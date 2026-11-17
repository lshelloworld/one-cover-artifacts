import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib',)]
_os.chdir(_ROOT)
"""Stress test of Algorithm 2: the certain key on all n columns (all nullable) against
random 3-uniform hypergraphs of partial keys, with m = c*n edges for c around the 2-colourability threshold
of random 3-uniform hypergraphs (about 2.4n edges), plus the complete 3-uniform hypergraph. Reports, per (n, c),
the share of implied targets, the median and maximum time of implies(), and the median and maximum number of
search nodes (calls of the inner colouring procedure). Writes results/A-C_random_covers/alg2_stress.jsonl."""
import sys, json, random, time, itertools, statistics
from keys import implies

def nodes_of(f, *a):
    cnt = [0]
    def prof(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == 'colourable': cnt[0] += 1
    sys.setprofile(prof)
    try: r = f(*a)
    finally: sys.setprofile(None)
    return r, cnt[0]

OUT = open('results/A-C_random_covers/alg2_stress.jsonl', 'w')
rng = random.Random(7)
TRIALS = 20
for n in (8, 12, 16, 20, 24):
    triples = [sum(1 << i for i in c) for c in itertools.combinations(range(n), 3)]
    for c in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 'complete'):
        res = []
        for t in range(TRIALS if c != 'complete' else 1):
            E = triples if c == 'complete' else rng.sample(triples, min(len(triples), int(c * n)))
            S = [('partial', e) for e in E]; phi = ('certain', (1 << n) - 1)
            t0 = time.perf_counter(); imp = implies(S, phi, 0); dt = time.perf_counter() - t0
            _, nd = nodes_of(implies, S, phi, 0)
            res.append((imp, dt, nd))
        rec = dict(n=n, c=c, edges=len(E), trials=len(res), implied=sum(r[0] for r in res),
                   ms_median=statistics.median(r[1] for r in res) * 1000, ms_max=max(r[1] for r in res) * 1000,
                   nodes_median=statistics.median(r[2] for r in res), nodes_max=max(r[2] for r in res))
        OUT.write(json.dumps(rec) + '\n'); OUT.flush()
        print(f"n={n:2d} c={c!s:8s} edges {rec['edges']:5d} implied {rec['implied']:2d}/{rec['trials']:2d} "
              f"ms {rec['ms_median']:8.2f} / {rec['ms_max']:8.2f}  nodes {rec['nodes_median']:7.0f} / {rec['nodes_max']:7d}", flush=True)
print('done')
