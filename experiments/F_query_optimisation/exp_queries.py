import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Measure the query rewrites licensed by the keys of the cover, on Hockey and VOC in PostgreSQL 16.
Each table is created with its profiled NOT NULL columns and the indexes of its cover (no triggers).
For every query: original vs rewritten form, identical results checked, plans and server-side
execution time (EXPLAIN ANALYZE, median of RUNS after one warm-up)."""
import sys, json, statistics, collections, io
sys.path.insert(0, 'experiments/lib')
import psycopg2
import hockey_data as hd
from keys import mincover_general
from exp_real_pg import ddl
from check_mined import read
RUNS = 9
DSN = __import__('config').DSN
q = lambda c: '"' + c + '"'

def voc_keys():
    U = 'data/mined_keys'
    F = {'possible': '1791953466091_voc-possible-orth1.txt', 'domain': '1791953466092_voc-domain-orth1.txt',
         'partial': '1791953466092_voc-partial-orth.txt', 'certain': '1791953466092_voc-certain-orth1.txt'}
    T = collections.defaultdict(list)
    for cls, f in F.items():
        for line in open(f'{U}/{f}', encoding='utf-8-sig'):
            line = line.strip()
            if line: t, cs = line.split('['); T[t.split('.')[1]].append((cls, tuple(cs.rstrip(']').split(','))))
    return T

def setup(cur, db, table, keysets, with_keys=True, tname=None):
    hd.use(*{'hockey': ('data/hockey', 'Hockey'), 'voc': ('data/voc', 'voc')}[db])
    cols, rows, nn = hd.load(table); ci = {c: i for i, c in enumerate(cols)}; tname = tname or table.lower()
    cur.execute(f'DROP TABLE IF EXISTS {tname} CASCADE')
    cur.execute(f'CREATE TABLE {tname} (' + ', '.join(f'{q(c)} bigint' + (' NOT NULL' if c in nn else '') for c in cols) + ')')
    buf = io.StringIO('\n'.join('\t'.join('\\N' if v is None else str(v) for v in r) for r in rows) + '\n')
    cur.copy_expert(f'COPY {tname} FROM STDIN', buf)
    n_idx = 0
    if with_keys:
        S = [(c, sum(1 << ci[x] for x in K)) for c, K in keysets[table]]; NN = sum(1 << ci[c] for c in nn)
        G = [(c, tuple(x for x in cols if m >> ci[x] & 1)) for c, m in mincover_general(S, NN)]
        for s in ddl(G, cols, nn)[0]:
            if s.startswith('CREATE UNIQUE INDEX'):
                cur.execute(s.replace(' ON t ', f' ON {tname} ').replace('CREATE UNIQUE INDEX k', f'CREATE UNIQUE INDEX {tname}_k')); n_idx += 1
    cur.execute(f'ANALYZE {tname}')
    return n_idx

def measure(cur, sql):
    P, E, plan = [], [], None
    cur.execute(sql); res = sorted(map(repr, cur.fetchall()))           # warm-up and result
    for _ in range(RUNS):
        cur.execute('EXPLAIN (ANALYZE, FORMAT JSON) ' + sql); p = cur.fetchone()[0][0]
        P.append(p['Planning Time']); E.append(p['Execution Time']); plan = plan or p['Plan']
    times = (statistics.median(P), statistics.median(E))
    def nodes(n): return [n['Node Type'] + (f" on {n.get('Relation Name')}" if 'Relation Name' in n else '') + (f" using {n['Index Name']}" if 'Index Name' in n else '')] + sum((nodes(c) for c in n.get('Plans', [])), [])
    return times, res, nodes(plan)

if __name__ == '__main__':
    con = psycopg2.connect(**DSN); con.autocommit = True; cur = con.cursor()
    H, V = read(1), voc_keys()
    for t in ['Master', 'Coaches']: setup(cur, 'hockey', t, H)
    for t in ['voyages', 'invoices', 'seafarers', 'soldiers', 'craftsmen']: setup(cur, 'voc', t, V)
    setup(cur, 'hockey', 'Master', H, with_keys=False, tname='master_nokeys')
    setup(cur, 'voc', 'voyages', V, with_keys=False, tname='voyages_nokeys')
    cur.execute('SELECT "playerID","coachID","hofID","firstName","lastName" FROM master'); _ = cur.fetchall()
    cur.execute('SELECT "number","yard","arrival_date","next_voyage" FROM voyages WHERE "number" IS NOT NULL AND "yard" IS NOT NULL AND "next_voyage" IS NOT NULL AND "arrival_date" IS NOT NULL LIMIT 1')
    n, y, a, v = cur.fetchone()
    cur.execute('SELECT "hofID" FROM master WHERE "playerID" IS NULL AND "coachID" IS NULL LIMIT 1'); hof = cur.fetchone()[0]
    cur.execute('SELECT "number","yard" FROM voyages WHERE "arrival_date" IS NULL AND "yard" IS NOT NULL LIMIT 1'); n6, y6 = cur.fetchone()
    Q = [
     ('Q1 join elimination (possible key, Hockey)', 'possible(coachID) on Master',
      'SELECT c.* FROM coaches c LEFT JOIN master m ON m."coachID" = c."coachID"',
      'SELECT c.* FROM coaches c LEFT JOIN master_nokeys m ON m."coachID" = c."coachID"', 'without the key'),
     ('Q2 join elimination (candidate key, VOC)', 'certain(number,trip) on soldiers, craftsmen',
      'SELECT s.* FROM seafarers s LEFT JOIN soldiers o USING ("number","trip") LEFT JOIN craftsmen c USING ("number","trip")',
      None, None),
     ('Q3 GROUP BY to projection (domain key, VOC)', 'domain(number,chamber) on invoices',
      'SELECT "number","chamber",SUM("invoice")::bigint FROM invoices GROUP BY "number","chamber"',
      'SELECT "number","chamber","invoice" FROM invoices', 'rewritten'),
     ('Q4 DISTINCT removal (domain key implied by partial key, Hockey)', 'domain(playerID,coachID,hofID) via R1',
      'SELECT DISTINCT "playerID","coachID","hofID","firstName","lastName" FROM master',
      'SELECT "playerID","coachID","hofID","firstName","lastName" FROM master', 'rewritten'),
     ('Q5 null-pattern lookup (partial key family, Hockey)', 'partial(playerID,coachID,hofID)',
      f'SELECT * FROM master WHERE "playerID" IS NULL AND "coachID" IS NULL AND "hofID" = {hof}',
      f'SELECT * FROM master_nokeys WHERE "playerID" IS NULL AND "coachID" IS NULL AND "hofID" = {hof}', 'without the key'),
     ('Q6 lost-ship lookup (partial key family, VOC)', 'partial(number,yard,arrival_date)',
      f'SELECT * FROM voyages WHERE "number" = {n6} AND "yard" = {y6} AND "arrival_date" IS NULL',
      f'SELECT * FROM voyages_nokeys WHERE "number" = {n6} AND "yard" = {y6} AND "arrival_date" IS NULL', 'without the key'),
     ('Q7 subsumption anti-join removal (partial key, VOC)', 'partial(number,yard,arrival_date)',
      'SELECT * FROM voyages v WHERE NOT EXISTS (SELECT 1 FROM voyages w WHERE w."artificial_id" <> v."artificial_id" AND w."number" = v."number" AND (v."yard" IS NULL OR v."yard" = w."yard") AND (v."arrival_date" IS NULL OR v."arrival_date" = w."arrival_date"))',
      'SELECT * FROM voyages', 'rewritten'),
     ('Q8 record linkage, all probes (certain key, VOC)', 'certain(number,yard,next_voyage)',
      'SELECT p."artificial_id", v."artificial_id" FROM voyages p JOIN voyages v ON v."number" = p."number" AND (v."yard" IS NULL OR v."yard" = p."yard") AND (v."next_voyage" IS NULL OR v."next_voyage" = p."next_voyage") WHERE p."yard" IS NOT NULL AND p."next_voyage" IS NOT NULL',
      'SELECT p."artificial_id", v."artificial_id" FROM voyages p CROSS JOIN LATERAL (SELECT w."artificial_id" FROM voyages w WHERE w."number" = p."number" AND (w."yard" IS NULL OR w."yard" = p."yard") AND (w."next_voyage" IS NULL OR w."next_voyage" = p."next_voyage") LIMIT 1) v WHERE p."yard" IS NOT NULL AND p."next_voyage" IS NOT NULL', 'rewritten (LIMIT 1)'),
    ]
    out = []
    for name, key, orig, alt, altlabel in Q:
        t0, r0, p0 = measure(cur, orig)
        rec = dict(query=name, key=key, orig_ms=t0, orig_rows=len(r0), orig_plan=p0)
        if alt:
            t1, r1, p1 = measure(cur, alt)
            same = (r0 == r1)
            rec.update(alt=altlabel, alt_ms=t1, alt_rows=len(r1), alt_plan=p1, same_result=same)
        out.append(rec)
        print(f"{name}\n   original : plan {t0[0]:7.2f} ms + exec {t0[1]:7.3f} ms  rows {len(r0):5d}  {p0[:3]}")
        if alt: print(f"   {altlabel[:9]:9s}: plan {rec['alt_ms'][0]:7.2f} ms + exec {rec['alt_ms'][1]:7.3f} ms  rows {rec['alt_rows']:5d}  {rec['alt_plan'][:3]}  same result: {rec['same_result']}")
    cur.execute("SELECT relname, pg_relation_size(oid) FROM pg_class WHERE relname IN ('master_k1_0','master_k1_1','master_k1_2','master_k1_3') OR relname LIKE 'master_k%' ORDER BY 1")
    sizes = cur.fetchall()
    json.dump(out, open('results/F_query_optimisation/queries.json', 'w'), indent=1)
    print('done')
