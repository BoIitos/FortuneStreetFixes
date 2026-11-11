"""Analyse the Memory::Heap instances of Boom Street (PAL ST7P01) in Dolphin memory dumps.

Dolphin: Debug > Memory > Dump MEM1 / Dump MEM2 writes mem1.raw and mem2.raw to
<User>/Dump. Rename them to keep several dumps, e.g. mem1_hang.raw / mem2_hang.raw.

Usage:
  python heapdump.py <dump dir> [suffix] [-map] [-sizes]
  python heapdump.py <dump dir> <suffix A> <suffix B>    compare two dumps

The suffix selects mem1<suffix>.raw / mem2<suffix>.raw; use "" for mem1.raw.
For each heap it prints free memory, the largest free blocks and the usage by
block tag (FourCC), and the completed rounds of the game. -map lists large blocks by address, -sizes the most common
block sizes per tag. Comparing prints the change per tag.

Heaps: task heap (Task::Heap, pointer at 0x808173F0, rest of MEM2; file buffers
come from here) and MEM1 heap (Memory::Wii::allocator at 0x804AC8C8, +4).
Info layout: +0 shift, +2 unit, +4 header size, +8 total, +0xC first block,
+0x10 free list, +0x14 free units. Block header: +0 tag, +4 size in units,
+0x10 next by address, +0x18 next free.
"""
import collections
import os
import struct
import sys

TASK_HEAP_P = 0x808173F0
MEM1_ALLOCATOR = 0x804AC8C8
G_BOARD = 0x8054D018                  # Gm::g_board; Gm::Player (0x4DC bytes) x4 at +0x2FA0


class Dump:
	def __init__(self, d, suffix):
		self.name = suffix or '(no suffix)'
		self.m1 = open(os.path.join(d, 'mem1%s.raw' % suffix), 'rb').read()
		self.m2 = open(os.path.join(d, 'mem2%s.raw' % suffix), 'rb').read()

	def buf(self, a):
		seg = a & 0xF0000000
		if seg in (0x80000000, 0xC0000000):
			return self.m1, a & 0x01FFFFFF
		if seg in (0x90000000, 0xD0000000):
			return self.m2, a & 0x0FFFFFFF
		raise ValueError('address %08X' % a)

	def u32(self, a):
		b, o = self.buf(a)
		return struct.unpack_from('>I', b, o)[0]

	def u16(self, a):
		b, o = self.buf(a)
		return struct.unpack_from('>H', b, o)[0]

	def u8(self, a):
		b, o = self.buf(a)
		return b[o]

	def rounds(self):
		"""Completed rounds as in Gm::Board::GetAroundTurn: minimum of Gm::Player+0x404 over active players."""
		turns = []
		for i in range(4):
			p = G_BOARD + 0x2FA0 + i * 0x4DC
			if self.u8(p + 0x470) and struct.unpack('>i', struct.pack('>I', self.u32(p + 0x464)))[0] <= 0:
				turns.append(self.u32(p + 0x404))
		return min(turns) if turns else None

	def heaps(self):
		return (('task heap', self.u32(TASK_HEAP_P)), ('MEM1 heap', self.u32(MEM1_ALLOCATOR + 4)))


def fourcc(v):
	s = struct.pack('>I', v)
	return s.decode('latin1') if all(32 <= c < 127 for c in s) else '%08X' % v


def mb(v):
	return '%.2f MB' % (v / 2**20)


class Heap:
	def __init__(self, dump, name, obj):
		self.name, self.obj = name, obj
		info = dump.u32(obj)
		self.info = info
		shift = dump.u8(info)
		self.total = dump.u32(info + 8)
		self.free_counter = dump.u32(info + 0x14) << shift
		free = set()
		a = dump.u32(info + 0x10)
		while a and len(free) < 1000000:
			free.add(a)
			a = dump.u32(a + 0x18)
		self.blocks = []  # (address, size, is free, tag)
		a = dump.u32(info + 0xC)
		while a and len(self.blocks) < 1000000:
			self.blocks.append((a, dump.u32(a + 4) << shift, a in free, fourcc(dump.u32(a))))
			a = dump.u32(a + 0x10)
		self.free = sorted((b for b in self.blocks if b[2]), key=lambda b: -b[1])
		self.used = collections.Counter()
		self.count = collections.Counter()
		for a, size, isfree, tag in self.blocks:
			if not isfree:
				self.used[tag] += size
				self.count[tag] += 1

	def report(self, sizes=False):
		print('== %s: Heap %08X Info %08X size %X (%s)' % (self.name, self.obj, self.info, self.total, mb(self.total)))
		print('   free %s in %d blocks (counter %s), %d blocks in total' % (
			mb(sum(b[1] for b in self.free)), len(self.free), mb(self.free_counter), len(self.blocks)))
		print('   largest free blocks: ' + ', '.join('%08X:%X (%s)' % (b[0], b[1], mb(b[1])) for b in self.free[:6]))
		print('   used by tag:')
		for tag, size in self.used.most_common():
			print('     %-8s %6d blocks %9X (%s)' % (tag, self.count[tag], size, mb(size)))
			if sizes:
				c = collections.Counter(s for a, s, f, t in self.blocks if not f and t == tag)
				print('              sizes: ' + ', '.join('%X x%d' % sn for sn in c.most_common(8)))

	def map(self):
		print('== map of %s (blocks >= 64 KB, free blocks >= 16 KB)' % self.name)
		for a, size, isfree, tag in self.blocks:
			if size >= 0x10000 or isfree and size >= 0x4000:
				print('   %08X %8X %s' % (a, size, 'FREE' if isfree else tag))


def compare(a, b):
	print('== %s: %s -> %s' % (a.name, mb(sum(x[1] for x in a.free)), mb(sum(x[1] for x in b.free))) + ' free, largest free block %s -> %s, free blocks %d -> %d' % (
		mb(a.free[0][1] if a.free else 0), mb(b.free[0][1] if b.free else 0), len(a.free), len(b.free)))
	print('   %-8s %15s %15s %16s' % ('tag', 'blocks', 'bytes', 'change'))
	for tag in sorted(set(a.used) | set(b.used), key=lambda t: -abs(b.used[t] - a.used[t])):
		d = b.used[tag] - a.used[tag]
		print('   %-8s %6d -> %6d %6X -> %6X %+6d / %+.2f MB' % (
			tag, a.count[tag], b.count[tag], a.used[tag], b.used[tag], b.count[tag] - a.count[tag], d / 2**20))


def main():
	args = [x for x in sys.argv[1:] if not x.startswith('-')]
	flags = set(x for x in sys.argv[1:] if x.startswith('-'))
	if not args:
		sys.exit(__doc__)
	d = args[0]
	suffixes = args[1:] or ['']
	dumps = [Dump(d, s) for s in suffixes]
	heaps = [[Heap(dump, n, o) for n, o in dump.heaps()] for dump in dumps]
	for dump in dumps:
		print('%s: %s completed rounds (Gm::Player+0x404)' % (dump.name, dump.rounds()))
	if len(dumps) == 1:
		for h in heaps[0]:
			h.report('-sizes' in flags)
			if '-map' in flags:
				h.map()
	else:
		print('comparing %s -> %s' % (dumps[0].name, dumps[1].name))
		for ha, hb in zip(heaps[0], heaps[1]):
			compare(ha, hb)


if __name__ == '__main__':
	main()
