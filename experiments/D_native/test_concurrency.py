import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT, _os.path.join(_ROOT, 'experiments', 'D_enforcement'), _os.path.dirname(_os.path.abspath(__file__))]
"""M0 concurrency and crash tests for nbtnull (READ COMMITTED).

1. wait: session A inserts a row and keeps its transaction open; session B inserts a conflicting row and
   must block; when A commits, B must fail with unique_violation; when A rolls back, B must succeed.
   Run for equal complete rows, for B with a null where A has a value and the reverse, for patterns two
   nulls apart at depth 0, for incomparable patterns, and for a non-conflicting pair (B must not block).
2. stress: 8 threads insert random rows over a small domain, in transactions of 1-4 statements, for both
   modes and depths 0 and 1; afterwards the table must contain no conflicting pair (checked in Python).
3. crash: rows are committed, the server is stopped with -m immediate and restarted; the index must still
   reject conflicting rows and accept new ones.
Usage: test_concurrency.py [stress transactions per thread] [x0 domain] [n_j domain]"""
import sys, time, threading, random, subprocess, os
import psycopg2
from test_correctness import DSN, conflict

PER = int(sys.argv[1]) if len(sys.argv) > 1 else 400
DX, DN = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (3, 4)   # stress domains of x0 and of n_j
PG = os.environ.get('ONECOVER_PG_BIN', '/Library/PostgreSQL/18/bin')   # pg_ctl of the cluster
DATA = os.environ.get('ONECOVER_PG_DATA', '')                           # its data directory (crash test only)

def setup(mode, nx, n, d, table='tc'):
    con = psycopg2.connect(**DSN); con.autocommit = True; cur = con.cursor()
    X = [f'x{i}' for i in range(nx)]; N = [f'n{j}' for j in range(n)]
    cur.execute(f'DROP TABLE IF EXISTS {table}')
    cur.execute(f'CREATE TABLE {table}(rid serial, ' + ', '.join([f'{c} int NOT NULL' for c in X] + [f'{c} int' for c in N]) + ')')
    cur.execute('SELECT nbtnull_key_ddl(%s, %s, %s, %s, %s, %s)', (table + '_k', table, X or None, N, mode, d))
    cur.execute(cur.fetchone()[0]); con.close()
    return 'INSERT INTO ' + table + '(' + ', '.join(X + N) + ') VALUES (' + ', '.join(['%s'] * (nx + n)) + ')'

def wait_case(mode, n, d, a, b, expect_conflict):
    ins = setup(mode, 0, n, d)
    out = []
    for finish in ('commit', 'rollback'):
        A = psycopg2.connect(**DSN); B = psycopg2.connect(**DSN); B.autocommit = True
        ca = A.cursor(); ca.execute('TRUNCATE tc'); A.commit(); ca.execute(ins, a)
        res = {}
        def runb():
            t0 = time.time()
            try: B.cursor().execute(ins, b); res['ok'] = True
            except psycopg2.errors.UniqueViolation: res['ok'] = False
            res['t'] = time.time() - t0
        th = threading.Thread(target=runb); th.start(); time.sleep(0.5)
        blocked = th.is_alive()
        (A.commit if finish == 'commit' else A.rollback)(); th.join(10)
        want_ok = not (expect_conflict and finish == 'commit')
        good = (blocked == expect_conflict) and res.get('ok') == want_ok
        out.append(good)
        if not good: print(f'  FAIL {mode} n={n} d={d} A={a} B={b} {finish}: blocked={blocked} B ok={res.get("ok")} (want blocked={expect_conflict}, ok={want_ok})')
        A.close(); B.close()
    return all(out)

def stress(mode, n, d, threads=8):
    ins = setup(mode, 1, n, d, 'ts'); errs = []
    def worker(seed):
        rnd = random.Random(seed); con = psycopg2.connect(**DSN); cur = con.cursor()
        for i in range(PER):
            k = rnd.randint(1, 4)
            try:
                for _ in range(k):
                    r = (rnd.randrange(DX),) + tuple(None if rnd.random() < 0.3 else rnd.randrange(DN) for _ in range(n))
                    cur.execute(ins, r)
                con.commit()
            except (psycopg2.errors.UniqueViolation, psycopg2.errors.DeadlockDetected):
                con.rollback()
            except Exception as e:
                errs.append(repr(e)); con.rollback()
        con.close()
    ths = [threading.Thread(target=worker, args=(s,)) for s in range(threads)]
    t0 = time.time(); [t.start() for t in ths]; [t.join() for t in ths]; dt = time.time() - t0
    con = psycopg2.connect(**DSN); cur = con.cursor()
    cur.execute('SELECT x0, ' + ', '.join(f'n{j}' for j in range(n)) + ' FROM ts'); rows = cur.fetchall()
    con.close()
    bad = sum(conflict(mode, rows[i], rows[j]) for i in range(len(rows)) for j in range(i))
    print(f'  stress {mode} n={n} d={d}: {len(rows)} rows after {threads}x{PER} transactions in {dt:.1f}s, '
          f'{bad} conflicting pairs, {len(errs)} other errors {errs[:2]}')
    return bad == 0 and not errs

def crash():
    ins = setup('compatible', 1, 3, 1, 'tcr')
    con = psycopg2.connect(**DSN); con.autocommit = True; cur = con.cursor()
    rnd = random.Random(3); kept = []
    for i in range(3000):
        r = (rnd.randrange(50),) + tuple(None if rnd.random() < 0.3 else rnd.randrange(50) for _ in range(3))
        try: cur.execute(ins, r); kept.append(r)
        except psycopg2.errors.UniqueViolation: pass
    con.close()
    subprocess.run([f'{PG}/pg_ctl', '-D', DATA, '-m', 'immediate', '-w', 'stop'], check=True, capture_output=True)
    subprocess.run(['bash', '-c', f'ulimit -n 10240; {PG}/pg_ctl -D {DATA} -o "-p {DSN["port"]} -c max_files_per_process=9000 '
                    f'-c listen_addresses=localhost -c unix_socket_directories=\'\'" -l {DATA}/server.log -w start'],
                   check=True, capture_output=True)
    con = psycopg2.connect(**DSN); con.autocommit = True; cur = con.cursor()
    rej = acc = 0
    for r in kept[:300]:                    # each a duplicate of a committed row: must be rejected
        try: cur.execute(ins, r); acc += 1
        except psycopg2.errors.UniqueViolation: rej += 1
    cur.execute('SELECT count(*) FROM tcr'); n = cur.fetchone()[0]
    fresh = 0
    for i in range(200):                    # rows over a disjoint domain: must be accepted
        try: cur.execute(ins, (1000 + i, 1000 + i, 1000 + i, 1000 + i)); fresh += 1
        except psycopg2.errors.UniqueViolation: pass
    con.close()
    ok = rej == 300 and n == len(kept) and fresh == 200
    print(f'  crash: {len(kept)} rows before the immediate stop, {n} after restart; {rej}/300 duplicates rejected, {fresh}/200 new rows accepted')
    return ok

if __name__ == '__main__':
    good = True
    print('1. waiting on in-progress conflicts')
    for mode in ('compatible', 'subsumed'):
        good &= wait_case(mode, 2, 1, (1, 1), (1, 1), True)          # equal complete rows
        good &= wait_case(mode, 2, 1, (1, 1), (1, None), True)       # B less complete
        good &= wait_case(mode, 2, 1, (1, None), (1, 1), True)       # B more complete
        good &= wait_case(mode, 2, 0, (1, 1), (None, None), True)    # patterns two nulls apart, depth 0
        good &= wait_case(mode, 2, 1, (1, 1), (2, 2), False)         # no conflict: B must not block
    good &= wait_case('compatible', 2, 1, (1, None), (None, 1), True)   # incomparable patterns: certain only
    good &= wait_case('subsumed', 2, 1, (1, None), (None, 1), False)
    good &= wait_case('compatible', 2, 0, (1, None), (None, 1), True)   # the same beyond depth 0
    print('   ', 'all as expected' if good else 'FAILURES')
    print('2. stress, 8 sessions')
    for mode in ('compatible', 'subsumed'):
        for d in (0, 1):
            good &= stress(mode, 3, d)
    print('3. crash and restart')
    if DATA: good &= crash()
    else: print('   skipped: set ONECOVER_PG_DATA to the cluster data directory')
    print('ALL PASSED' if good else 'SOME FAILED'); sys.exit(0 if good else 1)
