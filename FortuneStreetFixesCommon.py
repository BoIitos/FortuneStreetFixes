class Asm:
	"""Minimal PowerPC assembler for the instructions used by the mods."""
	def __init__(self, base):
		self.base = base
		self.items = []
		self.labels = {}
	def addr(self):
		return self.base + 4 * len(self.items)
	def label(self, name):
		self.labels[name] = self.addr()
	def emit(self, word):
		self.items.append(word & 0xFFFFFFFF)
	def words(self):
		return [item(self.base + 4 * i) if callable(item) else item for i, item in enumerate(self.items)]
	def target(self, t):
		return self.labels[t] if isinstance(t, str) else t
	def d(self, op, rd, ra, imm):
		self.emit(op << 26 | rd << 21 | ra << 16 | imm & 0xFFFF)
	def x(self, rd, ra, rb, xo):
		self.emit(31 << 26 | rd << 21 | ra << 16 | rb << 11 | xo << 1)
	def addi(self, rd, ra, v): self.d(14, rd, ra, v)
	def li(self, rd, v): self.d(14, rd, 0, v)
	def lis(self, rd, v): self.d(15, rd, 0, v)
	def lwz(self, rd, off, ra): self.d(32, rd, ra, off)
	def lbz(self, rd, off, ra): self.d(34, rd, ra, off)
	def stw(self, rs, off, ra): self.d(36, rs, ra, off)
	def stwu(self, rs, off, ra): self.d(37, rs, ra, off)
	def stb(self, rs, off, ra): self.d(38, rs, ra, off)
	def lha(self, rd, off, ra): self.d(42, rd, ra, off)
	def sth(self, rs, off, ra): self.d(44, rs, ra, off)
	def lfs(self, frt, off, ra): self.d(48, frt, ra, off)
	def stfs(self, frs, off, ra): self.d(52, frs, ra, off)
	def mulli(self, rd, ra, v): self.d(7, rd, ra, v)
	def cmpwi(self, ra, v): self.d(11, 0, ra, v)
	def cmplwi(self, ra, v): self.d(10, 0, ra, v)
	def andi_(self, ra, rs, v): self.d(28, rs, ra, v)
	def lmw(self, rd, off, ra): self.d(46, rd, ra, off)
	def stmw(self, rs, off, ra): self.d(47, rs, ra, off)
	def cmpw(self, ra, rb): self.x(0, ra, rb, 0)
	def subf(self, rd, ra, rb): self.x(rd, ra, rb, 40)
	def or_(self, ra, rs, rb): self.x(rs, ra, rb, 444)
	def and_(self, ra, rs, rb): self.emit(31 << 26 | rs << 21 | ra << 16 | rb << 11 | 28 << 1 | 1)
	def slw(self, ra, rs, rb): self.x(rs, ra, rb, 24)
	def lbzx(self, rd, ra, rb): self.x(rd, ra, rb, 87)
	def stbx(self, rs, ra, rb): self.x(rs, ra, rb, 215)
	def lwzx(self, rd, ra, rb): self.x(rd, ra, rb, 23)
	def add(self, rd, ra, rb): self.x(rd, ra, rb, 266)
	def mr(self, ra, rs): self.x(rs, ra, rs, 444)
	def extsb(self, ra, rs): self.x(rs, ra, 0, 954)
	def slwi(self, ra, rs, n): self.emit(21 << 26 | rs << 21 | ra << 16 | n << 11 | (31 - n) << 1)
	def srwi(self, ra, rs, n): self.emit(21 << 26 | rs << 21 | ra << 16 | (32 - n) % 32 << 11 | n << 6 | 31 << 1)
	def mflr(self, rd): self.emit(0x7C0802A6 | rd << 21)
	def mtlr(self, rs): self.emit(0x7C0803A6 | rs << 21)
	def mtctr(self, rs): self.emit(0x7C0903A6 | rs << 21)
	def blr(self): self.emit(0x4E800020)
	def b(self, t, link=False):
		self.items.append(lambda pc, t=t: 18 << 26 | (self.target(t) - pc) & 0x03FFFFFC | int(link))
	def bl(self, t): self.b(t, True)
	def bc(self, bo, bi, t):
		self.items.append(lambda pc, t=t: 16 << 26 | bo << 21 | bi << 16 | (self.target(t) - pc) & 0xFFFC)
	def blt(self, t): self.bc(12, 0, t)
	def bgt(self, t): self.bc(12, 1, t)
	def ble(self, t): self.bc(4, 1, t)
	def bne(self, t): self.bc(4, 2, t)
	def bge(self, t): self.bc(4, 0, t)
	def beq(self, t): self.bc(12, 2, t)
	def bdnz(self, t): self.bc(16, 0, t)


def ha(v):
	return (v + 0x8000) >> 16 & 0xFFFF


def one(emit):
	a = Asm(0)
	emit(a)
	return a.items[0]


class Dol:
	"""main.dol opened for patching. Addresses are Boom Street addresses unless they come from allocate()."""
	def __init__(self, file, gameInstance, modid):
		self.file = file
		self.mapper = gameInstance.addressMapper()
		self.fsm = gameInstance.freeSpaceManager()
		self.modid = modid
	def std(self, addr):
		return self.mapper.boomStreetToStandard(addr)
	def file_offset(self, addr):
		return self.mapper.boomToFileAddress(self.mapper.standardToBoomStreet(addr))
	def read(self, addr):
		self.file.seek(self.file_offset(addr))
		return int.from_bytes(self.file.read(4), 'big')
	def write(self, addr, word):
		self.file.seek(self.file_offset(addr))
		self.file.write(word.to_bytes(4, 'big'))
	def patch(self, patches):
		"""Applies (Boom Street address, original, patched) tuples after checking the original."""
		for addr, orig, new in patches:
			current = self.read(self.std(addr))
			if current not in (orig, new):
				raise RuntimeError(f'{self.modid}: unexpected instruction {current:08X} at {addr:08X} (expected {orig:08X})')
			self.write(self.std(addr), new)
	def allocate(self, data, purpose):
		"""Stores data in free space and returns its address."""
		addr = self.fsm.allocateUnusedSpace(data, self.file, self.mapper, f'{self.modid} {purpose}', False)
		self.file.seek(self.file_offset(addr))
		self.file.write(data)
		return addr
	def install(self, assemble, hooks):
		"""assemble(base, std) -> Asm; hooks = (Boom Street address, original instruction, label, link)."""
		size = len(assemble(0, lambda addr: 0).items) * 4
		code_addr = self.allocate(bytes(size), 'routines')
		code = assemble(code_addr, self.std)
		for i, word in enumerate(code.words()):
			self.write(code_addr + 4 * i, word)
		for addr, orig, label, link in hooks:
			site = self.std(addr)
			current = self.read(site)
			if current != orig and current >> 26 != 18:
				raise RuntimeError(f'{self.modid}: unexpected instruction {current:08X} at {addr:08X} (expected {orig:08X})')
			self.write(site, 18 << 26 | (code.labels[label] - site) & 0x03FFFFFC | int(link))
