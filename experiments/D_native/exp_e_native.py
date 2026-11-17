import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment E (enforcing mined keys on the real tables) with the native index.

For each table of Hockey (mining levels 9 and 1) or VOC (level 1), as in exp_real_pg.py and exp_voc.py:
create the table with its profiled NOT NULL columns, enforce the mined keys (input) or their cover, and
insert the table's own rows (one transaction, batches of 200). Two schemes, each on input and cover:
  emulation  exp_real_pg.py's: UNIQUE (possible), UNIQUE NULLS NOT DISTINCT (domain), filtered unique
             indexes per null pattern + one PL/pgSQL trigger per partial or certain key
  native     the same for possible and domain keys; one nbtnull index per partial or certain key
             (shadow depth 0 if the key has a NOT NULL column, else 1); a partial or certain key without
             nullable columns gets a plain UNIQUE index in both schemes
The four runs of a table are interleaved, in alternating order per repetition; every run must accept
every row. Reports indexes, triggers, index size and insert time (median over the repetitions).
The database (config.py) must have the extension loaded (experiments/D_native/README.md).
Usage: exp_e_native.py hockey|voc   Output: results/D_native/e_<data>_native.jsonl (resumable by table)."""
import sys, json, statistics, os, collections, time
import psycopg2
from keys import mincover_general
import exp_real_pg as R

DATA = sys.argv[1] if len(sys.argv) > 1 else 'hockey'
MAXLOAD = float(os.environ.get('ONECOVER_MAXLOAD', '0'))     # if set: wait for a 5-minute load below it
                                                              # before each table, and redo a table that ends above it
def quiet():
    while MAXLOAD and os.getloadavg()[1] >= MAXLOAD: time.sleep(60)
OUT = f'results/D_native/e_{DATA}_native.jsonl'
q = R.q
emulation_ddl = R.ddl

def native_ddl(keys, cols, nn):
    st, ni, nt = [], 0, 0
    rest = []
    for i, (cls, K) in enumerate(keys):
        X = [c for c in K if c in nn]; NK = [c for c in K if c not in nn]
        if cls in ('partial', 'certain') and NK:
            xs = ''.join(q(c) + ', ' for c in X); ns = ', '.join(map(q, NK))
            st.append(f'CREATE INDEX k{i} ON t USING nbtnull ({xs}(onecover_nullpat({ns})), (onecover_nullpat({ns})), {ns}) '
                      f"WITH (nx = {len(X)}, mode = '{'subsumed' if cls == 'partial' else 'compatible'}', shadow_depth = {0 if X else 1})")
            ni += 1
        else:
            rest.append((i, cls, K))
    for i, cls, K in rest:                     # possible and domain keys, and keys without nullable columns
        s, n, _ = emulation_ddl([(cls, K)], cols, nn)
        st += [x.replace('INDEX k0 ', f'INDEX k{i} ') for x in s]; ni += n
    return st, ni, nt

def run(con, scheme, cols, rows, nn, keys):
    R.ddl = native_ddl if scheme == 'native' else emulation_ddl
    try: return R.run(con, cols, rows, nn, keys)
    finally: R.ddl = emulation_ddl

def tables_hockey():
    from hockey_data import load, tables
    from check_mined import read
    full = set(tables())
    for level in [9, 1]:
        T = read(level)
        for tname in sorted(T, key=lambda x: len(T[x])):
            if tname in full: yield level, tname, load(tname), T[tname]

def tables_voc():
    import exp_voc as V                    # switches hockey_data to the VOC export and reads the mined keys
    for t in sorted(V.T, key=lambda x: len(V.T[x])):
        yield 1, t, V.hd.load(t), V.T[t]

if __name__ == '__main__':
    os.makedirs('results/D_native', exist_ok=True)
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT): r = json.loads(l); done.add((r['level'], r['table']))
    con = psycopg2.connect(**dict(__import__('config').DSN, gssencmode='disable'))
    out = open(OUT, 'a')
    order = [('emulation', 'input'), ('emulation', 'cover'), ('native', 'input'), ('native', 'cover')]
    for level, tname, (cols, rows, nn), mined in (tables_hockey() if DATA == 'hockey' else tables_voc()):
        if (level, tname) in done: continue
        ci = {c: i for i, c in enumerate(cols)}
        S = [(cls, sum(1 << ci[c] for c in K)) for cls, K in mined]
        G = mincover_general(S, sum(1 << ci[c] for c in nn))
        name = lambda m: tuple(c for c in cols if m >> ci[c] & 1)
        sides = {'input': [(c, name(m)) for c, m in S], 'cover': [(c, name(m)) for c, m in G]}
        reps = 5 if DATA == 'voc' else (1 if len(S) > 500 else 3)
        while True:
          quiet(); res = collections.defaultdict(list)
          for rep in range(reps):
            for scheme, side in (order if rep % 2 == 0 else order[::-1]):
                r = run(con, scheme, cols, rows, nn, sides[side])
                assert r['rows'] == len(rows), (tname, scheme, side, 'a row was rejected')
                res[(scheme, side)].append(r)
          if not MAXLOAD or os.getloadavg()[1] < MAXLOAD: break
          print(f'L{level} {tname}: load {os.getloadavg()[1]:.1f} at the end, repeating', flush=True)
        rec = dict(level=level, table=tname, rows=len(rows), keys_input=len(S), keys_cover=len(G), reps=reps, runs={})
        for (scheme, side), rs in res.items():
            rec['runs'][f'{scheme}_{side}'] = dict({k: rs[0][k] for k in ('indexes', 'pg_indexes', 'triggers', 'index_bytes')},
                                                   t_ddl=statistics.median(x['t_ddl'] for x in rs),
                                                   t_insert=statistics.median(x['t_insert'] for x in rs),
                                                   t_insert_all=[x['t_insert'] for x in rs])
        rec['load'] = os.getloadavg()
        out.write(json.dumps(rec) + '\n'); out.flush()
        t = lambda k: rec['runs'][k]['t_insert']; x = lambda k: rec['runs'][k]['indexes']
        print(f"L{level} {tname:17} keys {len(S)}/{len(G)}  emulation {t('emulation_input'):6.2f}/{t('emulation_cover'):6.2f}s "
              f"idx {x('emulation_input')}/{x('emulation_cover')}  native {t('native_input'):6.2f}/{t('native_cover'):6.2f}s "
              f"idx {x('native_input')}/{x('native_cover')}", flush=True)
    print('done')
