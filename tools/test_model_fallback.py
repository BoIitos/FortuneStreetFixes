"""Tests the model heap fallback from Board128Squares in unicorn, with stubs for the Construct functions.

Usage: test_model_fallback.py <main.dol of Boom Street>   (needs: pip install unicorn)
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
MODEL = 0x80700100
LOG = 0x80700000
ALLOCATOR = 0x804AC8C8             # Memory::Wii::allocator
NEW_OBJECT = 0x81230000
dol = open(sys.argv[1], 'rb').read()
sections = list(zip(struct.unpack('>18I', dol[0:72]), struct.unpack('>18I', dol[72:144]), struct.unpack('>18I', dol[144:216])))

mu = Uc(UC_ARCH_PPC, UC_MODE_PPC32 | UC_MODE_BIG_ENDIAN)
mu.mem_map(0x80000000, 0x01800000)
for offset, start, size in sections:
    if size:
        mu.mem_write(start, dol[offset:offset + size])
code = m.assemble(CODE, lambda addr: addr, 0x80001900, 0x80001A00)
mu.mem_write(CODE, b''.join(struct.pack('>I', word) for word in code.words()))
mu.mem_write(RET, struct.pack('>I', 0x48000000))
# stub: log r3-r7 to LOG, return NEW_OBJECT
stub = [0x3D008070] + [0x90080000 | r << 21 | (r - 3) * 4 for r in range(3, 8)] + [0x3C600000 | NEW_OBJECT >> 16, 0x4E800020]
for addr in (m.SCN_MDL_CONSTRUCT, m.SCN_MDL_SIMPLE_CONSTRUCT):
    mu.mem_write(addr, b''.join(struct.pack('>I', word) for word in stub))


def run(label, result):
    mu.mem_write(LOG, bytes(0x14))
    mu.mem_write(MODEL + 0x54, bytes(4))
    mu.reg_write(UC_PPC_REG_1, STACK)
    mu.reg_write(UC_PPC_REG_LR, RET)
    mu.reg_write(UC_PPC_REG_3, result)
    mu.reg_write(UC_PPC_REG_30, 0x30C)
    mu.reg_write(UC_PPC_REG_31, MODEL)
    mu.emu_start(code.labels[label], RET, count=200)
    assert mu.reg_read(UC_PPC_REG_PC) == RET and mu.reg_read(UC_PPC_REG_1) == STACK
    assert mu.reg_read(UC_PPC_REG_30) == 0x30C and mu.reg_read(UC_PPC_REG_31) == MODEL
    return struct.unpack('>I', mu.mem_read(MODEL + 0x54, 4))[0], struct.unpack('>5I', mu.mem_read(LOG, 0x14))


# a model that was created is stored unchanged, without a second attempt
for label in ('model_fallback', 'model_simple_fallback'):
    stored, log = run(label, 0x81111110)
    assert stored == 0x81111110 and log == (0, 0, 0, 0, 0), (label, hex(stored), log)
# a failed model is created again from the normal heap with the same arguments
stored, log = run('model_fallback', 0)
assert stored == NEW_OBJECT and log == (ALLOCATOR, 0, STACK + 8, 0x30C, 1), (hex(stored), [hex(x) for x in log])
stored, log = run('model_simple_fallback', 0)
assert stored == NEW_OBJECT and log[:4] == (ALLOCATOR, 0, STACK + 0xC, 1), (hex(stored), [hex(x) for x in log])
print('all checks passed')
