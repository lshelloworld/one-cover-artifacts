import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""VOC: verify the mined keys on the data, then enforce mined keys vs cover in PostgreSQL."""
import sys, json, os, statistics, collections
sys.path.insert(0, 'experiments/lib')
import hockey_data as hd; hd.use('data/voc', 'voc')
from check_mined import holds
from exp_real_pg import run, DSN
from keys import mincover_general
import psycopg2
U = 'data/mined_keys'
FILES = {'possible': '1791953466091_voc-possible-orth1.txt', 'domain': '1791953466092_voc-domain-orth1.txt',
         'partial': '1791953466092_voc-partial-orth.txt', 'certain': '1791953466092_voc-certain-orth1.txt'}
T = collections.defaultdict(list)
for cls, f in FILES.items():
    for line in open(f'{U}/{f}', encoding='utf-8-sig'):
        line = line.strip()
        if line: t, cs = line.split('['); T[t.split('.')[1]].append((cls, tuple(cs.rstrip(']').split(','))))
OUT = os.environ.get('ONECOVER_VOC_OUT', 'results/E_real_tables/voc_pg.jsonl')
if __name__ == '__main__':
    # 1. do the mined keys hold?  (and the voyages triangle)
    ok = bad = 0; fails = []
    for t, keys in T.items():
        cols, rows, nn = hd.load(t); ci = {c: i for i, c in enumerate(cols)}
        for cls, K in keys:
            if holds(rows, [ci[c] for c in K], cls): ok += 1
            else: bad += 1; fails.append(f'{cls}({",".join(K)}) on {t}')
    print(f'mined keys holding: {ok}, failing: {bad}', fails[:10])
    cols, rows, nn = hd.load('voyages'); ci = {c: i for i, c in enumerate(cols)}
    for K in [('number', 'yard', 'arrival_date', 'next_voyage'), ('number', 'yard', 'next_voyage'), ('number', 'yard', 'arrival_date'), ('number', 'arrival_date', 'next_voyage')]:
        print('  voyages certain(' + ','.join(K) + ') holds:', holds(rows, [ci[c] for c in K], 'certain'))
    if '--check' in sys.argv: sys.exit()
    # 2. enforcement in PostgreSQL
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT): r = json.loads(l); done.add((r['table'], r['side']))
    con = psycopg2.connect(**DSN); out = open(OUT, 'a')
    for t in sorted(T, key=lambda x: len(T[x])):
        cols, rows, nn = hd.load(t); ci = {c: i for i, c in enumerate(cols)}
        S = [(c, sum(1 << ci[x] for x in K)) for c, K in T[t]]; NN = sum(1 << ci[c] for c in nn)
        G = mincover_general(S, NN); name = lambda m: tuple(c for c in cols if m >> ci[c] & 1)
        for side, keys in (('input', [(c, name(m)) for c, m in S]), ('cover', [(c, name(m)) for c, m in G])):
            if (t, side) in done: continue
            rs = [run(con, cols, rows, nn, keys) for _ in range(5)]
            rec = dict(table=t, side=side, keys=len(keys), **{k: rs[0][k] for k in ('indexes', 'triggers', 'index_bytes', 'rows')},
                       t_ddl=statistics.median(r['t_ddl'] for r in rs), t_insert=statistics.median(r['t_insert'] for r in rs),
                       t_insert_all=[r['t_insert'] for r in rs])
            assert rec['rows'] == len(rows)
            out.write(json.dumps(rec) + '\n'); out.flush()
            print(t, side, rec['keys'], 'keys', rec['indexes'], 'idx', rec['triggers'], 'trg', f"{rec['index_bytes']/2**20:.2f} MiB", f"ins {rec['t_insert']:.2f}s", flush=True)
    print('done')
