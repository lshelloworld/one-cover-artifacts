import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT, _os.path.join(_ROOT, 'experiments', 'D_enforcement'), _os.path.dirname(_os.path.abspath(__file__))]
"""M0 correctness for nbtnull: random statements against a brute-force oracle.

For every combination of mode (subsumed, compatible), NOT NULL columns nx in {0,1,2}, nullable columns
n in {1,2,3} and shadow depth d in {0..n}, a random sequence of inserts and updates over small domains
(values 0..V-1, default V=3, each nullable column NULL with probability 0.35, so rows with several nulls
occur) is executed, each statement in its own savepoint inside one
transaction (as in Experiment D), and also in autocommit. Every accept/reject decision must equal the
oracle's. Usage: test_correctness.py [statements per run] [seeds] [domain size] [mode:nx:n]"""
import sys, random, itertools
import psycopg2

DSN = dict(__import__('config').DSN, gssencmode='disable')
STMTS = int(sys.argv[1]) if len(sys.argv) > 1 else 250
SEEDS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
V = int(sys.argv[3]) if len(sys.argv) > 3 else 3        # domain size of every column
ONLY = sys.argv[4] if len(sys.argv) > 4 else None       # e.g. 'compatible:0:3' to run one mode, nx, n

def conflict(mode, s, t):
    """s, t: tuples (x..., n...) with None for null, restricted to the key; True if they violate."""
    for a, b in zip(s, t):
        if a is not None and b is not None and a != b:
            return False
    if mode == 'compatible':
        return True
    sn = {i for i, v in enumerate(s) if v is None}; tn = {i for i, v in enumerate(t) if v is None}
    return sn <= tn or tn <= sn

def run(cur, mode, nx, n, d, seed, autocommit, con):
    rnd = random.Random(seed)
    X = [f'x{i}' for i in range(nx)]; N = [f'n{j}' for j in range(n)]
    cur.execute('DROP TABLE IF EXISTS t')
    cur.execute('CREATE TABLE t(rid serial, ' + ', '.join([f'{c} int NOT NULL' for c in X] + [f'{c} int' for c in N]) + ')')
    cur.execute('SELECT nbtnull_key_ddl(%s, %s, %s, %s, %s, %s)', ('k', 't', X or None, N, mode, d))
    cur.execute(cur.fetchone()[0])
    if not autocommit: con.commit()
    rows = {}; mism = 0; acc = rej = 0
    def rand_row():
        return tuple(rnd.randrange(V) for _ in X) + tuple(None if rnd.random() < 0.35 else rnd.randrange(V) for _ in N)
    for i in range(STMTS):
        upd = rows and rnd.random() < 0.2
        if upd:
            rid = rnd.choice(sorted(rows)); r = list(rows[rid]); c = rnd.randrange(nx + n)
            r[c] = rnd.randrange(V) if c < nx or rnd.random() < 0.6 else None; r = tuple(r)
            expect = not any(conflict(mode, r, t) for k, t in rows.items() if k != rid)
            sql = 'UPDATE t SET ' + ', '.join(f'{col} = %s' for col in X + N) + ' WHERE rid = %s'; args = r + (rid,)
        else:
            r = rand_row(); expect = not any(conflict(mode, r, t) for t in rows.values())
            sql = 'INSERT INTO t(' + ', '.join(X + N) + ') VALUES (' + ', '.join(['%s'] * (nx + n)) + ') RETURNING rid'; args = r
        if not autocommit: cur.execute('SAVEPOINT s')
        try:
            cur.execute(sql, args); got = True
            new = cur.fetchone()[0] if not upd else None
        except psycopg2.errors.UniqueViolation:
            got = False
            if not autocommit: cur.execute('ROLLBACK TO SAVEPOINT s')
        if got and not autocommit: cur.execute('RELEASE SAVEPOINT s')
        if got:
            if upd: rows[rid] = r
            else: rows[new] = r
            acc += 1
        else: rej += 1
        if got != expect:
            mism += 1
            if mism <= 3: print(f'  MISMATCH {mode} nx={nx} n={n} d={d} seed={seed} stmt {i}: {"update" if upd else "insert"} {r} db={got} oracle={expect}')
    if not autocommit: con.commit()
    cur.execute('SELECT count(*) FROM t'); assert cur.fetchone()[0] == len(rows)
    return mism, acc, rej

if __name__ == '__main__':
    tot = bad = 0; acc_all = rej_all = 0
    for autocommit in (False, True):
        con = psycopg2.connect(**DSN); con.autocommit = autocommit; cur = con.cursor()
        for mode in ('subsumed', 'compatible'):
            for nx in (0, 1, 2):
                for n in (1, 2, 3):
                    if ONLY and ONLY != f'{mode}:{nx}:{n}': continue
                    for d in range(n + 1):
                        for seed in range(SEEDS):
                            m, a, r = run(cur, mode, nx, n, d, seed * 7919 + nx * 31 + n * 7 + d, autocommit, con)
                            tot += 1; bad += m > 0; acc_all += a; rej_all += r
        con.close()
    print(f'{tot} runs of {STMTS} statements: {bad} with mismatches; {acc_all} accepted, {rej_all} rejected in all')
    sys.exit(1 if bad else 0)
