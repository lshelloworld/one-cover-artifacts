import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT]
_os.chdir(_ROOT)
"""What does a uniqueness check cost per insert in PostgreSQL, by the mechanism that performs it?

The same k keys (each on 3 of 6 NOT NULL integer columns) are enforced in five ways:
  none      no index                                              (the bare insert)
  index     a plain B-tree per key, no check                      (index maintenance)
  unique    a UNIQUE index per key                                (check inside the B-tree insert)
  exclude   EXCLUDE USING btree (.. WITH =) per key               (insert, then a separate index scan by the executor)
  trigger   a plain B-tree per key + one PL/pgSQL trigger per key (an EXISTS probe, as in our scheme for partial/certain keys)
The rows are random over a large domain, so no insert is rejected and all five do the same work apart from the
check. Two workloads: 'bulk' is one INSERT .. SELECT of BULK rows from a staging table (no client cost);
'single' is SINGLE inserts, one statement per row, in one transaction. Each configuration is repeated REPS
times, interleaved; medians are reported. (unique - index) and (exclude - index) are the cost of the check
in the B-tree and in the executor; their ratio is the overhead a native in-tree check would save per probe.
Writes results/D_enforcement/unique_vs_exclude.json.
Usage: exp_unique_vs_exclude.py [bulk rows] [single rows] [reps]"""
import sys, json, time, random, statistics, itertools
import psycopg2
DSN = __import__('config').DSN
BULK = int(sys.argv[1]) if len(sys.argv) > 1 else 500000
SINGLE = int(sys.argv[2]) if len(sys.argv) > 2 else 100000
REPS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
NC, V = 6, 1000000
OUT = _os.environ.get('ONECOVER_UVX_OUT', 'results/D_enforcement/unique_vs_exclude.json')
CS = [f'c{i}' for i in range(NC)]
KEYS = list(itertools.combinations(CS, 3))[:8]          # 8 distinct 3-column keys
CONFIGS = ('none', 'index', 'unique', 'exclude', 'trigger')

def build(cur, what, k):
    cur.execute('DROP TABLE IF EXISTS uvx_t CASCADE')
    cur.execute('CREATE TABLE uvx_t(' + ','.join(f'{c} int NOT NULL' for c in CS) + ')')
    for i, key in enumerate(KEYS[:k] if what != 'none' else []):
        cl = ','.join(key)
        if what == 'unique': cur.execute(f'CREATE UNIQUE INDEX uvx_i{i} ON uvx_t({cl})')
        elif what == 'exclude': cur.execute(f'ALTER TABLE uvx_t ADD CONSTRAINT uvx_i{i} EXCLUDE USING btree (' + ','.join(f'{c} WITH =' for c in key) + ')')
        else: cur.execute(f'CREATE INDEX uvx_i{i} ON uvx_t({cl})')
        if what == 'trigger':
            cond = ' AND '.join(f'{c} = NEW.{c}' for c in key)
            cur.execute(f"""CREATE FUNCTION uvx_f{i}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                IF EXISTS (SELECT 1 FROM uvx_t WHERE {cond}) THEN RAISE EXCEPTION 'key {i} violated'; END IF; RETURN NEW; END $$""")
            cur.execute(f'CREATE TRIGGER uvx_g{i} BEFORE INSERT ON uvx_t FOR EACH ROW EXECUTE FUNCTION uvx_f{i}()')

def run(con, what, k, mode, rows):
    cur = con.cursor(); build(cur, what, k); con.commit()
    cl = ','.join(CS)
    t0 = time.perf_counter()
    if mode == 'bulk':
        cur.execute(f'INSERT INTO uvx_t({cl}) SELECT {cl} FROM uvx_stage ORDER BY rid')
    else:
        cur.execute(f'PREPARE uvx_p AS INSERT INTO uvx_t({cl}) VALUES(' + ','.join(f'${i+1}' for i in range(NC)) + ')')
        q = 'EXECUTE uvx_p(' + ','.join(['%s'] * NC) + ')'
        for r in rows: cur.execute(q, r)
    con.commit(); t = time.perf_counter() - t0
    if mode == 'single': cur.execute('DEALLOCATE uvx_p')
    cur.execute('SELECT count(*) FROM uvx_t'); n = cur.fetchone()[0]
    cur.execute('DROP TABLE uvx_t CASCADE')
    for i in range(8): cur.execute(f'DROP FUNCTION IF EXISTS uvx_f{i}()')
    con.commit(); return t, n

if __name__ == '__main__':
    rnd = random.Random(7); rows = [tuple(rnd.randrange(V) for _ in range(NC)) for _ in range(BULK)]
    con = psycopg2.connect(**DSN); cur = con.cursor()
    cur.execute('SELECT version()'); ver = cur.fetchone()[0]
    cur.execute('DROP TABLE IF EXISTS uvx_stage'); cur.execute('CREATE TABLE uvx_stage(rid serial,' + ','.join(f'{c} int' for c in CS) + ')')
    import psycopg2.extras
    psycopg2.extras.execute_values(cur, 'INSERT INTO uvx_stage(' + ','.join(CS) + ') VALUES %s', rows, page_size=10000)
    con.commit(); cur.execute('ANALYZE uvx_stage'); con.commit()
    out = dict(version=ver, bulk=BULK, single=SINGLE, reps=REPS, load_start=_os.getloadavg(), runs=[])
    for mode, n in (('bulk', BULK), ('single', SINGLE)):
        for k in (1, 4, 8):
            times = {w: [] for w in CONFIGS}
            for rep in range(REPS):
                for w in CONFIGS:
                    if w == 'none' and k > 1 and rep > 0: continue      # the bare insert does not depend on k
                    t, cnt = run(con, w, k, mode, rows[:n]); assert cnt == n, (w, k, cnt)
                    times[w].append(t)
            med = {w: statistics.median(v) for w, v in times.items()}
            us = lambda w: (med[w] - med['index']) / (n * k) * 1e6       # microseconds per row and key, for the check alone
            rec = dict(mode=mode, keys=k, rows=n, median_s={w: round(m, 3) for w, m in med.items()}, all_s={w: [round(x, 3) for x in v] for w, v in times.items()},
                       check_us_per_row_key={w: round(us(w), 2) for w in ('unique', 'exclude', 'trigger')},
                       maint_us_per_row_key=round((med['index'] - med['none']) / (n * k) * 1e6, 2), load=_os.getloadavg())
            out['runs'].append(rec); json.dump(out, open(OUT, 'w'), indent=1)
            print(mode, f'k={k}', ' '.join(f'{w} {med[w]:.2f}s' for w in CONFIGS), '| check us/row/key:', rec['check_us_per_row_key'],
                  '| maintenance:', rec['maint_us_per_row_key'], flush=True)
    cur.execute('DROP TABLE uvx_stage'); con.commit()
    out['load_end'] = _os.getloadavg(); json.dump(out, open(OUT, 'w'), indent=1); print('done')
