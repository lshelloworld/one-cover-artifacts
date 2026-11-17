import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Why does MySQL gain so little from the cover? Diagnostic on one size (default key set 2, |Sigma|=40).

For input and cover, the first ROWS inserts of the million-row workload are run under four configurations:
  full      the perkey scheme of exp_db2_mysql.py (one index per key, triggers for partial/certain keys)
  indexes   the key indexes only, no triggers                (index maintenance)
  triggers  the triggers only, no key indexes                (the probes, which must then scan; first 5,000 rows only)
  none      no keys                                          (the bare insert)
Times per batch of 5,000 inserts show what grows with the table. For 'full', performance_schema gives the
time spent in each trigger and the rows read through each index, and EXPLAIN shows the access type of every
trigger probe at the end, with the values of sample rows. Writes results/D_enforcement/mysql_diag.json.
Usage: exp_mysql_diag.py [keyset] [m] [rows]"""
import sys, os, json, time, random, re, collections
KS = int(sys.argv[1]) if len(sys.argv) > 1 else 2
M_ = int(sys.argv[2]) if len(sys.argv) > 2 else 40
ROWS = int(sys.argv[3]) if len(sys.argv) > 3 else 100000
os.environ['ONECOVER_KEYSET'] = str(KS)
import mysql.connector
import exp_db2_mysql as X
from exp_db2_pg_extra import keyset, workload
from exp_db2_pg import N, K, cname, cols, subsets, pattern_where
BATCH = 5000
ROWS_TRIG = min(ROWS, 5000)   # without key indexes every probe scans the table, so this configuration gets fewer rows

def build(cur, keys, NN, what):
    cur.execute('DROP TABLE IF EXISTS T'); cur.execute(X.table_ddl(NN)); n = t = 0
    for i, (cls, K_) in enumerate(keys):
        if what in ('full', 'indexes'):
            for s in X.index_ddl(i, cls, K_, NN, 'perkey'): cur.execute(s); n += 1
        if what in ('full', 'triggers') and cls in ('partial', 'certain'):
            for s in X.trigger_ddl(i, cls, K_, NN, 'perkey'): cur.execute(s); t += 1
    return n, t

def probes(keys, NN, row):
    """The INSERT trigger's probe queries that fire for `row`, with NEW.c replaced by the row's values."""
    out = []
    for i, (cls, K_) in enumerate(keys):
        if cls not in ('partial', 'certain'): continue
        Xc = cols(K_ & NN); NK = cols(K_ & ~NN)
        P = [c for c in NK if row[int(c[1:])] is None]
        for P2 in subsets(NK):
            if cls == 'partial' and not (set(P) <= set(P2) or set(P2) <= set(P)): continue
            eq = Xc + [c for c in NK if c not in P and c not in P2]
            cond = [pattern_where(P2, NK)] + [f'{c} = {row[int(c[1:])]}' for c in eq]
            out.append((i, cls, len(NK), len(P), len(P2), 'SELECT 1 FROM T WHERE ' + ' AND '.join(cond)))
    return out

def run(con, keys, NN, rows, what, side):
    cur = con.cursor(); n, t = build(cur, keys, NN, what)
    if what == 'full':
        for tb in ('events_statements_summary_by_program', 'table_io_waits_summary_by_index_usage'):
            cur.execute(f'TRUNCATE TABLE performance_schema.{tb}')
    ins = 'INSERT INTO T(' + ','.join(cname(i) for i in range(N)) + ') VALUES(' + ','.join(['%s'] * N) + ')'
    acc = 0; batches = []; t0 = tb = time.perf_counter()
    for j, r in enumerate(rows, 1):
        if X.guarded(cur, ins, r): acc += 1
        if j % BATCH == 0: now = time.perf_counter(); batches.append(round(now - tb, 3)); tb = now
    rec = dict(side=side, config=what, indexes=n, triggers=t, accepted=acc, t_insert=time.perf_counter() - t0, batches=batches)
    if what == 'full':
        cur.execute("SELECT OBJECT_NAME, COUNT_STAR, SUM_TIMER_WAIT/1e12 FROM performance_schema.events_statements_summary_by_program "
                    "WHERE OBJECT_TYPE='TRIGGER' AND OBJECT_SCHEMA=DATABASE()")
        rec['trigger_seconds'] = {name: [cnt, float(sec)] for name, cnt, sec in cur.fetchall()}
        cur.execute("SELECT INDEX_NAME, COUNT_FETCH, COUNT_INSERT, SUM_TIMER_WAIT/1e12 FROM performance_schema.table_io_waits_summary_by_index_usage "
                    "WHERE OBJECT_SCHEMA=DATABASE() AND OBJECT_NAME='T'")
        rec['index_io'] = {str(name): [int(f), int(i), float(s)] for name, f, i, s in cur.fetchall()}
        # EXPLAIN every probe for 200 sample rows (half with a null, half without)
        rnd = random.Random(5); sample = [r for r in rows[:ROWS] if None in r][:100] + [r for r in rows[:ROWS] if None not in r][:100]
        acc_types = collections.Counter(); rows_est = collections.defaultdict(list)
        for r in sample:
            for (i, cls, nk, p, p2, q) in probes(keys, NN, r):
                cur.execute('EXPLAIN FORMAT=TRADITIONAL ' + q); e = dict(zip([d[0] for d in cur.description], cur.fetchone()))
                tag = f"{cls}: new nulls {p}, probed pattern nulls {p2}"; acc_types[(e['type'], e['key'] is not None)] += 1
                rows_est[e['type']].append(int(e['rows'] or 0))
        rec['explain'] = {f'{ty} {"with key" if k else "no key"}': c for (ty, k), c in acc_types.items()}
        rec['explain_rows_median'] = {ty: sorted(v)[len(v) // 2] for ty, v in rows_est.items()}
        rec['explain_rows_max'] = {ty: max(v) for ty, v in rows_est.items()}
    cur.execute('DROP TABLE T'); return rec

if __name__ == '__main__':
    S, G, NN = keyset(M_); rows, _ = workload(random.Random(11), 1000000, 200000, 32000); rows = rows[:ROWS]
    DB = os.environ.get('ONECOVER_MYSQL_DB', 'onecover_diag'); OUTJ = os.environ.get('ONECOVER_DIAG_OUT', 'results/D_enforcement/mysql_diag.json')
    c0 = mysql.connector.connect(**X.MYSQL); c0.autocommit = True; c0.cursor().execute(f'CREATE DATABASE IF NOT EXISTS {DB}'); c0.close()
    con = mysql.connector.connect(**dict(X.MYSQL, database=DB)); con.autocommit = True; cur = con.cursor()
    cur.execute('SELECT @@GLOBAL.innodb_flush_log_at_trx_commit'); f0 = cur.fetchone()[0]
    cur.execute('SET GLOBAL innodb_flush_log_at_trx_commit = 2')
    cur.execute("UPDATE performance_schema.setup_instruments SET ENABLED='YES', TIMED='YES' WHERE NAME LIKE 'statement/%' OR NAME LIKE 'wait/io/table/%'")
    cur.execute("UPDATE performance_schema.setup_consumers SET ENABLED='YES' WHERE NAME LIKE 'events_statements%' OR NAME = 'global_instrumentation' OR NAME = 'thread_instrumentation' OR NAME = 'statements_digest'")
    out = dict(keyset=KS, m=M_, rows=ROWS, in_keys=len(S), out_keys=len(G), runs=[])
    try:
        for what in ('none', 'indexes', 'triggers', 'full'):
            for side, keys in (('sigma', S), ('cover', G)):
                rec = run(con, keys, NN, rows[:ROWS_TRIG] if what == 'triggers' else rows, what, side); out['runs'].append(rec)
                json.dump(out, open(OUTJ, 'w'), indent=1)
                print(what, side, f"idx {rec['indexes']} trg {rec['triggers']} acc {rec['accepted']} ins {rec['t_insert']:.1f}s",
                      'first/last batch', rec['batches'][:1], rec['batches'][-1:], rec.get('explain', ''), flush=True)
    finally:
        cur.execute(f'SET GLOBAL innodb_flush_log_at_trx_commit = {f0}')
    print('done')
