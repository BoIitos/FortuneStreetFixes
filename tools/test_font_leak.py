"""Tests the duplicate check from LayoutFontLeak in unicorn.

Usage: test_font_leak.py   (needs: pip install unicorn)
"""
import os, sys, struct
here = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [here, os.path.join(os.path.dirname(here), 'mod')]
from unicorn import *
from unicorn.ppc_const import *
import LayoutFontLeak as m

CODE = 0x80100000
APPEND = 0x80001800                   # stands for SET_EXTRA_FONT_NEXT
SKIP = 0x80001900                     # stands for SET_EXTRA_FONT_DONE
OBJ = 0x80200000
HOLDER = 0x80201000
VECTOR = 0x80210000
STACK = 0x80300000
FONT, OTHER, LINK = 0x92C87260, 0x92C1B5A0, 0x81597C00

std = {m.SET_EXTRA_FONT_NEXT: APPEND, m.SET_EXTRA_FONT_DONE: SKIP}
mu = Uc(UC_ARCH_PPC, UC_MODE_PPC32 | UC_MODE_BIG_ENDIAN)
mu.mem_map(0x80000000, 0x00400000)
code = m.assemble(CODE, lambda addr: std[addr])
mu.mem_write(CODE, b''.join(struct.pack('>I', word) for word in code.words()))
for addr in (APPEND, SKIP):
    mu.mem_write(addr, struct.pack('>I', 0x48000000))


def run(entries, font):
    mu.mem_write(OBJ + m.HOLDER, struct.pack('>I', HOLDER))
    mu.mem_write(HOLDER + m.FONTS_BEGIN, struct.pack('>II', VECTOR if entries else 0, len(entries)))
    for i, (holder, link) in enumerate(entries):
        mu.mem_write(VECTOR + 16 * i, struct.pack('>4I', holder, 0x815B3680, link, 0x815B3D80 if link else 0))
    mu.mem_write(STACK + m.PAIR, struct.pack('>4I', font, 0x815B3680, 0, 0))
    mu.reg_write(UC_PPC_REG_1, STACK)
    mu.reg_write(UC_PPC_REG_28, OBJ)
    mu.reg_write(UC_PPC_REG_29, 0)
    mu.emu_start(code.labels['extra_font'], 0, count=20 + 8 * len(entries))
    pc = mu.reg_read(UC_PPC_REG_PC)
    assert pc in (APPEND, SKIP), hex(pc)
    assert mu.reg_read(UC_PPC_REG_29) == HOLDER and mu.reg_read(UC_PPC_REG_28) == OBJ and mu.reg_read(UC_PPC_REG_1) == STACK
    return 'skip' if pc == SKIP else 'append'


checks = 0
for entries, font, expected in [
        ([], FONT, 'append'),
        ([(FONT, 0)], FONT, 'skip'),
        ([(FONT, LINK)], FONT, 'append'),
        ([(OTHER, LINK), (OTHER, 0)], FONT, 'append'),
        ([(OTHER, LINK)] * 9 + [(FONT, 0)], FONT, 'skip'),
        ([(FONT, LINK), (OTHER, 0), (FONT, 0), (OTHER, LINK)], FONT, 'skip'),
        ([(OTHER, 0)] * 50, FONT, 'append')]:
    result = run(entries, font)
    assert result == expected, (entries, result, expected)
    checks += 1
print(f'{checks} checks passed')
