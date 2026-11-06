"""Compares the BFS from AiPathing with the original CalcDistance4Salary in unicorn.

Usage: test_ai_distance.py <main.dol without AiPathing> [tests] [max squares]   (needs: pip install unicorn)
The original function is exponential, so larger boards can take many minutes.
"""
import os, sys, struct, random, importlib.util
here = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [here, os.path.dirname(here)]
from unicorn import *
from unicorn.ppc_const import *
import AiPathing as m
dol = open(sys.argv[1], 'rb').read()
test_count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
max_squares = int(sys.argv[3]) if len(sys.argv) > 3 else 12

BOARD = m.G_BOARD
CODE = 0x81000000
RET = 0x80001800
mu = Uc(UC_ARCH_PPC, UC_MODE_PPC32 | UC_MODE_BIG_ENDIAN)
mu.mem_map(0x80000000, 0x01800000)
offs = struct.unpack('>18I', dol[0:72]); addrs = struct.unpack('>18I', dol[72:144]); sizes = struct.unpack('>18I', dol[144:216])
for o, a, s in zip(offs, addrs, sizes):
    if s: mu.mem_write(a, dol[o:o+s])
a = m.assemble(CODE, lambda x: x)
mu.mem_write(CODE, b''.join(struct.pack('>I', w) for w in a.words()))
mu.mem_write(RET, struct.pack('>I', 0x48000000))  # b .
NEW = a.labels['calc_distance']
ORIG = m.CALC_DISTANCE_4_SALARY

def make_board(n, rng):
    adj = {i: set() for i in range(n)}
    for i in range(1, n):          # spanning tree + extra edges, degree <= 4
        j = rng.randrange(i)
        if len(adj[j]) < 4: adj[i].add(j); adj[j].add(i)
        else: adj[i].add(i - 1); adj[i - 1].add(i)
    for _ in range(n // 2):
        i, j = rng.randrange(n), rng.randrange(n)
        if i != j and len(adj[i]) < 4 and len(adj[j]) < 4: adj[i].add(j); adj[j].add(i)
    data = bytearray(n * 0x54)
    for i in range(n):
        p = i * 0x54
        for k in range(4): data[p + 8 + 4 * k: p + 12 + 4 * k] = b'\xff' * 4
        nb = sorted(adj[i])[:4]
        for k, e in enumerate(nb):
            others = [x for x in nb if x != e]
            if rng.random() < 0.15 and len(others) > 1: others = others[:1]   # one-way-ish
            data[p + 8 + 4 * k] = e
            for q, d in enumerate(others[:3]): data[p + 9 + 4 * k + q] = d
        data[p + 0x4D] = rng.choice([0] * 8 + [1, 3, 4, 5, 6, 7, 8, 9, 10, 0x21, 0x22, 2])
    return bytes(data)

count = [0]; ovf=[0]
def hook(uc, addr, size, ud):
    count[0] += 1
    if addr == 0x8009CEF0: ovf[0] += 1
mu.hook_add(UC_HOOK_CODE, hook)

def call(fn, args):
    mu.reg_write(UC_PPC_REG_1, 0x80800000)
    mu.reg_write(UC_PPC_REG_LR, RET)
    for r, v in zip((UC_PPC_REG_3, UC_PPC_REG_4, UC_PPC_REG_5, UC_PPC_REG_6, UC_PPC_REG_7), args):
        mu.reg_write(r, v & 0xFFFFFFFF)
    count[0] = 0; ovf[0] = 0
    mu.emu_start(fn, RET, count=200_000_000)
    if mu.reg_read(UC_PPC_REG_PC) != RET: return None, count[0]
    return struct.unpack('>i', struct.pack('>I', mu.reg_read(UC_PPC_REG_3)))[0], count[0]

rng = random.Random(1); ovc=[0]; timeouts=[0]
tests = mism = 0; ti_o = ti_n = 0
for t in range(test_count):
    n = rng.randrange(4, max_squares)
    mu.mem_write(BOARD, make_board(n, rng))
    mu.mem_write(BOARD + 0x5414, struct.pack('>I', n))
    place = rng.randrange(n)
    ents = [x for x in mu.mem_read(BOARD + place * 0x54 + 8, 16)[0::4] if x != 0xff]
    prev = rng.choice(ents + [-1])
    mask = rng.randrange(16); wild = rng.choice([0, 0, 1, 2])
    args = (0x80700000, place, prev, mask, wild)
    ro, co = call(ORIG, args); ov = ovf[0]; rn, cn = call(NEW, args)
    if ov: ovc[0]+=1
    tests += 1; ti_o += co; ti_n += cn
    if ro is None: timeouts[0] += 1; print('orig timeout (>200M instructions), n =', n, 'new:', rn, cn); continue
    if ro != rn:
        mism += 1
        if mism < 10: print('MISMATCH', n, args[1:], ro, rn, 'orig stack overflows:', ov)
print('cases with orig overflow', ovc[0], 'orig timeouts', timeouts[0]); print(f'{tests} tests, {mism} mismatches, avg instructions orig {ti_o//tests}, new {ti_n//tests}')
