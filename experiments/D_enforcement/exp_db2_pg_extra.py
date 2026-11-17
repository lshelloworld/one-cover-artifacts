import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment D extras (PostgreSQL 16).
(a) naive enforcement: no indexes, one BEFORE INSERT OR UPDATE trigger per key whose
    body is one EXISTS over the whole table with the pair condition of the key class;
    combined class, |Sigma| in {10,40,120}, trial-0 key sets of db2_log.jsonl.
(b) large table: the filtered-index scheme with 100,000 inserts and 20,000 updates,
    combined class, |Sigma| in {10,20}, trial-0 key sets, values uniform in [0,10000).
Each run: input vs cover, one transaction with a savepoint per statement.
"""
import sys, json, time, random
sys.path.insert(0, 'experiments/lib')
import psycopg2
from exp_db2_pg import *          # DSN, N, K, cols, cname, index_ddl, trigger_ddl, table_ddl, guarded, REJECT, parse_key, check_sql

OUTF = _os.environ.get('ONECOVER_XL_OUT', 'results/D_enforcement/db2_pg_extra.jsonl')
orig = [json.loads(l) for l in open('results/D_enforcement/db2_log.jsonl')]
KEYSET = int(_os.environ.get('ONECOVER_KEYSET', 0))   # 0 = the key sets of the paper; k > 0 = a fresh draw per size
def keyset(m, t=0):
    o = None if KEYSET else next((r for r in orig if r['fragment'] == 'ALL' and r['m'] == m and r['trial'] == t), None)
    if o is None:   # |Sigma| not in db2_log.jsonl: draw as random_keys_capped does, seeded by m
        from keys import mincover_general
        rng = random.Random(1000 + m + 1000 * KEYSET); NN = (1 << K) - 1; S = set()
        while len(S) < m:
            size = min(MAXSIZE, 2 + sum(rng.random() < 0.3 for _ in range(N - 2)))
            S.add((rng.choice(FRAGMENTS['ALL']), sum(1 << c for c in rng.sample(range(N), size))))
        S = sorted(S); return S, mincover_general(S, NN), NN
    return [parse_key(s) for s in o['input']], [parse_key(s) for s in o['output']], (1 << K) - 1

def pair_cond(cls, K_):
    cs = cols(K_)
    if cls == 'possible': return ' AND '.join(f'{c}=NEW.{c}' for c in cs)                       # non-null equality
    if cls == 'domain':   return ' AND '.join(f'{c} IS NOT DISTINCT FROM NEW.{c}' for c in cs)
    if cls == 'certain':  return ' AND '.join(f'({c} IS NULL OR NEW.{c} IS NULL OR {c}=NEW.{c})' for c in cs)
    # partial: NEW subsumed by existing or existing subsumed by NEW
    a = ' AND '.join(f'(NEW.{c} IS NULL OR NEW.{c}={c})' for c in cs)
    b = ' AND '.join(f'({c} IS NULL OR {c}=NEW.{c})' for c in cs)
    return f'(({a}) OR ({b}))'

def make_naive(cur, keys, NN):
    cur.execute('DROP TABLE IF EXISTS T CASCADE'); cur.execute(table_ddl(NN))
    for i, (cls, K_) in enumerate(keys):
        cur.execute(f"""CREATE OR REPLACE FUNCTION chk_n{i}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  IF EXISTS (SELECT 1 FROM T WHERE {pair_cond(cls, K_)} AND (TG_OP='INSERT' OR ctid <> OLD.ctid)) THEN
    RAISE EXCEPTION '{cls} key violated'; END IF; RETURN NEW; END $$""")
        cur.execute(f'CREATE TRIGGER trg_n{i} BEFORE INSERT OR UPDATE ON T FOR EACH ROW EXECUTE FUNCTION chk_n{i}()')
    return len(keys)

def make_indexed(cur, keys, NN):
    cur.execute('DROP TABLE IF EXISTS T CASCADE'); cur.execute(table_ddl(NN)); n = 0
    for i, (cls, K_) in enumerate(keys):
        for s in index_ddl(i, cls, K_, NN): cur.execute(s); n += 1
        if cls in ('partial', 'certain'):
            for s in trigger_ddl(i, cls, K_, NN)[0]: cur.execute(s)
    return n

def guarded_ac(cur, sql, params):
    try:
        cur.execute(sql, params); return True
    except REJECT:
        return False

def run(con, keys, NN, rows, ups, scheme, rid_index=False):
    cur = con.cursor(); t0 = time.perf_counter()
    g = guarded_ac if con.autocommit else guarded
    nobj = (make_naive if scheme == 'naive' else make_indexed)(cur, keys, NN)
    if rid_index:   # xl: without it every update scans the table for its rid (same cost for input and cover)
        cur.execute('CREATE INDEX t_rid ON T(rid)')
    t_ddl = time.perf_counter() - t0
    ins = 'INSERT INTO T(' + ','.join(cname(i) for i in range(N)) + ') VALUES(' + ','.join(['%s'] * N) + ')'
    acc = 0; t0 = time.perf_counter()
    for r in rows:
        if g(cur, ins, r): acc += 1
    t_ins = time.perf_counter() - t0
    cur.execute('SELECT rid FROM T ORDER BY rid'); ids = [x[0] for x in cur.fetchall()]
    t0 = time.perf_counter(); ok = 0
    for (j, c, v) in ups:
        if g(cur, f'UPDATE T SET {cname(c)}=%s WHERE rid=%s', (v, ids[j % len(ids)])): ok += 1
    t_upd = time.perf_counter() - t0
    cur.execute('SELECT ' + ','.join(cname(i) for i in range(N)) + ' FROM T')
    state = sorted(cur.fetchall(), key=lambda x: tuple(-1 if v is None else v for v in x))
    t0 = time.perf_counter()
    if not con.autocommit:   # the self-join check is quadratic; skipped for the 100k-row run
        for cls, K_ in keys:
            cur.execute(check_sql(cls, K_)); assert cur.fetchone() is None
    t_chk = time.perf_counter() - t0
    if not con.autocommit: con.commit()
    return dict(objects=nobj, accepted=acc, updated=ok, t_ddl=t_ddl, t_insert=t_ins, t_update=t_upd, t_check=t_chk), state

def workload(rng, ROWS, UPDATES, V, NULL_ROW=0.3, NULLP=0.05):
    rows = []
    for _ in range(ROWS):
        r = [rng.randrange(V) for _ in range(N)]
        if rng.random() < NULL_ROW: r[rng.randrange(K, N)] = None
        rows.append(tuple(r))
    ups = [(rng.randrange(ROWS), rng.randrange(K, N), (None if rng.random() < NULLP else rng.randrange(V))) for _ in range(UPDATES)]
    return rows, ups

if __name__ == '__main__':
    which = sys.argv[1]
    con = psycopg2.connect(**DSN); con.autocommit = False
    out = open(OUTF, 'a')
    import os
    done = {(json.loads(l)['exp'], json.loads(l)['m']) for l in open(OUTF)} if os.path.exists(OUTF) else set()
    if which == 'naive':
        for m in [10, 40, 120]:
            if ('naive', m) in done: continue
            S, G, NN = keyset(m); rows, ups = workload(random.Random(7), 1500, 600, 200)
            rS, stS = run(con, S, NN, rows, ups, 'naive'); rG, stG = run(con, G, NN, rows, ups, 'naive')
            assert stS == stG
            rec = dict(exp='naive', m=m, in_keys=len(S), out_keys=len(G), sigma=rS, cover=rG); out.write(json.dumps(rec) + '\n'); out.flush()
            print('naive', m, 'ins %.1f/%.1f upd %.1f/%.1f chk %.2f/%.2f acc %d' % (rS['t_insert'], rG['t_insert'], rS['t_update'], rG['t_update'], rS['t_check'], rG['t_check'], rS['accepted']), flush=True)
    else:
        # large: 100k inserts, 20k updates; xl: 1M inserts, 200k updates, values in [0,32000), index on rid
        # (V grows with sqrt(rows), keeping the per-key collision rate of the 100k run)
        ms, ROWS_, UPD_, V_ = ([10, 20], 100000, 20000, 10000) if which == 'large' else ([10, 20, 30, 40, 50], 1000000, 200000, 32000)
        if len(sys.argv) > 2: ms = [int(x) for x in sys.argv[2].split(',')]   # optional subset of the sizes
        con.autocommit = True; con.cursor().execute('SET synchronous_commit = off')
        for m in ms:
            if (which, m) in done: continue
            S, G, NN = keyset(m); rows, ups = workload(random.Random(11), ROWS_, UPD_, V_)
            ri = which == 'xl'
            rS, stS = run(con, S, NN, rows, ups, 'indexed', ri); rG, stG = run(con, G, NN, rows, ups, 'indexed', ri)
            assert stS == stG
            rec = dict(exp=which, m=m, keyset=KEYSET, rid_index=ri, in_keys=len(S), out_keys=len(G), sigma=rS, cover=rG); out.write(json.dumps(rec) + '\n'); out.flush()
            print(which, m, 'keys %d/%d' % (len(S), len(G)), 'idx %d/%d ins %.1f/%.1f upd %.1f/%.1f chk %.2f/%.2f acc %d' % (rS['objects'], rG['objects'], rS['t_insert'], rG['t_insert'], rS['t_update'], rG['t_update'], rS['t_check'], rG['t_check'], rS['accepted']), flush=True)
    print('done')
