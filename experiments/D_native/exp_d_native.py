import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT, _os.path.join(_ROOT, 'experiments', 'D_enforcement'), _os.path.dirname(_os.path.abspath(__file__))]
"""M2: Experiment D (75 configurations, 1,500 inserts, 600 updates) with native enforcement.

Schemes, each on the input Sigma and on its cover Gamma:
  today   exp_db2_pg.py's scheme: UNIQUE (possible), UNIQUE NULLS NOT DISTINCT (domain), filtered unique
          indexes per null pattern + one PL/pgSQL trigger per key (partial, certain)
  native  the same for possible and domain keys; one nbtnull index per partial or certain key (mode
          subsumed or compatible), shadow depth 0 if the key has a NOT NULL column, else 1 (the M1 rule;
          rows here carry at most one null from the inserts). A partial or certain key without nullable
          columns is a possible key and gets a plain UNIQUE index.
Key sets and workloads are regenerated from exp_db2_pg.py's seeded RNG and checked against db2_log.jsonl.
Per configuration and repetition the four runs are interleaved, in alternating order; all four must
accept the same statements and end in the same table. Runs against the database of config.py (ONECOVER_DB_*), which must have the extension loaded
(README.md). Output: results/D_native/m2_expD.jsonl (one line per configuration and repetition).
Usage: exp_d_native.py [reps] [frag:m ...]"""
import os, sys, json, time
import exp_db2_pg as M          # the artifact root is the working directory

REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 2
SMOKE = [x for x in sys.argv[2:]]          # e.g. ALL:120 : run only these (fragment, m) configurations, trial 0
os.makedirs('results/D_native', exist_ok=True)
OUT = os.path.join('results', 'D_native', 'm2_smoke.jsonl' if SMOKE else 'm2_expD.jsonl')

def native_make_db(cur, keys, NNmask):
    cur.execute('DROP TABLE IF EXISTS T CASCADE'); cur.execute(M.table_ddl(NNmask))
    nidx = 0
    for i, (cls, mask) in enumerate(keys):
        X = M.cols(mask & NNmask); NK = M.cols(mask & ~NNmask)
        if cls in ('possible', 'domain') or not NK:
            c = 'possible' if cls in ('partial', 'certain') else cls
            for s in M.index_ddl(i, c, mask, NNmask): cur.execute(s)
        else:
            cur.execute('SELECT nbtnull_key_ddl(%s, %s, %s, %s, %s, %s)',
                        (f'k{i}', 't', X or None, NK, 'subsumed' if cls == 'partial' else 'compatible', 0 if X else 1))
            cur.execute(cur.fetchone()[0])
        nidx += 1
    return nidx, 0

today_make_db = M.make_db
def run(con, scheme, keys, NN, rows, ups):
    M.make_db = native_make_db if scheme == 'native' else today_make_db
    try: return M.run_db(con, keys, NN, rows, ups)
    finally: M.make_db = today_make_db

if __name__ == '__main__':
    import psycopg2
    orig = [json.loads(l) for l in open(M.ORIG_LOG)]
    jobs = []; idx = 0
    for frag in ['F1', 'F2', 'ALL']:
        for m in [10, 20, 40, 80, 120]:
            for t in range(M.TRIALS):
                NN, S = M.random_keys_capped(M.N, M.K, m, frag); o = orig[idx]; idx += 1
                assert [f'{c}({M.fmt_mask(mk, M.N)})' for c, mk in S] == o['input'], 'RNG drift'
                rows, ups = M.workload()
                jobs.append((frag, m, t, NN, S, [M.parse_key(s) for s in o['output']], rows, ups))
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT): r = json.loads(l); done.add((r['fragment'], r['m'], r['trial'], r['rep']))
    con = psycopg2.connect(**M.DSN); con.autocommit = False
    order = [('today', 'S'), ('today', 'G'), ('native', 'S'), ('native', 'G')]
    out = open(OUT, 'a')
    for rep in range(REPS):
        for frag, m, t, NN, S, G, rows, ups in jobs:
            if (frag, m, t, rep) in done: continue
            if SMOKE and (f'{frag}:{m}' not in SMOKE or t): continue
            res = {}; states = {}
            for scheme, side in (order if (rep + t) % 2 == 0 else order[::-1]):
                r, st = run(con, scheme, S if side == 'S' else G, NN, rows, ups)
                res[f'{scheme}_{side}'] = r; states[f'{scheme}_{side}'] = st
            ref = states['today_S']
            assert all(v == ref for v in states.values()), (frag, m, t, 'schemes accepted different data')
            assert len({(v['accepted'], v['updated']) for v in res.values()}) == 1
            rec = dict(fragment=frag, m=m, trial=t, rep=rep, in_keys=len(S), out_keys=len(G), runs=res, load=os.getloadavg())
            out.write(json.dumps(rec) + '\n'); out.flush()
            f = lambda k: res[k]['t_insert'] + res[k]['t_update']
            print(f"{frag:3} m={m:3} t={t} rep {rep}: today {f('today_S'):6.2f}/{f('today_G'):6.2f}  native {f('native_S'):6.2f}/{f('native_G'):6.2f} s"
                  f"  idx {res['today_S']['indexes']}/{res['today_G']['indexes']} -> {res['native_S']['indexes']}/{res['native_G']['indexes']}"
                  f"  load {rec['load'][1]:.1f}", flush=True)
    print('done')
