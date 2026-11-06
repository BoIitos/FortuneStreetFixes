import sys, struct
d = open(sys.argv[1], 'rb').read()
n = struct.unpack('>H', d[0xE:0x10])[0]
o = 0x10; depth = 0
for _ in range(n):
    magic = d[o:o+4]; size = struct.unpack('>I', d[o+4:o+8])[0]
    m = magic.decode()
    if m == 'pas1': depth += 1
    elif m == 'pae1': depth -= 1
    elif m in ('pan1', 'pic1', 'txt1', 'bnd1', 'wnd1'):
        name = d[o+0xC:o+0x1C].split(b'\0')[0].decode()
        tx, ty, tz, rx, ry, rz, sx, sy, w, h = struct.unpack('>10f', d[o+0x24:o+0x4C])
        vis = d[o+8] & 1
        print(f"{'  '*depth}{m} {name:20s} pos=({tx:.0f},{ty:.0f}) size=({w:.0f}x{h:.0f}){'' if vis else ' hidden'}")
    elif m in ('grp1',):
        pass
    o += size
