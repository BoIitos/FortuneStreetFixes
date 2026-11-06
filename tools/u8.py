import sys, struct, os
d = open(sys.argv[1], 'rb').read()
assert d[:4] == b'\x55\xAA\x38\x2D'
root, hsize, doff = struct.unpack('>III', d[4:16])
n = struct.unpack('>I', d[root+8:root+12])[0]
st = root + n*12
names = []
def name(o): return d[st+o:d.index(b'\0', st+o)].decode()
path = []; ends = []
out = sys.argv[2]
for i in range(n):
    t, no, a, b = d[root+i*12], int.from_bytes(d[root+i*12+1:root+i*12+4],'big'), *struct.unpack('>II', d[root+i*12+4:root+i*12+12])
    while ends and ends[-1] <= i: ends.pop(); path.pop()
    nm = name(no)
    if t == 1:
        if i: path.append(nm); ends.append(b)
    else:
        p = os.path.join(out, *path, nm)
        if sys.argv[3] in nm:
            os.makedirs(os.path.dirname(p), exist_ok=True); open(p,'wb').write(d[a:a+b]); print(p, b)
