"""Compares the guarded GXGetChanMatColor/GXSetChanMatColor from Board128Squares with the originals in unicorn.

Usage: test_mat_color_guard.py <main.dol of Boom Street>   (needs: pip install unicorn)
"""
import os, sys, struct
here = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [here, os.path.join(os.path.dirname(here), 'mod')]
from unicorn import *
from unicorn.ppc_const import *
import Board128Squares as m

CODE = 0x81000000
RET = 0x80001800
STACK = 0x80800000
THIS = 0x80700000
RES = 0x80700100
COLOR = 0x80700200
OUT = 0x80700300
SET = 0x803481E0
GET = 0x80348240
dol = open(sys.argv[1], 'rb').read()
sections = zip(struct.unpack('>18I', dol[0:72]), struct.unpack('>18I', dol[72:144]), struct.unpack('>18I', dol[144:216]))


def machine(guarded):
    mu = Uc(UC_ARCH_PPC, UC_MODE_PPC32 | UC_MODE_BIG_ENDIAN)
    mu.mem_map(0x80000000, 0x01800000)
    for offset, start, size in sections_list:
        if size:
            mu.mem_write(start, dol[offset:offset + size])
    mu.mem_write(RET, struct.pack('>I', 0x48000000))
    if guarded:
        code = m.assemble(CODE, lambda addr: addr, 0x80001900, 0x80001A00)
        mu.mem_write(CODE, b''.join(struct.pack('>I', word) for word in code.words()))
        for addr, orig, label, link in m.HOOKS:
            if addr in (m.MAT_COLOR_SET, m.MAT_COLOR_GET):
                assert struct.unpack('>I', mu.mem_read(addr, 4))[0] == orig
                mu.mem_write(addr, struct.pack('>I', 18 << 26 | (code.labels[label] - addr) & 0x03FFFFFC | int(link)))
    return mu


def call(mu, fn, res, channel):
    mu.mem_write(THIS, struct.pack('>I', res))
    mu.mem_write(RES, bytes(range(0x10, 0x40)))
    mu.mem_write(COLOR, bytes((0xA1, 0xB2, 0xC3, 0xD4)))
    mu.mem_write(OUT, bytes(4))
    mu.reg_write(UC_PPC_REG_1, STACK)
    mu.reg_write(UC_PPC_REG_LR, RET)
    mu.reg_write(UC_PPC_REG_3, THIS)
    mu.reg_write(UC_PPC_REG_4, channel)
    mu.reg_write(UC_PPC_REG_5, COLOR if fn == SET else OUT)
    mu.emu_start(fn, RET, count=200)
    assert mu.reg_read(UC_PPC_REG_PC) == RET, 'did not return'
    return bytes(mu.mem_read(RES, 0x30)), bytes(mu.mem_read(OUT, 4)), mu.reg_read(UC_PPC_REG_3)


sections_list = list(sections)
original, guarded = machine(False), machine(True)
checks = 0
for fn in (SET, GET):
    for channel in (0, 1, 2, 3, 4, 5):
        a, b = call(original, fn, RES, channel), call(guarded, fn, RES, channel)
        assert a == b, (hex(fn), channel, a, b)
        checks += 1
        result = call(guarded, fn, 0, channel)
        assert result[0] == bytes(range(0x10, 0x40)) and result[1] == bytes(4), (hex(fn), channel, result)
        checks += 1
print(f'{checks} checks passed: same result with a valid pointer, no access with NULL')
