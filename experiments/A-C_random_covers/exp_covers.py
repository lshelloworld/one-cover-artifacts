import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
import sys, json, time, random, statistics
sys.path.insert(0, 'experiments/lib')
from keys import *
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = 'results/A-C_random_covers'
import os; os.makedirs(OUT, exist_ok=True)
LOG = open(f'{OUT}/covers_log.jsonl', 'w')
TRIALS = 10
rng = random.Random(2026)

def cover(frag, S, NN):
    if frag == 'F1': return mincover_fragment(S, NN, 'partial')
    if frag == 'F2': return mincover_fragment(S, NN, 'certain')
    return mincover_general(S, NN)

def run(frag, n, k, m, exp):
    rows = []
    for t in range(TRIALS):
        NN, S = random_keys(n, k, m, frag, rng)
        t0 = time.perf_counter(); G = cover(frag, S, NN); dt = time.perf_counter() - t0
        rec = dict(exp=exp, fragment=frag, n=n, k=k, trial=t, in_keys=len(S), in_occ=occ(S),
                   out_keys=len(G), out_occ=occ(G), time=dt,
                   NN=fmt_mask(NN, n),
                   input=[f'{c}({fmt_mask(mk, n)})' for c, mk in sorted(S, key=lambda x: (popcount(x[1]), x[0]))],
                   output=[f'{c}({fmt_mask(mk, n)})' for c, mk in sorted(G, key=lambda x: (popcount(x[1]), x[0]))])
        LOG.write(json.dumps(rec) + '\n'); rows.append(rec)
    return rows

results = {'A': [], 'B': [], 'C': []}
import sys
DO = sys.argv[1:] or ['A','B']
# Experiment A: growing |Sigma| at n=12, k=4
for frag in (['F1', 'F2', 'ALL'] if 'A' in DO else []):
    for m in [25, 50, 100, 200, 400, 800, 1600, 3200]:
        rs = run(frag, 12, 4, m, 'A'); results['A'] += rs
        print('A', frag, m, round(statistics.mean(r['out_keys'] for r in rs), 1), round(statistics.mean(r['time'] for r in rs) * 1000, 1), 'ms', flush=True)
# Experiment B: growing n at |Sigma|=200, k = n//3
for frag in (['F1', 'F2', 'ALL'] if 'B' in DO else []):
    for n in [8, 10, 12, 16, 20, 24, 28, 32]:
        rs = run(frag, n, n // 3, 200, 'B'); results['B'] += rs
        print('B', frag, n, round(statistics.mean(r['out_keys'] for r in rs), 1), round(statistics.mean(r['time'] for r in rs) * 1000, 1), 'ms', flush=True)
# Experiment C: combined class, binary partial keys vs. certain keys (n=16, no NOT NULL)
def run_c(p, exp='C'):
    rows = []
    for t in range(TRIALS):
        n = 16; NN = 0
        S = set()
        while len(S) < p:
            a, b = rng.sample(range(n), 2); S.add(('partial', (1 << a) | (1 << b)))
        while len(S) < p + 50:
            size = rng.randint(4, 8); cols = rng.sample(range(n), size)
            S.add(('certain', sum(1 << c for c in cols)))
        S = list(S)
        t0 = time.perf_counter(); G = mincover_general(S, NN); dt = time.perf_counter() - t0
        rec = dict(exp=exp, fragment='ALL', n=n, k=0, trial=t, in_keys=len(S), in_occ=occ(S), p=p,
                   out_keys=len(G), out_occ=occ(G), time=dt, NN='',
                   certain_kept=sum(1 for c, _ in G if c == 'certain'),
                   input=[f'{c}({fmt_mask(mk, n)})' for c, mk in sorted(S, key=lambda x: (popcount(x[1]), x[0]))],
                   output=[f'{c}({fmt_mask(mk, n)})' for c, mk in sorted(G, key=lambda x: (popcount(x[1]), x[0]))])
        LOG.write(json.dumps(rec) + '\n'); rows.append(rec)
    return rows
results['C'] = []
for p in ([0, 10, 20, 30, 40, 60, 80, 120] if 'C' in DO else []):
    rs = run_c(p); results['C'] += rs
    print('C', p, 'certain kept', round(statistics.mean(r['certain_kept'] for r in rs), 1), round(statistics.mean(r['time'] for r in rs) * 1000, 1), 'ms', flush=True)
LOG.close()
json.dump(results, open(f'{OUT}/covers_results.json', 'w'))

def agg(rows, key, xkey):
    xs = sorted(set(r[xkey] for r in rows))
    return xs, [statistics.mean(r[key] for r in rows if r[xkey] == x) for x in xs]

COL = {'F1': 'tab:blue', 'F2': 'tab:orange', 'ALL': 'tab:green'}
LBL = {'F1': r'$\mathcal{F}_1$', 'F2': r'$\mathcal{F}_2$', 'ALL': 'combined class'}
if not results['A']: results['A'] = None
fig, ax = plt.subplots(1, 3, figsize=(13, 3.6))
for frag in (COL if results['A'] else []):
    rows = [r for r in results['A'] if r['fragment'] == frag]
    xs, ys = agg(rows, 'out_keys', 'in_keys'); ax[0].plot(xs, ys, 'o-', color=COL[frag], label=LBL[frag])
    xs, ys = agg(rows, 'out_occ', 'in_keys'); xs2, ys2 = agg(rows, 'in_occ', 'in_keys')
    ax[1].plot(xs, [a / b for a, b in zip(ys, ys2)], 'o-', color=COL[frag], label=LBL[frag])
    xs, ys = agg(rows, 'time', 'in_keys'); ax[2].plot(xs, [y * 1000 for y in ys], 'o-', color=COL[frag], label=LBL[frag])
ax[0].set_xlabel(r'$|\Sigma|$'); ax[0].set_ylabel('keys in cover'); ax[0].set_xscale('log')
ax[1].set_xlabel(r'$|\Sigma|$'); ax[1].set_ylabel('attribute occurrences, cover / input'); ax[1].set_xscale('log')
ax[2].set_xlabel(r'$|\Sigma|$'); ax[2].set_ylabel('time (ms)'); ax[2].set_xscale('log'); ax[2].set_yscale('log')
ax[0].legend(); fig.suptitle('Experiment A: n = 12 columns, 4 NOT NULL, growing input size (mean of 10 trials)')
fig.tight_layout(); fig.savefig(f'{OUT}/expA.pdf'); fig.savefig(f'{OUT}/expA.png', dpi=110)

fig, ax = plt.subplots(1, 3, figsize=(13, 3.6))
for frag in COL:
    rows = [r for r in results['B'] if r['fragment'] == frag]
    xs, ys = agg(rows, 'out_keys', 'n'); ax[0].plot(xs, ys, 'o-', color=COL[frag], label=LBL[frag])
    xs, ys = agg(rows, 'out_occ', 'n'); xs2, ys2 = agg(rows, 'in_occ', 'n')
    ax[1].plot(xs, [a / b for a, b in zip(ys, ys2)], 'o-', color=COL[frag], label=LBL[frag])
    xs, ys = agg(rows, 'time', 'n'); ax[2].plot(xs, [y * 1000 for y in ys], 'o-', color=COL[frag], label=LBL[frag])
ax[0].set_xlabel('n (columns)'); ax[0].set_ylabel('keys in cover')
ax[1].set_xlabel('n (columns)'); ax[1].set_ylabel('attribute occurrences, cover / input')
ax[2].set_xlabel('n (columns)'); ax[2].set_ylabel('time (ms)'); ax[2].set_yscale('log')
ax[0].legend(); fig.suptitle(r'Experiment B: $|\Sigma|$ = 200, NOT NULL = n/3, growing schema (mean of 10 trials)')
fig.tight_layout(); fig.savefig(f'{OUT}/expB.pdf'); fig.savefig(f'{OUT}/expB.png', dpi=110)
if results['C']:
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.6))
    rows = results['C']
    xs, ys = agg(rows, 'certain_kept', 'p'); ax[0].plot(xs, ys, 'o-', color='tab:green')
    ax[0].set_xlabel('binary partial keys in input'); ax[0].set_ylabel('certain keys surviving in cover (of 50)')
    xs, ys = agg(rows, 'time', 'p'); ax[1].plot(xs, [y * 1000 for y in ys], 'o-', color='tab:green')
    ax[1].set_xlabel('binary partial keys in input'); ax[1].set_ylabel('time (ms)')
    fig.suptitle('Experiment C: combined class, n = 16 nullable columns, 50 random certain keys of 4-8 columns')
    fig.tight_layout(); fig.savefig(f'{OUT}/expC.pdf'); fig.savefig(f'{OUT}/expC.png', dpi=110)
print('done')
