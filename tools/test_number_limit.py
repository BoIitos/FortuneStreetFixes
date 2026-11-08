"""Tests the AI number input limit from AiNumberInput in unicorn.

Usage: test_number_limit.py   (needs: pip install unicorn)
"""
import os, sys, struct
here = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [here, os.path.join(os.path.dirname(here), 'mod')]
from unicorn import *
from unicorn.ppc_const import *
import AiNumberInput as m

CODE = 0x80100000
RET = 0x80001800
UI = 0x80200000

mu = Uc(UC_ARCH_PPC, UC_MODE_PPC32 | UC_MODE_BIG_ENDIAN)
mu.mem_map(0x80000000, 0x00400000)
code = m.assemble(CODE, lambda addr: addr)
mu.mem_write(CODE, b''.join(struct.pack('>I', word) for word in code.words()))
mu.mem_write(RET, struct.pack('>I', 0x48000000))


def run(digits, target):
    mu.mem_write(UI + m.NUMBER_DIGITS, struct.pack('>i', digits))
    mu.reg_write(UC_PPC_REG_LR, RET)
    mu.reg_write(UC_PPC_REG_3, UI)
    mu.reg_write(UC_PPC_REG_29, 0x1234)
    mu.reg_write(UC_PPC_REG_31, target & 0xFFFFFFFF)
    mu.emu_start(code.labels['number_limit'], RET, count=100)
    assert mu.reg_read(UC_PPC_REG_PC) == RET and mu.reg_read(UC_PPC_REG_29) == 0 and mu.reg_read(UC_PPC_REG_3) == UI
    return struct.unpack('>i', struct.pack('>I', mu.reg_read(UC_PPC_REG_31)))[0]


checks = 0
for digits, target, expected in [(3, 1188, 999), (3, 1000, 999), (3, 999, 999), (3, 188, 188), (3, 0, 0),
                                 (1, 12, 9), (6, 1188, 1188), (6, 1000000, 999999), (5, 99999, 99999),
                                 (0, 1188, 1188), (-1, 1188, 1188)]:
    result = run(digits, target)
    assert result == expected, (digits, target, result, expected)
    checks += 1
print(f'{checks} checks passed')
