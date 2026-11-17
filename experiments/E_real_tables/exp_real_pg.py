import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment F: the real Hockey tables in PostgreSQL 16.
For each fully exported table and each mining level (1, 9): create the table with the
profiled NOT NULL columns, enforce either all mined keys (input) or their cover with the
filtered-index scheme of Section 2.4, and insert the table's own rows (one transaction,
batches of 200). Reports indexes, triggers, index size and insert time (median of REPS).
Resumable: one JSON line per (level, table, side)."""
import sys, json, time, statistics, os, itertools
sys.path.insert(0, 'experiments/lib')
import psycopg2, psycopg2.extras
from keys import mincover_general, popcount
from hockey_data import load, tables
from check_mined import read

DSN = __import__('config').DSN
OUT = os.environ.get('ONECOVER_E_OUT', 'results/E_real_tables/real_pg.jsonl')
q = lambda c: '"' + c.replace('"', '""') + '"'

def subsets(lst):
    for r in range(len(lst) + 1):
        yield from (list(c) for c in itertools.combinations(lst, r))

def ddl(keys, cols, nn):
    """Statements enforcing keys (cls, tuple of column names); returns (stmts, n_indexes, n_triggers)."""
    st, ni, nt = [], 0, 0
    for i, (cls, K) in enumerate(keys):
        X = [c for c in K if c in nn]; NK = [c for c in K if c not in nn]
        if cls == 'possible' or (cls in ('partial', 'certain') and not NK):
            st.append(f'CREATE UNIQUE INDEX k{i} ON t ({",".join(map(q, K))})'); ni += 1; continue
        if cls == 'domain':
            st.append(f'CREATE UNIQUE INDEX k{i} ON t ({",".join(map(q, K))}) NULLS NOT DISTINCT'); ni += 1; continue
        for j, P in enumerate(subsets(NK)):
            kc = X + [c for c in NK if c not in P]
            where = ' AND '.join([f'{q(c)} IS NULL' for c in P] + [f'{q(c)} IS NOT NULL' for c in NK if c not in P])
            st.append(f'CREATE UNIQUE INDEX k{i}_{j} ON t ({",".join(map(q, kc)) if kc else "(1)"}) WHERE {where}'); ni += 1
        body = []
        for P in subsets(NK):
            newpat = ' AND '.join([f'NEW.{q(c)} IS NULL' for c in P] + [f'NEW.{q(c)} IS NOT NULL' for c in NK if c not in P])
            probes = []
            for P2 in subsets(NK):
                if cls == 'partial' and not (set(P) <= set(P2) or set(P2) <= set(P)): continue
                if set(P) == set(P2): continue          # same pattern: the unique index does it
                pat = ' AND '.join([f'{q(c)} IS NULL' for c in P2] + [f'{q(c)} IS NOT NULL' for c in NK if c not in P2])
                eq = [f'{q(c)}=NEW.{q(c)}' for c in X] + [f'{q(c)}=NEW.{q(c)}' for c in NK if c not in P and c not in P2]
                probes.append('(' + ' AND '.join([pat] + eq) + ')')
            if probes:
                body.append(f"  IF ({newpat}) AND EXISTS (SELECT 1 FROM t WHERE {' OR '.join(probes)}) THEN RAISE EXCEPTION 'k{i}'; END IF;")
        if body:
            st.append(f'CREATE FUNCTION chk{i}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN\n' + '\n'.join(body) + '\n RETURN NEW; END $$')
            st.append(f'CREATE TRIGGER trg{i} BEFORE INSERT ON t FOR EACH ROW EXECUTE FUNCTION chk{i}()'); nt += 1
    return st, ni, nt

def run(con, cols, rows, nn, keys):
    cur = con.cursor()
    cur.execute('DROP TABLE IF EXISTS t CASCADE')
    cur.execute('DROP FUNCTION IF EXISTS ' + ', '.join(f'chk{i}()' for i in range(len(keys))) if keys else 'SELECT 1')
    cur.execute('CREATE TABLE t (' + ', '.join(f'{q(c)} bigint' + (' NOT NULL' if c in nn else '') for c in cols) + ')')
    st, ni, nt = ddl(keys, cols, nn)
    t0 = time.perf_counter()
    for s in st: cur.execute(s)
    t_ddl = time.perf_counter() - t0; con.commit()
    ins = 'INSERT INTO t VALUES (' + ','.join(['%s'] * len(cols)) + ')'
    t0 = time.perf_counter()
    psycopg2.extras.execute_batch(cur, ins, rows, page_size=200)
    con.commit(); t_ins = time.perf_counter() - t0
    cur.execute("SELECT count(*), coalesce(sum(pg_relation_size(indexrelid)),0) FROM pg_index WHERE indrelid = 't'::regclass")
    nidx, size = cur.fetchone(); size = int(size); cur.execute('SELECT count(*) FROM t'); n = cur.fetchone()[0]
    return dict(indexes=ni, pg_indexes=nidx, triggers=nt, index_bytes=size, t_ddl=t_ddl, t_insert=t_ins, rows=n)

if __name__ == '__main__':
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT): r = json.loads(l); done.add((r['level'], r['table'], r['side']))
    con = psycopg2.connect(**DSN); full = set(tables())
    out = open(OUT, 'a')
    for level in [9, 1]:
        T = read(level)
        for tname in sorted(T, key=lambda x: len(T[x])):
            if tname not in full: continue
            cols, rows, nn = load(tname); ci = {c: i for i, c in enumerate(cols)}
            S = [(cls, sum(1 << ci[c] for c in K)) for cls, K in T[tname]]
            NN = sum(1 << ci[c] for c in nn)
            G = mincover_general(S, NN)
            name = lambda m: tuple(c for c in cols if m >> ci[c] & 1)
            sides = {'input': [(c, name(m)) for c, m in S], 'cover': [(c, name(m)) for c, m in G]}
            for side, keys in sides.items():
                if (level, tname, side) in done: continue
                reps = 1 if len(keys) > 500 else 3
                rs = [run(con, cols, rows, nn, keys) for _ in range(reps)]
                rec = dict(level=level, table=tname, side=side, keys=len(keys), reps=reps,
                           **{k: rs[0][k] for k in ('indexes', 'pg_indexes', 'triggers', 'index_bytes', 'rows')},
                           t_ddl=statistics.median(r['t_ddl'] for r in rs), t_insert=statistics.median(r['t_insert'] for r in rs))
                assert rec['rows'] == len(rows), 'a row was rejected'
                out.write(json.dumps(rec) + '\n'); out.flush()
                print(level, tname, side, rec['keys'], 'keys', rec['indexes'], 'idx', rec['triggers'], 'trg',
                      f"{rec['index_bytes']/1024:.0f} KiB", f"ins {rec['t_insert']:.2f}s", flush=True)
    print('done')
