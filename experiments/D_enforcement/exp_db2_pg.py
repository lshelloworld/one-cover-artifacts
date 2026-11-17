import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment D (PostgreSQL): enforce key sets with the index scheme of Section 2.

Port of exp_db2.py from sqlite3 to psycopg2.  Differences from the SQLite run:
  * domain(K)        : UNIQUE INDEX ... NULLS NOT DISTINCT (PostgreSQL >= 15)
  * partial/certain  : filtered UNIQUE indexes + one PL/pgSQL BEFORE INSERT OR UPDATE
                       trigger per key branching on the null pattern of NEW
                       (exactly the script pg_script() of exp_db2.py emitted)
  * row identity     : T gets an extra column rid SERIAL (no index) standing in for
                       SQLite's rowid; updates and the self-join check address rows by it
  * transactions     : each run is one transaction with a SAVEPOINT per statement,
                       mirroring sqlite3's single implicit transaction (no fsync per row)

keys.py (cover computation) is not available; instead the input Sigma and its
cover Gamma are read from the original db2_log.jsonl.  The seeded RNG regenerates
the identical inputs and workloads, which is asserted against the log.
"""
import sys, json, time, random, statistics, os, itertools
import psycopg2, psycopg2.extras
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ORIG_LOG = 'results/D_enforcement/db2_log.jsonl'
OUT = 'results/D_enforcement'
os.makedirs(OUT, exist_ok=True); os.makedirs(f'{OUT}/pg', exist_ok=True)
DSN = __import__('config').DSN
N, K = 8, 2
ROWS, UPDATES = 1500, 600
V, NULLP = 200, 0.05
NULL_ROW = 0.3
TRIALS = 5
MAXSIZE = 5
rng = random.Random(11)
FRAGMENTS = {'F1': ['possible', 'domain', 'partial'],
             'F2': ['possible', 'domain', 'certain'],
             'ALL': ['possible', 'domain', 'partial', 'certain']}

def cname(i): return f'c{i}'
def cols(mask): return [cname(i) for i in range(N) if mask >> i & 1]
def fmt_mask(mask, n): return ''.join(chr(65 + i) for i in range(n) if mask >> i & 1)
def parse_key(s):
    cls, letters = s[:-1].split('(')
    return cls, sum(1 << (ord(ch) - 65) for ch in letters)
def occ(keys): return sum(bin(m).count('1') for _, m in keys)
def subsets(lst):
    for r in range(len(lst) + 1):
        for c in itertools.combinations(lst, r):
            yield list(c)

def random_keys_capped(n, k, m, frag):
    NN = (1 << k) - 1; classes = FRAGMENTS[frag]; keys = set()
    while len(keys) < m:
        size = min(MAXSIZE, 2 + sum(rng.random() < 0.3 for _ in range(n - 2)))
        mask = sum(1 << c for c in rng.sample(range(n), size))
        keys.add((rng.choice(classes), mask))
    return NN, sorted(keys)

# ------------------------------------------------------------- index DDL (verbatim)
def pattern_where(P, NK):
    terms = [f'{c} IS NULL' for c in P] + [f'{c} IS NOT NULL' for c in NK if c not in P]
    return ' AND '.join(terms) if terms else 'TRUE'

def index_ddl(i, cls, mask, NNmask):
    cs = cols(mask); X = cols(mask & NNmask); NK = cols(mask & ~NNmask)
    out = []
    if cls == 'possible':
        out.append(f"CREATE UNIQUE INDEX k{i} ON T({','.join(cs)})")
    elif cls == 'domain':
        out.append(f"CREATE UNIQUE INDEX k{i} ON T({','.join(cs)}) NULLS NOT DISTINCT")
    else:
        for j, P in enumerate(subsets(NK)):
            keycols = X + [c for c in NK if c not in P]
            if keycols:
                out.append(f"CREATE UNIQUE INDEX k{i}_{j} ON T({','.join(keycols)}) WHERE {pattern_where(P, NK)}")
            else:
                out.append(f"CREATE UNIQUE INDEX k{i}_{j} ON T((1)) WHERE {pattern_where(P, NK)}")
    return out

def trigger_ddl(i, cls, mask, NNmask):
    """Returns (statements, number of probes).  Probes are counted as in the SQLite
    run (one per (pattern, event)), so the numbers are comparable to db2_log.jsonl."""
    X = cols(mask & NNmask); NK = cols(mask & ~NNmask); body = []; nprobe = 0
    for P in subsets(NK):
        newpat = ' AND '.join([f'NEW.{c} IS NULL' for c in P] + [f'NEW.{c} IS NOT NULL' for c in NK if c not in P]) or 'TRUE'
        probes = []
        for P2 in subsets(NK):
            if cls == 'partial' and not (set(P) <= set(P2) or set(P2) <= set(P)):
                continue
            eq = [f'{c}=NEW.{c}' for c in X] + [f'{c}=NEW.{c}' for c in NK if c not in P and c not in P2]
            probes.append('(' + ' AND '.join([pattern_where(P2, NK)] + eq) + ')')
        exists = ' OR '.join(f"EXISTS (SELECT 1 FROM T WHERE {p} AND (TG_OP = 'INSERT' OR ctid <> OLD.ctid))" for p in probes)
        body.append(f"  IF ({newpat}) AND ({exists}) THEN RAISE EXCEPTION '{cls} key k{i} violated'; END IF;")
        nprobe += 2
    fn = f"CREATE OR REPLACE FUNCTION chk_k{i}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN\n" + '\n'.join(body) + "\n  RETURN NEW; END $$"
    trg = f"CREATE TRIGGER trg_k{i} BEFORE INSERT OR UPDATE ON T FOR EACH ROW EXECUTE FUNCTION chk_k{i}()"
    return [fn, trg], nprobe

def table_ddl(NNmask):
    return 'CREATE TABLE T(rid SERIAL, ' + ','.join(f'{cname(i)} INTEGER' + (' NOT NULL' if NNmask >> i & 1 else '') for i in range(N)) + ')'

def pg_script(keys, NNmask):
    lines = ['DROP TABLE IF EXISTS T CASCADE;', table_ddl(NNmask) + ';']
    for i, (cls, mask) in enumerate(keys):
        lines += [s + ';' for s in index_ddl(i, cls, mask, NNmask)]
        if cls in ('partial', 'certain'):
            lines += [s + ';' for s in trigger_ddl(i, cls, mask, NNmask)[0]]
    return '\n'.join(lines) + '\n'

# ------------------------------------------------------------------ run
def check_sql(cls, mask):
    cs = cols(mask)
    if cls == 'possible': cond = ' AND '.join(f'a.{c}=b.{c}' for c in cs)
    elif cls == 'domain': cond = ' AND '.join(f'a.{c} IS NOT DISTINCT FROM b.{c}' for c in cs)
    elif cls == 'certain': cond = ' AND '.join(f'(a.{c} IS NULL OR b.{c} IS NULL OR a.{c}=b.{c})' for c in cs)
    else: cond = '(' + ' AND '.join(f'(a.{c} IS NULL OR a.{c}=b.{c})' for c in cs) + ')'
    return f"SELECT 1 FROM T a, T b WHERE a.rid<b.rid AND {cond} LIMIT 1"

def make_db(cur, keys, NNmask):
    cur.execute('DROP TABLE IF EXISTS T CASCADE')
    cur.execute(table_ddl(NNmask))
    nidx = ntrg = 0
    for i, (cls, mask) in enumerate(keys):
        for s in index_ddl(i, cls, mask, NNmask): cur.execute(s); nidx += 1
        if cls in ('partial', 'certain'):
            stmts, np_ = trigger_ddl(i, cls, mask, NNmask)
            for s in stmts: cur.execute(s)
            ntrg += np_
    return nidx, ntrg

REJECT = (psycopg2.IntegrityError, psycopg2.errors.RaiseException)

def guarded(cur, sql, params):
    cur.execute('SAVEPOINT s')
    try:
        cur.execute(sql, params); cur.execute('RELEASE SAVEPOINT s'); return True
    except REJECT:
        cur.execute('ROLLBACK TO SAVEPOINT s'); return False

def workload():
    rows = []
    for _ in range(ROWS):
        r = [rng.randrange(V) for _ in range(N)]
        if rng.random() < NULL_ROW: r[rng.randrange(K, N)] = None
        rows.append(tuple(r))
    ups = [(rng.randrange(ROWS), rng.randrange(K, N), (None if rng.random() < NULLP else rng.randrange(V))) for _ in range(UPDATES)]
    return rows, ups

def run_db(con, keys, NNmask, rows, ups):
    cur = con.cursor()
    t0 = time.perf_counter(); nidx, ntrg = make_db(cur, keys, NNmask); t_ddl = time.perf_counter() - t0
    ins = 'INSERT INTO T(' + ','.join(cname(i) for i in range(N)) + ') VALUES(' + ','.join(['%s'] * N) + ')'
    acc = 0; t0 = time.perf_counter()
    for r in rows:
        if guarded(cur, ins, r): acc += 1
    t_ins = time.perf_counter() - t0
    cur.execute('SELECT rid FROM T ORDER BY rid'); ids = [x[0] for x in cur.fetchall()]
    t0 = time.perf_counter(); ok = 0
    for (j, c, v) in ups:
        if guarded(cur, f'UPDATE T SET {cname(c)}=%s WHERE rid=%s', (v, ids[j % len(ids)])): ok += 1
    t_upd = time.perf_counter() - t0
    cur.execute('SELECT ' + ','.join(cname(i) for i in range(N)) + ' FROM T')
    state = sorted(cur.fetchall(), key=lambda x: tuple(-1 if v is None else v for v in x))
    t0 = time.perf_counter()
    for cls, mask in keys:
        cur.execute(check_sql(cls, mask)); assert cur.fetchone() is None, (cls, mask)
    t_chk = time.perf_counter() - t0
    con.commit()
    return dict(accepted=acc, updated=ok, t_insert=t_ins, t_update=t_upd, t_check=t_chk, t_ddl=t_ddl, indexes=nidx, triggers=ntrg), state


def _init():
    global WDB; WDB = f'keys_w{os.getpid()}'
    adm = psycopg2.connect(**DSN); adm.autocommit = True
    adm.cursor().execute(f'DROP DATABASE IF EXISTS {WDB}'); adm.cursor().execute(f'CREATE DATABASE {WDB}'); adm.close()

def one(job):
    frag, m, t, NN, S, G, rows, ups, o = job
    con = psycopg2.connect(**dict(DSN, dbname=WDB)); con.autocommit = False
    rS, stS = run_db(con, S, NN, rows, ups); rG, stG = run_db(con, G, NN, rows, ups); con.close()
    assert stS == stG, 'cover and input accepted different data!'
    same = (rS['accepted'], rS['updated']) == (o['sigma']['accepted'], o['sigma']['updated'])
    return dict(fragment=frag, m=m, trial=t, in_keys=len(S), in_occ=occ(S), out_keys=len(G), out_occ=occ(G),
                sigma=rS, cover=rG, accepted_equal=True, same_as_sqlite=same, input=o['input'], output=o['output'])

if __name__ == '__main__':
    from concurrent.futures import ProcessPoolExecutor, as_completed
    NW = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    orig = [json.loads(l) for l in open(ORIG_LOG)]
    done = {}
    if os.path.exists(f'{OUT}/db2_pg_log.jsonl'):
        for l in open(f'{OUT}/db2_pg_log.jsonl'):
            r = json.loads(l); done[(r['fragment'], r['m'], r['trial'])] = r
    jobs = []; idx = 0
    for frag in ['F1', 'F2', 'ALL']:
        for m in [10, 20, 40, 80, 120]:
            for t in range(TRIALS):
                NN, S = random_keys_capped(N, K, m, frag); o = orig[idx]; idx += 1
                assert [f'{c}({fmt_mask(mk, N)})' for c, mk in S] == o['input'], 'RNG drift'
                G = [parse_key(s) for s in o['output']]
                rows, ups = workload()
                if t == 0:
                    open(f'{OUT}/pg/{frag}_m{m}_input.sql', 'w').write(pg_script(S, NN))
                    open(f'{OUT}/pg/{frag}_m{m}_cover.sql', 'w').write(pg_script(G, NN))
                if (frag, m, t) not in done: jobs.append((frag, m, t, NN, S, G, rows, ups, o))
    jobs.sort(key=lambda j: -j[1])   # biggest first
    LOG = open(f'{OUT}/db2_pg_log.jsonl', 'a')
    with ProcessPoolExecutor(NW, initializer=_init) as ex:
        futs = [ex.submit(one, j) for j in jobs]
        for f in as_completed(futs):
            rec = f.result(); done[(rec['fragment'], rec['m'], rec['trial'])] = rec
            LOG.write(json.dumps(rec) + '\n'); LOG.flush()
            rS, rG = rec['sigma'], rec['cover']
            print(rec['fragment'], rec['m'], rec['trial'], 'idx %d/%d trg %d/%d ins %.2f/%.2f upd %.2f/%.2f chk %.2f/%.2f' % (
                rS['indexes'], rG['indexes'], rS['triggers'], rG['triggers'], rS['t_insert'], rG['t_insert'], rS['t_update'], rG['t_update'], rS['t_check'], rG['t_check']),
                'sqlite-match' if rec['same_as_sqlite'] else 'SQLITE-MISMATCH', flush=True)
    LOG.close()
    results = [done[k] for k in sorted(done, key=lambda k: (['F1','F2','ALL'].index(k[0]), k[1], k[2]))]
    json.dump(results, open(f'{OUT}/db2_pg_results.json', 'w'))
    COL = {'F1': 'tab:blue', 'F2': 'tab:orange', 'ALL': 'tab:green'}
    LBL = {'F1': r'$\mathcal{F}_1$', 'F2': r'$\mathcal{F}_2$', 'ALL': 'combined class'}
    fig, ax = plt.subplots(1, 4, figsize=(16, 3.6))
    for frag in COL:
        xs = sorted(set(r['m'] for r in results if r['fragment'] == frag))
        for j, (what, title) in enumerate([('t_insert', 'inserts'), ('t_update', 'updates'), ('t_check', 'integrity check')]):
            ys = [statistics.mean(r['sigma'][what] for r in results if r['fragment'] == frag and r['m'] == x) for x in xs]
            yg = [statistics.mean(r['cover'][what] for r in results if r['fragment'] == frag and r['m'] == x) for x in xs]
            ax[j].plot(xs, ys, 'o--', color=COL[frag], label=LBL[frag] + ', input'); ax[j].plot(xs, yg, 's-', color=COL[frag], label=LBL[frag] + ', cover')
            ax[j].set_xlabel(r'$|\Sigma|$'); ax[j].set_ylabel('seconds'); ax[j].set_title(title)
        ys = [statistics.mean(r['sigma']['indexes'] for r in results if r['fragment'] == frag and r['m'] == x) for x in xs]
        yg = [statistics.mean(r['cover']['indexes'] for r in results if r['fragment'] == frag and r['m'] == x) for x in xs]
        ax[3].plot(xs, ys, 'o--', color=COL[frag]); ax[3].plot(xs, yg, 's-', color=COL[frag]); ax[3].set_title('indexes created'); ax[3].set_xlabel(r'$|\Sigma|$')
    ax[0].legend(fontsize=7)
    fig.suptitle(f"Experiment D (PostgreSQL): filtered-index enforcement, {N} columns, {ROWS} inserts, {UPDATES} updates (mean of {TRIALS} trials)")
    fig.tight_layout(); fig.savefig(f'{OUT}/expD_pg.pdf'); fig.savefig(f'{OUT}/expD_pg.png', dpi=110)
    # LaTeX table in the layout of tab:expD
    rows_tex = []
    for frag, name in [('F1', r'$\mathcal F_1$'), ('F2', r'$\mathcal F_2$'), ('ALL', 'combined')]:
        for m in [10, 40, 120]:
            rs = [r for r in results if r['fragment'] == frag and r['m'] == m]
            mean = lambda side, k: statistics.mean(r[side][k] for r in rs)
            rows_tex.append(f"{name if m == 10 else ''} & {m} & {mean('cover','_') if False else statistics.mean(r['out_keys'] for r in rs):.1f} & "
                            f"{mean('sigma','indexes'):.0f} & {mean('cover','indexes'):.0f} & {mean('sigma','triggers'):.0f} & {mean('cover','triggers'):.0f} & "
                            f"{mean('sigma','t_insert'):.2f} & {mean('cover','t_insert'):.2f} & {mean('sigma','t_update'):.2f} & {mean('cover','t_update'):.2f} & "
                            f"{mean('sigma','t_check'):.2f} & {mean('cover','t_check'):.2f} \\\\")
    open(f'{OUT}/tab_expD_pg.tex', 'w').write('\n'.join(rows_tex) + '\n')
    print('done')
