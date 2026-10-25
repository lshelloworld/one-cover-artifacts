"""Load the table exports: 8-byte hashed cells, row-major, all-zero = NULL."""
import json, base64, glob, struct
DIR = 'data/hockey'; PREFIX = 'Hockey'
def use(dir_, prefix):
    global DIR, PREFIX; DIR, PREFIX = dir_, prefix
def load(table):
    f = glob.glob(f'{DIR}/{PREFIX}.{table}-*-full.json')[0]
    d = json.load(open(f))[0]; raw = base64.b64decode(d['rowData'])
    cols = [c['name'] for c in d['columns']]; n, c = d['rowCount'], len(cols)
    vals = struct.unpack(f'<{n*c}q', raw)
    rows = [tuple(None if v == 0 else v for v in vals[r*c:(r+1)*c]) for r in range(n)]
    nn = {col['name'] for col in d['columns'] if col['nullCount'] == 0}
    return cols, rows, nn
def tables():
    return sorted(f.split(PREFIX + '.')[1].split('-')[0] for f in glob.glob(f'{DIR}/{PREFIX}.*-full.json'))
