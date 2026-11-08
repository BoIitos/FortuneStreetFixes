"""Checks the mods against a main.dol without running CSMM. Only needs the Python standard library.

Usage: offline_check.py <main.dol> [boom|fortune|itadaki] [reference main.dol of Boom Street]

Prints every patch site whose original instruction does not match, then runs all mods on a temporary
copy of the file. With a reference file, it also compares the code around all sites. The reference and
the checked file may be CSMM builds, in which case some differences are expected. Free space is
simulated at FREE_SPACE, which is not free in reality, so the result must not be used as a game file.
"""
import os, sys, shutil, struct, tempfile, importlib

here = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [here, os.path.join(os.path.dirname(here), 'mod')]
MODS = ('Board128Squares', 'AiPathing', 'AiNumberInput', 'EightShopDistricts')
FREE_SPACE = 0x80390000

# (first Boom Street address, last Boom Street address, delta), see GameInstance in CSMM (lib/gameinstance.cpp)
VERSIONS = {
    'boom': [(0x80000100, 0x81800000, 0)],
    'fortune': [(0x80000100, 0x8007A283, 0), (0x8007A2F4, 0x80268717, 0x54), (0x80268720, 0x8040D97B, 0x50),
                (0x8040D980, 0x8041027F, 0x40), (0x804105F0, 0x8044EBE7, 0x188), (0x8044EC00, 0x804AC804, 0x1A0),
                (0x804AC880, 0x8081F013, 0x200)],
    'itadaki': [(0x80000100, 0x8007A244, 0), (0x8007A2F4, 0x80268717, 0x94), (0x8026871F, 0x8040D97B, 0x90),
                (0x8040D97F, 0x80410278, 0x80), (0x80410578, 0x8044EBE3, 0x2A8), (0x8044EBFF, 0x804AC804, 0x2C0),
                (0x804AC880, 0x8081F013, 0x300)],
}


class DolFile:
    def __init__(self, path):
        self.data = d = open(path, 'rb').read()
        self.sections = list(zip(struct.unpack('>18I', d[0:72]), struct.unpack('>18I', d[72:144]), struct.unpack('>18I', d[144:216])))
    def offset(self, addr):
        for offset, start, size in self.sections:
            if size and start <= addr < start + size:
                return offset + addr - start
        return None
    def word(self, addr):
        o = self.offset(addr)
        return None if o is None else struct.unpack('>I', self.data[o:o + 4])[0]


class Mapper:
    def __init__(self, dol, table):
        self.dol, self.table = dol, table
    def boomStreetToStandard(self, addr):
        for first, last, delta in self.table:
            if first <= addr <= last:
                return addr - delta
        raise ValueError(f'{addr:08X} is not mapped')
    def toFileAddress(self, addr):
        return self.dol.offset(addr)


class FreeSpace:
    def __init__(self):
        self.next = FREE_SPACE
    def allocateUnusedSpace(self, data, file, mapper, purpose, reuse):
        addr = self.next
        self.next += (len(data) + 3) & ~3
        print(f'  {addr:08X} {len(data):5X} {purpose}')
        return addr


class Game:
    def __init__(self, mapper):
        self.mapper, self.free = mapper, FreeSpace()
    def addressMapper(self):
        return self.mapper
    def freeSpaceManager(self):
        return self.free


def relocatable(word):
    """Masks branch displacements, which legitimately change between versions."""
    if word is None:
        return None
    op = word >> 26
    return word & 0xFC000003 if op == 18 else word & 0xFFFF0003 if op == 16 else word


def main():
    path = sys.argv[1]
    version = sys.argv[2] if len(sys.argv) > 2 else 'boom'
    dol = DolFile(path)
    mapper = Mapper(dol, VERSIONS[version])
    std = mapper.boomStreetToStandard
    board, ai, number, shops = (importlib.import_module(name) for name in MODS)

    groups = {
        'Board128Squares': board.PATCHES + board.quick_save_patches(std(board.G_BOARD)),
        'AiPathing': ai.PATCHES,
        'EightShopDistricts': shops.area_ui_patches(0, std(shops.AREA_UI_NAMES)),
        'hooks': [(addr, orig, None) for mod in (board, ai, number, shops) for addr, orig, _, _ in mod.HOOKS],
    }
    for name, entries in groups.items():
        wrong = [(addr, orig, dol.word(std(addr))) for addr, orig, _ in entries if dol.word(std(addr)) != orig]
        print(f'{name}: {len(entries) - len(wrong)} of {len(entries)} original')
        for addr, orig, current in wrong:
            branch = ' (branch, accepted by the hook check)' if current is not None and current >> 26 == 18 else ''
            print(f'  {addr:08X} -> {std(addr):08X}: expected {orig:08X}, found {current:08X}{branch}')

    if len(sys.argv) > 3:
        ref = DolFile(sys.argv[3])
        sites = sorted({entry[0] for entries in groups.values() for entry in entries})
        same = total = 0
        for addr in sites:
            for i in range(-8, 9):
                total += 1
                same += relocatable(ref.word(addr + 4 * i)) == relocatable(dol.word(std(addr + 4 * i)))
        print(f'code around {len(sites)} sites: {same} of {total} words equal')

    with tempfile.TemporaryDirectory() as root:
        os.mkdir(os.path.join(root, 'sys'))
        shutil.copy(path, os.path.join(root, 'sys', 'main.dol'))
        game = Game(mapper)
        for mod in (board, ai, number, shops):
            print(mod.__name__)
            mod.mod.saveFiles(root, game, [])
    print('all mods completed')


if __name__ == '__main__':
    main()
