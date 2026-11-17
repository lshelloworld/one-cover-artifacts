import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment D (PostgreSQL): where the integrity check's time goes. For the trial-0 key sets
at |Sigma| = 120 of each fragment, run the workload of exp_db2_pg.py on the input and on its
cover, then EXPLAIN ANALYZE every key's self-join check and sum planning and execution time."""
import json
import psycopg2
import exp_db2_pg as D

OUT = 'results/D_enforcement/check_plan_pg.json'
M = 120

def jobs():
    """The (fragment, input, cover, rows, updates) of trial 0 at |Sigma| = M, regenerated
    in the order of exp_db2_pg.py's main loop so that the seeded RNG gives the same data."""
    orig = [json.loads(l) for l in open(D.ORIG_LOG)]; idx = 0
    for frag in ['F1', 'F2', 'ALL']:
        for m in [10, 20, 40, 80, 120]:
            for t in range(D.TRIALS):
                NN, S = D.random_keys_capped(D.N, D.K, m, frag); o = orig[idx]; idx += 1
                assert [f'{c}({D.fmt_mask(mk, D.N)})' for c, mk in S] == o['input'], 'RNG drift'
                rows, ups = D.workload()
                if m == M and t == 0: yield frag, NN, S, [D.parse_key(s) for s in o['output']], rows, ups

def checks(con, keys, NN, rows, ups):
    cur = con.cursor(); nidx, _ = D.make_db(cur, keys, NN)
    ins = 'INSERT INTO T(' + ','.join(D.cname(i) for i in range(D.N)) + ') VALUES(' + ','.join(['%s'] * D.N) + ')'
    for r in rows: D.guarded(cur, ins, r)
    cur.execute('SELECT rid FROM T ORDER BY rid'); ids = [x[0] for x in cur.fetchall()]
    for (j, c, v) in ups: D.guarded(cur, f'UPDATE T SET {D.cname(c)}=%s WHERE rid=%s', (v, ids[j % len(ids)]))
    plan = execute = 0.0
    for cls, mask in keys:
        cur.execute('EXPLAIN (ANALYZE, FORMAT JSON) ' + D.check_sql(cls, mask)); e = cur.fetchone()[0][0]
        plan += e['Planning Time']; execute += e['Execution Time']
    con.rollback()
    return dict(keys=len(keys), indexes=nidx, plan_ms=plan, exec_ms=execute)

if __name__ == '__main__':
    con = psycopg2.connect(**D.DSN); con.autocommit = False; res = []
    for frag, NN, S, G, rows, ups in jobs():
        r = dict(fragment=frag, m=M, input=checks(con, S, NN, rows, ups), cover=checks(con, G, NN, rows, ups)); res.append(r)
        print(frag, M, ' '.join(f"{side}: {r[side]['indexes']} idx, plan {r[side]['plan_ms']:.1f} ms, exec {r[side]['exec_ms']:.1f} ms"
                                for side in ('input', 'cover')), flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)
    print('done')
