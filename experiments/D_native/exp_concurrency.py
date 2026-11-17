import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'D_native')]
_os.chdir(_ROOT)
"""Concurrent inserts: input against cover, emulation against native index, with C client sessions.

The rows of Experiment D's workload (values in [0, V), a null in one random nullable column with
probability 0.3) are split round-robin over C sessions, each inserting its share one row per transaction
(synchronous_commit off). Schemes:
  native     the native index (UNIQUE / NULLS NOT DISTINCT for possible and domain keys), READ COMMITTED
  emul_lock  the emulation (filtered unique indexes + triggers), each insert after
             LOCK TABLE ... IN SHARE ROW EXCLUSIVE MODE, READ COMMITTED: correct, inserts serialised
  emul_ser   the emulation under SERIALIZABLE, a transaction retried on serialization failure (at most
             50 times per row): correct
  emul_rc    the emulation under READ COMMITTED without a lock: not correct under concurrency; measured
             to count the violations it lets through
After each run the final table is checked against the input keys: it is reloaded into a table enforced by
the native index, one row at a time, and every rejected row counts as a violation.
Usage: exp_concurrency.py --keyset 1 --m 40 --rows 100000 --clients 1,4,8 [--schemes ...] [--cap 900]
       [--stop HH:MM] [--out results/D_native/concurrency.jsonl]"""
import argparse, json, os, random, threading, time
import psycopg2, psycopg2.errors

ap = argparse.ArgumentParser()
ap.add_argument('--keyset', type=int, default=1); ap.add_argument('--m', type=int, default=40)
ap.add_argument('--rows', type=int, default=100000); ap.add_argument('--values', type=int, default=10000)
ap.add_argument('--clients', default='1,4,8'); ap.add_argument('--schemes', default='native,emul_lock,emul_ser,emul_rc')
ap.add_argument('--cap', type=float, default=900); ap.add_argument('--stop', default='')
ap.add_argument('--out', default='results/D_native/concurrency.jsonl')
A = ap.parse_args()
os.environ['ONECOVER_KEYSET'] = str(A.keyset)

import exp_db2_pg_extra as X
emul_build = X.make_indexed
import exp_dxl_native as NV            # patches X.make_indexed; keep both builders and restore
native_build = NV.native_indexed
X.make_indexed = emul_build
DSN = dict(X.DSN, gssencmode='disable')
REJECT = X.REJECT
INS = 'INSERT INTO T(' + ','.join(X.cname(i) for i in range(X.N)) + ') VALUES(' + ','.join(['%s'] * X.N) + ')'

def late():
    if not A.stop: return False
    now = time.strftime('%H:%M'); return A.stop < now < '12:00'

def worker(scheme, rows, deadline, stats, lock):
    con = psycopg2.connect(**DSN)
    if scheme in ('native', 'emul_rc'): con.autocommit = True
    elif scheme == 'emul_ser': con.set_session(isolation_level='SERIALIZABLE')
    cur = con.cursor(); cur.execute('SET synchronous_commit = off')
    if not con.autocommit: con.commit()
    acc = rej = retries = gaveup = done = 0
    for r in rows:
        if time.perf_counter() > deadline: break
        for attempt in range(51):
            try:
                if scheme == 'emul_lock': cur.execute('LOCK TABLE T IN SHARE ROW EXCLUSIVE MODE')
                cur.execute(INS, r)
                if not con.autocommit: con.commit()
                acc += 1; break
            except REJECT:
                if not con.autocommit: con.rollback()
                rej += 1; break
            except (psycopg2.errors.SerializationFailure, psycopg2.errors.DeadlockDetected):
                if not con.autocommit: con.rollback()
                retries += 1
        else:
            gaveup += 1
        done += 1
    con.close()
    with lock:
        for k, v in dict(accepted=acc, rejected=rej, retries=retries, gave_up=gaveup, attempted=done).items(): stats[k] += v

def violations(con, keys, NN, rows):
    """Reload the final rows into a table enforced by the native index; count the rejected rows."""
    cur = con.cursor(); native_build(cur, keys, NN); bad = 0
    for r in rows:
        try: cur.execute(INS, r)
        except REJECT: bad += 1
    return bad

def run(scheme, keys, NN, rows, C):
    con = psycopg2.connect(**DSN); con.autocommit = True; cur = con.cursor()
    nobj = (native_build if scheme == 'native' else emul_build)(cur, keys, NN)
    cur.execute('CHECKPOINT')
    parts = [rows[c::C] for c in range(C)]; stats = dict(accepted=0, rejected=0, retries=0, gave_up=0, attempted=0)
    lock = threading.Lock(); t0 = time.perf_counter(); deadline = t0 + A.cap
    th = [threading.Thread(target=worker, args=(scheme, p, deadline, stats, lock)) for p in parts]
    [t.start() for t in th]; [t.join() for t in th]
    wall = time.perf_counter() - t0
    cur.execute('SELECT ' + ','.join(X.cname(i) for i in range(X.N)) + ' FROM T ORDER BY rid'); final = cur.fetchall()
    con.close()
    return dict(objects=nobj, wall=round(wall, 3), per_s=round(stats['attempted'] / wall, 1),
                censored=stats['attempted'] < len(rows), **stats), final

if __name__ == '__main__':
    S, G, NN = X.keyset(A.m)
    rows, _ = X.workload(random.Random(11), A.rows, 0, A.values)
    done = set()
    if os.path.exists(A.out):
        for l in open(A.out):
            r = json.loads(l); done.add((r['keyset'], r['m'], r['rows'], r['clients'], r['side'], r['scheme']))
    out = open(A.out, 'a'); chk = psycopg2.connect(**DSN); chk.autocommit = True
    for C in map(int, A.clients.split(',')):
        for side, keys in (('input', S), ('cover', G)):
            for scheme in A.schemes.split(','):
                if (A.keyset, A.m, A.rows, C, side, scheme) in done: continue
                if late(): print('stopped: past', A.stop, flush=True); raise SystemExit
                res, final = run(scheme, keys, NN, rows, C)
                bad = violations(chk, S, NN, final)
                rec = dict(keyset=A.keyset, m=A.m, rows=A.rows, values=A.values, clients=C, side=side, scheme=scheme,
                           keys=len(keys), violations=bad, load=os.getloadavg(), **res)
                out.write(json.dumps(rec) + '\n'); out.flush()
                print(f"conc ks{A.keyset} m={A.m} C={C} {side:5} {scheme:9} {res['per_s']:8.1f} rows/s  wall {res['wall']:7.1f}s  "
                      f"acc {res['accepted']} rej {res['rejected']} retries {res['retries']} gave_up {res['gave_up']} "
                      f"{'CENSORED ' if res['censored'] else ''}violations {bad}", flush=True)
    print('done')
