import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT]
_os.chdir(_ROOT)
"""M1 microbenchmark: the cost per insert of one partial or certain key, by enforcement scheme.

Table T(rid, x0..x{nx-1} NOT NULL, n0..n{n-1}) with one key on all its columns. Rows: values uniform in
[0, V) (V = 32000, as in the million-row runs); 'light' nulls: with probability 0.3 one uniformly chosen
nullable column is NULL (our workload); 'heavy' (n >= 2): additionally, with probability 0.1, two of them.
Rows are generated once per (nx, n, nulls, rows) into a staging table and inserted by a PL/pgSQL loop,
one subtransaction per row (as Experiment D's savepoints), in batches of BATCH rows, each batch one
transaction. A run stops early once it has taken CAP seconds (reported as censored, with the rows reached).

Schemes:  none     no index (the bare insert with its subtransaction)
          btree    a plain B-tree on the key columns (maintenance of one entry, no check)
          unnd     UNIQUE NULLS NOT DISTINCT on the key columns (one entry, check inside the B-tree)
          today    filtered unique indexes per null pattern + PL/pgSQL trigger (exp_db2_pg.py's scheme)
          nbt0     nbtnull, shadow depth 0
          nbt1     nbtnull, shadow depth 1 (nbt2: depth 2, and so on)
none/btree/unnd do not depend on the mode and run once. Writes JSON lines to OUT.
Usage: bench_m1.py --rows 100000 --nx 0,1,2 --n 1,2,3,4 --nulls light,heavy --modes certain,partial
                   --schemes none,btree,unnd,today,nbt0,nbt1 --reps 1 --cap 300 --out m1.jsonl"""
import argparse, itertools, json, os, random, time, io, zlib
import psycopg2

DSN = dict(__import__('config').DSN, gssencmode='disable')
V, BATCH = 32000, 10000
ap = argparse.ArgumentParser()
ap.add_argument('--rows', type=int, default=100000)
ap.add_argument('--nx', default='0,1,2'); ap.add_argument('--n', default='1,2,3,4')
ap.add_argument('--nulls', default='light,heavy'); ap.add_argument('--modes', default='certain,partial')
ap.add_argument('--schemes', default='none,btree,unnd,today,nbt0,nbt1')
ap.add_argument('--reps', type=int, default=1); ap.add_argument('--cap', type=float, default=300)
ap.add_argument('--out', default='m1.jsonl')
A = ap.parse_args()

def subsets(lst): return [list(c) for r in range(len(lst) + 1) for c in itertools.combinations(lst, r)]
def pattern_where(P, NK):
    t = [f'{c} IS NULL' for c in P] + [f'{c} IS NOT NULL' for c in NK if c not in P]
    return ' AND '.join(t) if t else 'TRUE'

def today_ddl(cls, X, NK):
    """exp_db2_pg.py's index_ddl + trigger_ddl for one partial/certain key (i = 0)."""
    out = []
    for j, P in enumerate(subsets(NK)):
        kc = X + [c for c in NK if c not in P]
        out.append(f"CREATE UNIQUE INDEX k0_{j} ON T({','.join(kc) if kc else '(1)'}) WHERE {pattern_where(P, NK)}")
    body = []
    for P in subsets(NK):
        newpat = ' AND '.join([f'NEW.{c} IS NULL' for c in P] + [f'NEW.{c} IS NOT NULL' for c in NK if c not in P]) or 'TRUE'
        probes = []
        for P2 in subsets(NK):
            if cls == 'partial' and not (set(P) <= set(P2) or set(P2) <= set(P)): continue
            eq = [f'{c}=NEW.{c}' for c in X] + [f'{c}=NEW.{c}' for c in NK if c not in P and c not in P2]
            probes.append('(' + ' AND '.join([pattern_where(P2, NK)] + eq) + ')')
        exists = ' OR '.join(f"EXISTS (SELECT 1 FROM T WHERE {p} AND (TG_OP = 'INSERT' OR ctid <> OLD.ctid))" for p in probes)
        body.append(f"  IF ({newpat}) AND ({exists}) THEN RAISE EXCEPTION '{cls} key k0 violated'; END IF;")
    out.append("CREATE OR REPLACE FUNCTION chk_k0() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN\n" + '\n'.join(body) + "\n  RETURN NEW; END $$")
    out.append("CREATE TRIGGER trg_k0 BEFORE INSERT OR UPDATE ON T FOR EACH ROW EXECUTE FUNCTION chk_k0()")
    return out

def gen_rows(nx, n, nulls, rows, seed):
    rnd = random.Random(seed); buf = io.StringIO()
    for i in range(rows):
        r = [str(rnd.randrange(V)) for _ in range(nx + n)]
        u = rnd.random()
        k = 1 if u < 0.3 else (2 if nulls == 'heavy' and n >= 2 and u < 0.4 else 0)
        for j in rnd.sample(range(n), k): r[nx + j] = r'\N'
        buf.write(f'{i}\t' + '\t'.join(r) + '\n')
    buf.seek(0); return buf

def setup_stage(cur, nx, n, nulls, rows):
    X = [f'x{i}' for i in range(nx)]; N = [f'n{j}' for j in range(n)]
    cur.execute('DROP TABLE IF EXISTS S'); cur.execute('CREATE TABLE S(id int, ' + ', '.join(f'{c} int' for c in X + N) + ')')
    cur.copy_from(gen_rows(nx, n, nulls, rows, zlib.crc32(repr((nx, n, nulls, rows)).encode())), 's', columns=['id'] + X + N)
    cur.execute('CREATE INDEX ON S(id)'); cur.execute('ANALYZE S')
    cl = ', '.join(X + N); rv = ', '.join(f'r.{c}' for c in X + N)
    cur.execute(f"""CREATE OR REPLACE FUNCTION m1_load(lo int, hi int, OUT acc int, OUT rej int) LANGUAGE plpgsql AS $$
      DECLARE r record; BEGIN acc := 0; rej := 0;
      FOR r IN SELECT * FROM S WHERE id >= lo AND id < hi ORDER BY id LOOP
        BEGIN INSERT INTO T({cl}) VALUES ({rv}); acc := acc + 1;
        EXCEPTION WHEN unique_violation OR raise_exception THEN rej := rej + 1; END;
      END LOOP; END $$""")
    return X, N

def build(cur, scheme, mode, X, N):
    cur.execute('DROP TABLE IF EXISTS T CASCADE')
    cur.execute('CREATE TABLE T(rid serial, ' + ', '.join([f'{c} int NOT NULL' for c in X] + [f'{c} int' for c in N]) + ')')
    kc = ', '.join(X + N)
    if scheme == 'btree': cur.execute(f'CREATE INDEX k0 ON T({kc})')
    elif scheme == 'unnd': cur.execute(f'CREATE UNIQUE INDEX k0 ON T({kc}) NULLS NOT DISTINCT')
    elif scheme == 'today':
        for s in today_ddl(mode, X, N): cur.execute(s)
    elif scheme.startswith('nbt'):
        cur.execute('SELECT nbtnull_key_ddl(%s, %s, %s, %s, %s, %s)',
                    ('k0', 't', X or None, N, 'compatible' if mode == 'certain' else 'subsumed', int(scheme[-1])))
        cur.execute(cur.fetchone()[0])

def run(con, scheme, mode, X, N, rows):
    cur = con.cursor(); build(cur, scheme, mode, X, N)
    cur.execute('SELECT nbtnull_stats(true)'); cur.execute('CHECKPOINT')
    acc = rej = 0; batches = []; t0 = time.perf_counter(); censored = False
    for lo in range(0, rows, BATCH):
        tb = time.perf_counter(); cur.execute('SELECT * FROM m1_load(%s, %s)', (lo, lo + BATCH)); a, r = cur.fetchone()
        acc += a; rej += r; batches.append(round(time.perf_counter() - tb, 3))
        if time.perf_counter() - t0 > A.cap and lo + BATCH < rows: censored = True; break
    t = time.perf_counter() - t0; done = acc + rej
    cur.execute("SELECT coalesce(sum(pg_relation_size(indexrelid)), 0), count(*) FROM pg_index WHERE indrelid = 't'::regclass")
    isize, nidx = cur.fetchone()
    cur.execute('SELECT * FROM nbtnull_stats()'); st = dict(zip([d[0] for d in cur.description], cur.fetchone()))
    return dict(scheme=scheme, mode=mode if scheme == 'today' or scheme.startswith('nbt') else None, nx=len(X), n=len(N),
                rows_attempted=done, rows_target=rows, censored=censored, accepted=acc, rejected=rej, t=round(t, 3),
                us_per_row=round(t / done * 1e6, 2), batches=batches, index_bytes=int(isize), indexes=int(nidx),
                nbt_stats={k: int(v) for k, v in st.items()} if scheme.startswith('nbt') else None, load=os.getloadavg())

if __name__ == '__main__':
    con = psycopg2.connect(**DSN); con.autocommit = True; cur = con.cursor()
    schemes = A.schemes.split(','); modes = A.modes.split(',')
    out = open(A.out, 'a')
    for nulls in A.nulls.split(','):
        for n in map(int, A.n.split(',')):
            if nulls == 'heavy' and n < 2: continue
            for nx in map(int, A.nx.split(',')):
                X, N = setup_stage(cur, nx, n, nulls, A.rows)
                jobs = [(s, None) for s in schemes if s in ('none', 'btree', 'unnd')] + \
                       [(s, m) for m in modes for s in schemes if s == 'today' or s.startswith('nbt')]
                for rep in range(A.reps):
                    for s, m in (jobs if rep % 2 == 0 else jobs[::-1]):     # interleaved, alternating order
                        rec = run(con, s, m, X, N, A.rows); rec.update(nulls=nulls, rep=rep)
                        out.write(json.dumps(rec) + '\n'); out.flush()
                        print(f"{nulls:5} n={n} nx={nx} {s:5} {str(m or ''):7} rep {rep}: {rec['us_per_row']:9.1f} us/row"
                              f"{' (censored at %d rows)' % rec['rows_attempted'] if rec['censored'] else ''}  acc {rec['accepted']} rej {rec['rejected']}"
                              f"  idx {rec['index_bytes'] // 1024} kB  load {rec['load'][1]:.1f}", flush=True)
    cur.execute('DROP TABLE IF EXISTS T CASCADE'); cur.execute('DROP TABLE IF EXISTS S'); print('done')
