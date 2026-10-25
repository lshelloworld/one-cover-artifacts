import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment E on the VOC database: covers of the keys mined at orthogonality level 1,
with and without the profiled NOT NULL columns."""
import sys, json, itertools, collections, time
sys.path.insert(0, 'experiments/lib'); from keys import mincover_general, implies, popcount, RANK
U = 'data/mined_keys'
FILES = {'possible': '1791953466091_voc-possible-orth1.txt', 'domain': '1791953466092_voc-domain-orth1.txt',
         'partial': '1791953466092_voc-partial-orth.txt', 'certain': '1791953466092_voc-certain-orth1.txt'}
prof = json.load(open('data/profiles/voc_profile.json'))
T = collections.defaultdict(list)
for cls, f in FILES.items():
    for line in open(f'{U}/{f}', encoding='utf-8-sig'):
        line = line.strip()
        if line: t, cs = line.split('['); T[t.split('.')[1]].append((cls, tuple(cs.rstrip(']').split(','))))
def idx(keys, NN): return sum(2 ** popcount(m & ~NN) if c in ('partial', 'certain') else 1 for c, m in keys)
res = {}; agg = collections.Counter()
for t in sorted(T, key=lambda x: -len(T[x])):
    cols = sorted({c for _, K in T[t] for c in K} | set(prof[t])); ci = {c: i for i, c in enumerate(cols)}
    S = [(cls, sum(1 << ci[c] for c in K)) for cls, K in T[t]]
    nnset = {c for c, v in prof[t].items() if v['nulls'] == 0}; NN1 = sum(1 << ci[c] for c in nnset)
    per = collections.Counter(c for c, _ in S); row = dict(table=t, declared=len(S), per=dict(per))
    for tag, NN in (('nn0', 0), ('nn1', NN1)):
        t0 = time.perf_counter(); G = mincover_general(S, NN); dt = time.perf_counter() - t0
        Gs = set(G); rem = [k for k in S if k not in Gs]
        why = collections.Counter()
        for c, K in rem:
            others = [k for k in S if k != (c, K)]
            if any(L == K and RANK[c2] > RANK[c] for c2, L in S): why['R1 same columns, stronger class'] += 1
            elif any(L & ~K == 0 and L != K for _, L in others) and implies([k for k in others if k[1] & ~K == 0 and k[1] != K], (c, K), NN): why['R2 superkey'] += 1
            elif c == 'certain' and implies([k for k in others if k[0] == 'partial'], (c, K), NN) and not any(implies([k], (c, K), NN) for k in others): why['colouring'] += 1
            else: why['R3/R4 (NOT NULL)'] += 1
        row[tag] = dict(cover=len(G), per_out=dict(collections.Counter(c for c, _ in G)), idx_in=idx(S, NN), idx_out=idx(G, NN),
                        why=dict(why), ms=dt * 1000, removed=sorted(f'{c}({",".join(cc for cc in cols if K >> ci[cc] & 1)})' for c, K in rem))
        agg[f'{tag}_cover'] += len(G); agg[f'{tag}_idx_in'] += idx(S, NN); agg[f'{tag}_idx_out'] += idx(G, NN)
        for w, n in why.items(): agg[f'{tag}:{w}'] += n
    agg['declared'] += len(S); res[t] = row
    print(f"{t:11s} {len(S):3d} keys ({per['possible']}/{per['domain']}/{per['partial']}/{per['certain']}) "
          f"| NN=∅: cover {row['nn0']['cover']:3d}, indexes {row['nn0']['idx_in']}->{row['nn0']['idx_out']} {row['nn0']['why']} "
          f"| NOT NULL: cover {row['nn1']['cover']:3d}, indexes {row['nn1']['idx_in']}->{row['nn1']['idx_out']} {row['nn1']['why']}")
print(dict(agg))
json.dump(res, open('results/E_mined_keys/voc/voc_covers.json', 'w'), indent=1)
