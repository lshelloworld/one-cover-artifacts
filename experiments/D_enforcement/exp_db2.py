import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment D': enforce key sets with the index scheme of Section 2.

possible(K)  : UNIQUE index on K                       (nulls distinct)
domain(K)    : UNIQUE index, nulls not distinct        (PG: UNIQUE NULLS NOT DISTINCT; SQLite: coalesce)
partial(K),
certain(K)   : one filtered UNIQUE index per null pattern P of the nullable
               columns of K  (UNIQUE(K\\P) WHERE P IS NULL AND N_K\\P IS NOT NULL),
               plus triggers that probe these indexes with pure equalities.
Runs on SQLite (triggers dispatched on the null pattern of NEW) and emits the
equivalent PostgreSQL script (PL/pgSQL trigger) for every configuration.
"""
import sys, json, time, random, sqlite3, statistics, os, itertools
sys.path.insert(0, 'experiments/lib')
from keys import *
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = os.environ.get('ONECOVER_D_OUT', 'results/D_enforcement')
os.makedirs(OUT, exist_ok=True); os.makedirs(f'{OUT}/pg', exist_ok=True)
N, K = 8, 2
ROWS, UPDATES = 1500, 600
V, NULLP = 200, 0.05
NULL_ROW = 0.3
TRIALS = 5
MAXSIZE = 5
rng = random.Random(11)

def cname(i): return f'c{i}'
def cols(mask): return [cname(i) for i in range(N) if mask >> i & 1]
def subsets(lst):
    for r in range(len(lst) + 1):
        for c in itertools.combinations(lst, r):
            yield list(c)

def cover(frag, S, NN):
    if frag == 'F1': return mincover_fragment(S, NN, 'partial')
    if frag == 'F2': return mincover_fragment(S, NN, 'certain')
    return mincover_general(S, NN)

def random_keys_capped(n, k, m, frag):
    NN = (1 << k) - 1; classes = FRAGMENTS[frag]; keys = set()
    while len(keys) < m:
        size = min(MAXSIZE, 2 + sum(rng.random() < 0.3 for _ in range(n - 2)))
        mask = sum(1 << c for c in rng.sample(range(n), size))
        keys.add((rng.choice(classes), mask))
    return NN, sorted(keys)

# ------------------------------------------------------------- index DDL
def pattern_where(P, NK):
    terms = [f'{c} IS NULL' for c in P] + [f'{c} IS NOT NULL' for c in NK if c not in P]
    return ' AND '.join(terms) if terms else 'TRUE'

def index_ddl(i, cls, mask, NNmask, dialect):
    cs = cols(mask); X = cols(mask & NNmask); NK = cols(mask & ~NNmask)
    out = []
    if cls == 'possible':
        out.append(f"CREATE UNIQUE INDEX k{i} ON T({','.join(cs)})")
    elif cls == 'domain':
        if dialect == 'pg':
            out.append(f"CREATE UNIQUE INDEX k{i} ON T({','.join(cs)}) NULLS NOT DISTINCT")
        else:
            out.append(f"CREATE UNIQUE INDEX k{i} ON T({','.join(f'coalesce({c},-1)' for c in cs)})")
    else:
        for j, P in enumerate(subsets(NK)):
            keycols = X + [c for c in NK if c not in P]
            if keycols:
                out.append(f"CREATE UNIQUE INDEX k{i}_{j} ON T({','.join(keycols)}) WHERE {pattern_where(P, NK)}")
            else:  # pattern with all key columns null: at most one such row
                out.append(f"CREATE UNIQUE INDEX k{i}_{j} ON T((1)) WHERE {pattern_where(P, NK)}" if dialect == 'pg'
                           else f"CREATE UNIQUE INDEX k{i}_{j} ON T(1) WHERE {pattern_where(P, NK)}")
    return out

# --------------------------------------------------------- SQLite triggers
def sqlite_triggers(i, cls, mask, NNmask):
    """One trigger per null pattern P of NEW; its WHEN probes the filtered
    indexes of the comparable (partial) or all (certain) patterns P' with
    pure equalities on K \\ (P u P')."""
    X = cols(mask & NNmask); NK = cols(mask & ~NNmask); out = []
    for P in subsets(NK):
        newpat = ' AND '.join([f'NEW.{c} IS NULL' for c in P] + [f'NEW.{c} IS NOT NULL' for c in NK if c not in P]) or 'TRUE'
        probes = []
        for P2 in subsets(NK):
            if cls == 'partial' and not (set(P) <= set(P2) or set(P2) <= set(P)):
                continue
            eq = [f'{c}=NEW.{c}' for c in X] + [f'{c}=NEW.{c}' for c in NK if c not in P and c not in P2]
            probes.append('(' + ' AND '.join([pattern_where(P2, NK)] + eq) + ')')
        for ev in ('INSERT', 'UPDATE'):
            excl = ' AND rowid<>NEW.rowid' if ev == 'UPDATE' else ''
            exists = ' OR '.join(f'EXISTS(SELECT 1 FROM T WHERE {p}{excl})' for p in probes)
            out.append(f"CREATE TRIGGER t{i}_{len(out)} BEFORE {ev} ON T WHEN ({newpat}) AND ({exists}) "
                       f"BEGIN SELECT RAISE(ABORT,'{cls}'); END")
    return out

# ------------------------------------------------------- PostgreSQL script
def pg_script(keys, NNmask):
    lines = ['DROP TABLE IF EXISTS T CASCADE;',
             'CREATE TABLE T(' + ','.join(f'{cname(i)} INTEGER' + (' NOT NULL' if NNmask >> i & 1 else '') for i in range(N)) + ');']
    for i, (cls, mask) in enumerate(keys):
        lines += [s + ';' for s in index_ddl(i, cls, mask, NNmask, 'pg')]
        if cls in ('partial', 'certain'):
            X = cols(mask & NNmask); NK = cols(mask & ~NNmask)
            body = []
            for P in subsets(NK):   # branch on the null pattern of NEW
                newpat = ' AND '.join([f'NEW.{c} IS NULL' for c in P] + [f'NEW.{c} IS NOT NULL' for c in NK if c not in P]) or 'TRUE'
                probes = []
                for P2 in subsets(NK):
                    if cls == 'partial' and not (set(P) <= set(P2) or set(P2) <= set(P)):
                        continue
                    eq = [f'{c}=NEW.{c}' for c in X] + [f'{c}=NEW.{c}' for c in NK if c not in P and c not in P2]
                    probes.append('(' + ' AND '.join([pattern_where(P2, NK)] + eq) + ')')
                exists = ' OR '.join(f"EXISTS (SELECT 1 FROM T WHERE {p} AND (TG_OP = 'INSERT' OR ctid <> OLD.ctid))" for p in probes)
                body.append(f"  IF ({newpat}) AND ({exists}) THEN RAISE EXCEPTION '{cls} key k{i} violated'; END IF;")
            lines.append(f"CREATE FUNCTION chk_k{i}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN\n" + '\n'.join(body) + "\n  RETURN NEW; END $$;")
            lines.append(f"CREATE TRIGGER trg_k{i} BEFORE INSERT OR UPDATE ON T FOR EACH ROW EXECUTE FUNCTION chk_k{i}();")
    return '\n'.join(lines) + '\n'

# ------------------------------------------------------------------ run
def check_sql(cls, mask):
    cs = cols(mask)
    if cls == 'possible': cond = ' AND '.join(f'a.{c}=b.{c}' for c in cs)
    elif cls == 'domain': cond = ' AND '.join(f'a.{c} IS b.{c}' for c in cs)
    elif cls == 'certain': cond = ' AND '.join(f'(a.{c} IS NULL OR b.{c} IS NULL OR a.{c}=b.{c})' for c in cs)
    else: cond = '(' + ' AND '.join(f'(a.{c} IS NULL OR a.{c}=b.{c})' for c in cs) + ')'
    return f"SELECT 1 FROM T a, T b WHERE a.rowid<b.rowid AND {cond} LIMIT 1"

def make_db(keys, NNmask):
    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE T(' + ','.join(f'{cname(i)} INTEGER' + (' NOT NULL' if NNmask >> i & 1 else '') for i in range(N)) + ')')
    nidx = ntrg = 0
    for i, (cls, mask) in enumerate(keys):
        for s in index_ddl(i, cls, mask, NNmask, 'sqlite'): con.execute(s); nidx += 1
        if cls in ('partial', 'certain'):
            for s in sqlite_triggers(i, cls, mask, NNmask): con.execute(s); ntrg += 1
    return con, nidx, ntrg

def workload():
    rows = []
    for _ in range(ROWS):   # at most one null per row, in a random nullable column, with probability NULL_ROW
        r = [rng.randrange(V) for _ in range(N)]
        if rng.random() < NULL_ROW: r[rng.randrange(K, N)] = None
        rows.append(tuple(r))
    ups = [(rng.randrange(ROWS), rng.randrange(K, N), (None if rng.random() < NULLP else rng.randrange(V))) for _ in range(UPDATES)]
    return rows, ups

def run_db(keys, NNmask, rows, ups):
    con, nidx, ntrg = make_db(keys, NNmask)
    acc = 0; t0 = time.perf_counter()
    for r in rows:
        try: con.execute('INSERT INTO T VALUES(' + ','.join('?' * N) + ')', r); acc += 1
        except sqlite3.IntegrityError: pass
    t_ins = time.perf_counter() - t0
    ids = [x[0] for x in con.execute('SELECT rowid FROM T ORDER BY rowid')]
    t0 = time.perf_counter(); ok = 0
    for (j, c, v) in ups:
        try: con.execute(f'UPDATE T SET {cname(c)}=? WHERE rowid=?', (v, ids[j % len(ids)])); ok += 1
        except sqlite3.IntegrityError: pass
    t_upd = time.perf_counter() - t0
    state = sorted(con.execute('SELECT * FROM T').fetchall(), key=lambda x: tuple(-1 if v is None else v for v in x))
    t0 = time.perf_counter()
    for cls, mask in keys:
        assert con.execute(check_sql(cls, mask)).fetchone() is None, (cls, mask)
    t_chk = time.perf_counter() - t0
    con.close()
    return dict(accepted=acc, updated=ok, t_insert=t_ins, t_update=t_upd, t_check=t_chk, indexes=nidx, triggers=ntrg), state

if __name__ == '__main__':
    LOG = open(f'{OUT}/db2_log.jsonl', 'w'); results = []
    for frag in ['F1', 'F2', 'ALL']:
        for m in [10, 20, 40, 80, 120]:
            for t in range(TRIALS):
                NN, S = random_keys_capped(N, K, m, frag); G = cover(frag, S, NN)
                rows, ups = workload()
                rS, stS = run_db(S, NN, rows, ups); rG, stG = run_db(G, NN, rows, ups)
                assert stS == stG, 'cover and input accepted different data!'
                rec = dict(fragment=frag, m=m, trial=t, in_keys=len(S), in_occ=occ(S), out_keys=len(G), out_occ=occ(G),
                           sigma=rS, cover=rG, accepted_equal=True,
                           input=[f'{c}({fmt_mask(mk, N)})' for c, mk in S], output=[f'{c}({fmt_mask(mk, N)})' for c, mk in G])
                LOG.write(json.dumps(rec) + '\n'); results.append(rec)
                if t == 0:
                    open(f'{OUT}/pg/{frag}_m{m}_input.sql', 'w').write(pg_script(S, NN))
                    open(f'{OUT}/pg/{frag}_m{m}_cover.sql', 'w').write(pg_script(G, NN))
                print(frag, m, t, len(S), '->', len(G), 'idx %d/%d trg %d/%d' % (rS['indexes'], rG['indexes'], rS['triggers'], rG['triggers']),
                      'ins %.2f/%.2f upd %.2f/%.2f chk %.2f/%.2f' % (rS['t_insert'], rG['t_insert'], rS['t_update'], rG['t_update'], rS['t_check'], rG['t_check']),
                      'acc', rS['accepted'], flush=True)
    LOG.close(); json.dump(results, open(f'{OUT}/db2_results.json', 'w'))
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
    fig.suptitle(f"Experiment D': filtered-index enforcement, {N} columns, {ROWS} inserts, {UPDATES} updates (mean of {TRIALS} trials)")
    fig.tight_layout(); fig.savefig(f'{OUT}/expD2.pdf'); fig.savefig(f'{OUT}/expD2.png', dpi=110)
    print('done')
