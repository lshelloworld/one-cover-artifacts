import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment E: covers of the keys mined from the Hockey database (all classes,
arity <= 5, completeness 0, orthogonality level 1; minimal per class).
NOT NULL information is not part of the mined lists, so NN = {} throughout
(this only under-estimates redundancy: R3/R4 never fire)."""
import sys, json, time, collections
sys.path.insert(0, 'experiments/lib')
from keys import *
U = 'data/mined_keys'
tables = collections.defaultdict(lambda: collections.defaultdict(set))
for cls in ['possible', 'domain', 'partial', 'certain']:
    for line in open(f'{U}/mined_{cls}_keys.txt'):
        line = line.strip()
        if not line: continue
        t, cols = line.split('['); cols = cols.rstrip(']').split(',')
        tables[t.split('.')[1]][cls].add(frozenset(cols))
rows = []
LOG = open('results/E_mined_keys/hockey/real_covers_log.jsonl', 'w')
def idx(keys):
    return sum(2 ** popcount(m) if c in ('partial', 'certain') else 1 for c, m in keys)
for t in sorted(tables):
    colset = sorted({c for s in tables[t].values() for k in s for c in k}); ci = {c: i for i, c in enumerate(colset)}
    mask = lambda k: sum(1 << ci[c] for c in k)
    S = [(cls, mask(k)) for cls, ks in tables[t].items() for k in ks]
    NN = 0
    t0 = time.perf_counter(); G = mincover_general(S, NN); dt = time.perf_counter() - t0
    # fragment views: which declared keys survive, by class
    per_in = collections.Counter(c for c, _ in S); per_out = collections.Counter(c for c, _ in G)
    # how many removals needed the colouring test (certain key without certain/candidate premise inside it)
    colour_removed = 0
    for c, K in S:
        if c == 'certain' and (c, K) not in G and not any(c2 == 'certain' and subset(L, K) and L != K for c2, L in S):
            colour_removed += 1
    rec = dict(table=t, columns=len(colset), declared=len(S), cover=len(G), occ_in=occ(S), occ_out=occ(G),
               idx_in=idx(S), idx_out=idx(G), time_ms=round(dt * 1000, 2), per_in=dict(per_in), per_out=dict(per_out),
               colour_removed=colour_removed,
               cover_keys=sorted(f'{c}({",".join(colset[i] for i in range(len(colset)) if m >> i & 1)})' for c, m in G))
    LOG.write(json.dumps(rec) + '\n'); rows.append(rec)
    print(f"{t:18s} cols={len(colset):3d} declared={len(S):5d} ({per_in['possible']}/{per_in['domain']}/{per_in['partial']}/{per_in['certain']}) cover={len(G):4d} ({per_out['possible']}/{per_out['domain']}/{per_out['partial']}/{per_out['certain']}) occ {occ(S)}->{occ(G)} idx {idx(S)}->{idx(G)} colour={colour_removed} {dt*1000:.1f}ms")
tot = lambda k: sum(r[k] for r in rows)
print('TOTAL declared', tot('declared'), 'cover', tot('cover'), 'occ', tot('occ_in'), '->', tot('occ_out'), 'idx', tot('idx_in'), '->', tot('idx_out'), 'time', round(tot('time_ms'), 1), 'ms')
json.dump(rows, open('results/E_mined_keys/hockey/real_covers.json', 'w'), indent=1)
