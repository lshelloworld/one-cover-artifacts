import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment E: covers of mined Hockey keys at orthogonality levels 1 and 9,
with and without the NOT NULL columns known from the profiler metadata."""
import sys, json, time, collections
sys.path.insert(0, 'experiments/lib')
from keys import *
U = 'data/mined_keys'
FILES = {1: {c: f'{U}/mined_{c}_keys.txt' for c in ['possible','domain','partial','certain']},
         9: {c: f'{U}/{c}_keys-orth9.txt' for c in ['possible','domain','partial','certain']}}
# NOT NULL columns = null count 0 in the profiler screenshot (covers three tables only)
NOTNULL = {t: set(v) for t, v in json.load(open('results/E_mined_keys/hockey/notnull.json')).items()}  # null count 0 in the profiler
def load(level):
    tables = collections.defaultdict(lambda: collections.defaultdict(set))
    for cls, f in FILES[level].items():
        for line in open(f):
            line = line.strip()
            if not line: continue
            t, cols = line.split('['); tables[t.split('.')[1]][cls].add(frozenset(cols.rstrip(']').split(',')))
    return tables
def analyse(level, use_nn):
    tables = load(level); rows = []
    for t in sorted(tables):
        colset = sorted({c for s in tables[t].values() for k in s for c in k}); ci = {c: i for i, c in enumerate(colset)}
        mask = lambda k: sum(1 << ci[c] for c in k)
        S = [(cls, mask(k)) for cls, ks in tables[t].items() for k in ks]
        NN = mask(NOTNULL.get(t, set()) & set(colset)) if use_nn else 0
        t0 = time.perf_counter(); G = mincover_general(S, NN); dt = time.perf_counter() - t0
        idx = lambda keys: sum(2 ** popcount(m & ~NN) if c in ('partial', 'certain') else 1 for c, m in keys)
        # with NN, a certain key on NOT NULL columns is a candidate key: one plain UNIQUE index
        rows.append(dict(table=t, columns=len(colset), declared=len(S), cover=len(G), occ_in=occ(S), occ_out=occ(G),
                         idx_in=idx(S), idx_out=idx(G), time_ms=dt * 1000, nn=popcount(NN),
                         per_in=dict(collections.Counter(c for c, _ in S)), per_out=dict(collections.Counter(c for c, _ in G)),
                         cover_keys=sorted(f'{c}({",".join(colset[i] for i in range(len(colset)) if m >> i & 1)})' for c, m in G)))
    return rows
out = {}
for level in [1, 9]:
    for use_nn in [False, True]:
        rows = analyse(level, use_nn); out[f'L{level}_NN{int(use_nn)}'] = rows
        tot = lambda k: sum(r[k] for r in rows)
        rec = rows
        print(f'level {level} NN={use_nn}: declared {tot("declared")} cover {tot("cover")} idx {tot("idx_in")}->{tot("idx_out")} | '
              f'3 NN tables: declared {sum(r["declared"] for r in rec)} cover {sum(r["cover"] for r in rec)} idx {sum(r["idx_in"] for r in rec)}->{sum(r["idx_out"] for r in rec)} time {tot("time_ms"):.0f}ms')
        if level == 9 and not use_nn:
            for r in sorted(rows, key=lambda r: -r['declared']): print('   ', r['table'], r['declared'], dict(r['per_in']), '->', r['cover'], dict(r['per_out']), 'idx', r['idx_in'], '->', r['idx_out'])
json.dump(out, open('results/E_mined_keys/hockey/real_covers_levels.json', 'w'), indent=1)
