import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""A cost model of the PostgreSQL enforcement scheme for the million-row runs, computed from the key sets alone.

In the workload a row has, with probability 0.3, a null in one uniformly chosen nullable column (6 of 8),
so a nullable column is null in 5 % of rows and no row has two nulls. For a partial or certain key with
NOT NULL part X and nullable part N_K, the trigger probes, for a new row of null pattern P, the filtered
index of each pattern P' (P' comparable with P for partial keys, all P' for certain keys); that index has
columns X + (N_K minus P') and the probe binds X + (N_K minus P minus P'). It is a point lookup unless the
new row's null column c lies outside P' (c is then free); if c leads the index (X empty and c the first
column of N_K minus P'), nothing narrows the search and the probe scans the whole filtered index, whose size
is the share of rows with pattern P' (1 - 0.05|N_K| for P' empty, 0.05 for a single column, 0 otherwise).
Reports per key set: probes per insert, and scanned index entries per insert as a share of the table size
(times 10^6 rows = expected entries scanned per insert at the end of a million-row run), for input and cover,
next to the measured speed-ups. Writes results/D_enforcement/probe_model.json."""
import json, itertools, statistics, importlib
from exp_db2_pg import N, K, cols

PN = 0.3 / (N - K)                                        # P(a given nullable column is null in a row)
def subsets(lst): return [list(c) for r in range(len(lst) + 1) for c in itertools.combinations(lst, r)]
def pat_share(P, NK): return (1 - PN * len(NK)) if not P else (PN if len(P) == 1 else 0.0)

def cost(keys, NN):
    probes = scan = 0.0
    for cls, M in keys:
        if cls not in ('partial', 'certain'): continue
        X = cols(M & NN); NK = cols(M & ~NN)
        for P in [[]] + [[c] for c in NK]:                # the new row's pattern on this key
            w = pat_share(P, NK)
            for P2 in subsets(NK):
                if cls == 'partial' and not (set(P) <= set(P2) or set(P2) <= set(P)): continue
                probes += w
                free = [c for c in P if c not in P2]
                if free and not X and [c for c in NK if c not in P2][0] == free[0]:
                    scan += w * pat_share(P2, NK)
    return probes, scan

if __name__ == '__main__':
    out = []
    for ks, f in ((0, 'results/D_enforcement/db2_pg_extra.jsonl'), (1, 'results/D_enforcement/db2_pg_extra_ks1.jsonl'),
                  (2, 'results/D_enforcement/db2_pg_extra_ks2.jsonl'), (3, 'results/D_enforcement/db2_pg_extra_ks3.jsonl')):
        if not _os.path.exists(f): continue
        _os.environ['ONECOVER_KEYSET'] = str(ks)
        import exp_db2_pg_extra as E; E = importlib.reload(E)
        for l in open(f):
            r = json.loads(l)
            if r.get('exp') != 'xl' or r['m'] < 30: continue
            S, G, NN = E.keyset(r['m'])
            assert len(S) == r['in_keys'] and len(G) == r['out_keys'], (ks, r['m'])
            (pS, sS), (pG, sG) = cost(S, NN), cost(G, NN)
            s, c = r['sigma'], r['cover']
            out.append(dict(keyset=ks, m=r['m'], idx_removed=1 - c['objects'] / s['objects'],
                            probes=(round(pS, 2), round(pG, 2)), scan_per_1M=(round(sS * 1e6), round(sG * 1e6)),
                            gain_ins=s['t_insert'] / c['t_insert'], gain_upd=s['t_update'] / c['t_update']))
    json.dump(out, open('results/D_enforcement/probe_model.json', 'w'), indent=1)
    print('ks  m  idx removed  probes in/cover (ratio)   scanned per insert at 1M in/cover (ratio)   gain ins upd')
    for o in sorted(out, key=lambda o: o['gain_ins']):
        pr = o['probes'][0] / max(o['probes'][1], 1e-9); sr = o['scan_per_1M'][0] / max(o['scan_per_1M'][1], 1)
        print(f"{o['keyset']}  {o['m']}  {100*o['idx_removed']:5.0f}%      {o['probes'][0]:6.1f}/{o['probes'][1]:5.1f} ({pr:4.1f})"
              f"          {o['scan_per_1M'][0]:7d}/{o['scan_per_1M'][1]:6d} ({sr:5.1f})            {o['gain_ins']:4.1f} {o['gain_upd']:4.1f}")
    def spearman(a, b):
        ra = {v: i for i, v in enumerate(sorted(a))}; rb = {v: i for i, v in enumerate(sorted(b))}
        x = [ra[v] for v in a]; y = [rb[v] for v in b]; mx, my = statistics.mean(x), statistics.mean(y)
        return sum((p - mx) * (q - my) for p, q in zip(x, y)) / (sum((p - mx) ** 2 for p in x) * sum((q - my) ** 2 for q in y)) ** .5
    g = [o['gain_ins'] for o in out]
    for name, v in (('share of indexes removed', [o['idx_removed'] for o in out]),
                    ('probe ratio', [o['probes'][0] / o['probes'][1] for o in out]),
                    ('scan ratio', [o['scan_per_1M'][0] / max(o['scan_per_1M'][1], 1) for o in out])):
        print(f'Spearman rank correlation with the insert gain, {name}: {spearman(v, g):.2f}')
