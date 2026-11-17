import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Query batch 3 (VOC voyages): (1) planning cost of the two self-joins Q7 and Q8 without indexes,
with the cover's indexes and with the indexes of all mined keys; (2) the row estimate of the record
linkage join Q8 with and without the keys; (3) the next-voyage left join of batch 2, reading only the
voyage, which PostgreSQL removes only given a plain UNIQUE index on (number, boatname)."""
import sys, json
sys.path.insert(0, 'experiments/lib')
import psycopg2
import hockey_data as hd
import exp_queries
from exp_queries import setup, voc_keys, measure, outfile, DSN, q
from exp_real_pg import ddl

Q7 = ('SELECT * FROM {t} v WHERE NOT EXISTS (SELECT 1 FROM {t} w WHERE w."artificial_id" <> v."artificial_id" AND w."number" = v."number" '
      'AND (v."yard" IS NULL OR v."yard" = w."yard") AND (v."arrival_date" IS NULL OR v."arrival_date" = w."arrival_date"))')
Q8 = ('SELECT p."artificial_id", v."artificial_id" FROM {t} p JOIN {t} v ON v."number" = p."number" AND (v."yard" IS NULL OR v."yard" = p."yard") '
      'AND (v."next_voyage" IS NULL OR v."next_voyage" = p."next_voyage") WHERE p."yard" IS NOT NULL AND p."next_voyage" IS NOT NULL')
NEXT = 'SELECT v.* FROM {t} v LEFT JOIN {t} w ON w."number" = v."next_voyage" AND w."boatname" = v."boatname"'

def all_keys(cur, V, tname):
    """Add the unique indexes of every mined key of voyages (not only the cover's) to table tname."""
    hd.use('data/voc', 'voc'); cols, _, nn = hd.load('voyages')
    n = 0
    for s in ddl(V['voyages'], cols, nn)[0]:
        if s.startswith('CREATE UNIQUE INDEX'):
            cur.execute(s.replace(' ON t ', f' ON {tname} ').replace('CREATE UNIQUE INDEX k', f'CREATE UNIQUE INDEX {tname}_k')); n += 1
    cur.execute(f'ANALYZE {tname}')
    return n

if __name__ == '__main__':
    if len(sys.argv) > 1: exp_queries.SCALE = int(sys.argv[1])
    con = psycopg2.connect(**DSN); con.autocommit = True; cur = con.cursor()
    V = voc_keys(); out = {}
    n_cover = setup(cur, 'voc', 'voyages', V)
    setup(cur, 'voc', 'voyages', V, with_keys=False, tname='voyages_nokeys')
    setup(cur, 'voc', 'voyages', V, with_keys=False, tname='voyages_all')
    n_all = all_keys(cur, V, 'voyages_all')

    print(f'P planning cost of the self-joins: no indexes / cover ({n_cover}) / all mined keys ({n_all})')
    for name, sql in [('Q7', Q7), ('Q8', Q8)]:
        r = {}
        for label, t in [('none', 'voyages_nokeys'), ('cover', 'voyages'), ('all', 'voyages_all')]:
            tm, res, plan = measure(cur, sql.format(t=t))
            cur.execute('EXPLAIN (FORMAT JSON) ' + sql.format(t=t)); est = cur.fetchone()[0][0]['Plan']['Plan Rows']
            r[label] = dict(plan_ms=tm[0], exec_ms=tm[1], rows=len(res), est=est)
            print(f'   {name} {label:6s} plan {tm[0]:8.2f} ms + exec {tm[1]:8.3f} ms  rows {len(res):6d}  estimated {est}')
        out[name] = dict(r, n_cover=n_cover, n_all=n_all)

    print('U next voyage: cover, cover plus a plain UNIQUE (number, boatname), no keys')
    r = {}
    for label, t in [('cover', 'voyages'), ('cover + UNIQUE', 'voyages'), ('without the key', 'voyages_nokeys')]:
        if label == 'cover + UNIQUE':
            cur.execute('CREATE UNIQUE INDEX voyages_nb ON voyages ("number","boatname")'); cur.execute('ANALYZE voyages')
        tm, res, plan = measure(cur, NEXT.format(t=t))
        r[label] = dict(plan_ms=tm[0], exec_ms=tm[1], rows=len(res), plan=plan)
        print(f'   {label:16s} plan {tm[0]:7.2f} ms + exec {tm[1]:7.3f} ms  rows {len(res):6d}  {plan[:4]}')
    out['next voyage'] = r
    json.dump(out, open(outfile('queries3'), 'w'), indent=1)
    print('done')
