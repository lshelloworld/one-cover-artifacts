import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment D, robustness runs.

  reps <engine> [R]   the 75 configurations of Experiment D (same key sets and workloads, regenerated
                      from the seeded RNG and checked against db2_log.jsonl), each run R times (default 5),
                      input and cover alternating, so that run-to-run spread can be reported
  wide <engine> [R]   the combined class on wider schemas: n = 16, 24, 32 columns, n/4 NOT NULL,
                      |Sigma| = 40 and 120, 3 random key sets each (seeded), cover by Algorithm 4

<engine> is sqlite (in memory, as exp_db2.py) or pg (as exp_db2_pg.py; set ONECOVER_DB_PORT for the private
cluster). Every record keeps all R timings and the accepted/updated counts, from which the rejection rates
follow. Records are appended to results/D_enforcement/tier2/<mode>_<engine>.jsonl; finished configurations
are skipped on a rerun.
"""
import sys, json, os, random, time, statistics
MODE, ENGINE = sys.argv[1], sys.argv[2]
R = int(sys.argv[3]) if len(sys.argv) > 3 else (5 if MODE == 'reps' else 3)
if ENGINE == 'sqlite':
    import exp_db2 as M
    def run(keys, NN, rows, ups): return M.run_db(keys, NN, rows, ups)
else:
    import exp_db2_pg as M, psycopg2
    WDB = 'keys_tier2'
    adm = psycopg2.connect(**M.DSN); adm.autocommit = True
    adm.cursor().execute(f'DROP DATABASE IF EXISTS {WDB}'); adm.cursor().execute(f'CREATE DATABASE {WDB}'); adm.close()
    CON = psycopg2.connect(**dict(M.DSN, dbname=WDB)); CON.autocommit = False
    def run(keys, NN, rows, ups): return M.run_db(CON, keys, NN, rows, ups)
from keys import mincover_general, occ, fmt_mask

OUTD = os.environ.get('ONECOVER_TIER2_OUT', 'results/D_enforcement/tier2'); os.makedirs(OUTD, exist_ok=True)
OUTF = f'{OUTD}/{MODE}_{ENGINE}.jsonl'
done = set()
if os.path.exists(OUTF):
    for l in open(OUTF): r = json.loads(l); done.add((r['n'], r['fragment'], r['m'], r['trial']))
LOG = open(OUTF, 'a')

def measure(n, frag, m, t, NN, S, G, rows, ups, extra):
    if (n, frag, m, t) in done: return
    reps = {'sigma': [], 'cover': []}; states = {}
    for i in range(R):
        for side, keys in (('sigma', S), ('cover', G)) if i % 2 == 0 else (('cover', G), ('sigma', S)):
            res, st = run(keys, NN, rows, ups); reps[side].append(res)
            if side in states: assert states[side] == st, 'nondeterministic run'
            states[side] = st
    assert states['sigma'] == states['cover'], 'cover and input accepted different data!'
    summ = {}
    for side in reps:
        rs = reps[side]
        summ[side] = dict(accepted=rs[0]['accepted'], updated=rs[0]['updated'], indexes=rs[0]['indexes'], triggers=rs[0]['triggers'],
                          **{k: [r[k] for r in rs] for k in ('t_insert', 't_update', 't_check')})
    rec = dict(n=n, k=bin(NN).count('1'), fragment=frag, m=m, trial=t, reps=R, rows=len(rows), updates=len(ups),
               in_keys=len(S), out_keys=len(G), in_occ=occ(S), out_occ=occ(G), sigma=summ['sigma'], cover=summ['cover'],
               finished=time.strftime('%F %T'), **extra)
    LOG.write(json.dumps(rec) + '\n'); LOG.flush(); os.fsync(LOG.fileno())
    med = lambda side, k: statistics.median(rec[side][k])
    print(n, frag, m, t, f"{len(S)}->{len(G)} idx {rec['sigma']['indexes']}/{rec['cover']['indexes']}",
          'ins %.2f/%.2f upd %.2f/%.2f chk %.2f/%.2f' % tuple(med(s, k) for k in ('t_insert', 't_update', 't_check') for s in ('sigma', 'cover')),
          f"acc {rec['sigma']['accepted']}/{len(rows)} upd {rec['sigma']['updated']}/{len(ups)}", flush=True)

if MODE == 'reps':
    orig = [json.loads(l) for l in open('results/D_enforcement/db2_log.jsonl')]; idx = 0
    for frag in ['F1', 'F2', 'ALL']:
        for m in [10, 20, 40, 80, 120]:
            for t in range(M.TRIALS):
                NN, S = M.random_keys_capped(M.N, M.K, m, frag); o = orig[idx]; idx += 1
                assert [f'{c}({fmt_mask(mk, M.N)})' for c, mk in S] == o['input'], 'RNG drift'
                G = [M.parse_key(s) for s in o['output']] if hasattr(M, 'parse_key') else M.cover(frag, S, NN)
                rows, ups = M.workload()
                measure(M.N, frag, m, t, NN, S, G, rows, ups, {})
else:
    for n in (16, 24, 32):
        M.N, M.K = n, n // 4; M.rng = random.Random(1000 + n)
        for m in (40, 120):
            for t in range(3):
                NN, S = M.random_keys_capped(n, n // 4, m, 'ALL'); G = mincover_general(S, NN)
                rows, ups = M.workload()
                measure(n, 'ALL', m, t, NN, S, G, rows, ups,
                        dict(input=[f'{c}({fmt_mask(mk, n)})' for c, mk in S], output=[f'{c}({fmt_mask(mk, n)})' for c, mk in G]))
LOG.close(); print('done')
