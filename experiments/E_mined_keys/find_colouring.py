import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Search the mined partial keys of every Hockey table, with the profiled NOT NULL columns,
for certain keys implied by a combination of partial keys but by no single one."""
import sys, itertools, collections; sys.path.insert(0, 'experiments/lib')
from keys import implies, popcount
from hockey_data import load, tables
from check_mined import read, holds
full = set(tables())
for level in [1, 9]:
    T = read(level); found = []
    for t, keys in sorted(T.items()):
        if t not in full: continue
        cols, rows, nn = load(t); ci = {c: i for i, c in enumerate(cols)}
        NN = sum(1 << ci[c] for c in nn)
        P = sorted({sum(1 << ci[c] for c in K) for cls, K in keys if cls == 'partial'})
        single = lambda K: any(implies([('partial', L)], ('certain', K), NN) for L in P)
        seen = set()
        for r in (2, 3, 4, 5):
            for combo in itertools.combinations(P, r):
                K = 0
                for L in combo: K |= L
                if K in seen or popcount(K & ~NN) > 12: continue
                seen.add(K)
                if implies([('partial', L) for L in P if L & ~K == 0], ('certain', K), NN) and not single(K):
                    edges = [L for L in P if L & ~K == 0]
                    found.append((t, [c for c in cols if K >> ci[c] & 1], [[c for c in cols if L >> ci[c] & 1] for L in edges],
                                  holds(rows, [i for i in range(len(cols)) if K >> i & 1], 'certain')))
        print(f'level {level}: {t:18s} {len(P):3d} partial keys, unions checked: {len(seen)}', flush=True) if P else None
    print(f'level {level}: certain keys implied only by combinations of partial keys: {len(found)}')
    for f in found[:10]: print('   ', f[0], 'certain(' + ','.join(f[1]) + ')', 'from', f[2], 'holds on data:', f[3])
