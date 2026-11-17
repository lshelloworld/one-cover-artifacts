import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Query batch 2: (1) idempotent reload with ON CONFLICT, (2) a ship's next voyage,
(3) eager aggregation over Goalies |><| Master, (4) GROUP BY on a primary key promoted from the cover."""
import sys, json, statistics
sys.path.insert(0, 'experiments/lib')
import psycopg2
import exp_queries
from exp_queries import setup, voc_keys, measure, outfile, DSN
from check_mined import read

def show(label, t, rows, plan):
    print(f'   {label:28s} plan {t[0]:7.2f} ms + exec {t[1]:7.3f} ms  rows {rows:5d}  {plan[:4]}')

if __name__ == '__main__':
    if len(sys.argv) > 1: exp_queries.SCALE = int(sys.argv[1])   # copies of every table, as in exp_queries.py
    con = psycopg2.connect(**DSN); con.autocommit = True; cur = con.cursor()
    H, V = read(1), voc_keys(); out = {}
    for t in ['Master', 'Goalies', 'Teams']: setup(cur, 'hockey', t, H)
    for t in ['voyages', 'invoices']: setup(cur, 'voc', t, V)
    setup(cur, 'voc', 'voyages', V, with_keys=False, tname='voyages_nokeys')

    # (1) idempotent reload
    print('R1 idempotent reload of invoices: INSERT ... ON CONFLICT (number, chamber) DO NOTHING')
    cur.execute('SELECT count(*) FROM invoices'); src = cur.fetchone()[0]
    for label, opt in [('UNIQUE (SQL default)', ''), ('domain key: NULLS NOT DISTINCT', 'NULLS NOT DISTINCT')]:
        cur.execute('DROP TABLE IF EXISTS inv2'); cur.execute('CREATE TABLE inv2 AS SELECT * FROM invoices')
        cur.execute(f'CREATE UNIQUE INDEX inv2_k ON inv2 ("number","chamber") {opt}')
        ts = []
        for _ in range(9):
            cur.execute('BEGIN'); t = __import__('time').perf_counter()
            cur.execute('INSERT INTO inv2 SELECT * FROM invoices ON CONFLICT ("number","chamber") DO NOTHING')
            ts.append((__import__('time').perf_counter() - t) * 1000); n = cur.rowcount; cur.execute('ROLLBACK')
        cur.execute('INSERT INTO inv2 SELECT * FROM invoices ON CONFLICT ("number","chamber") DO NOTHING')
        cur.execute('SELECT count(*) FROM inv2'); total = cur.fetchone()[0]
        out[f'reload {label}'] = dict(inserted=n, total=total, ms=statistics.median(ts))
        print(f'   {label:32s} rows inserted by the reload: {n}   table afterwards: {total} (source {src})   {statistics.median(ts):.2f} ms')

    # (2) a ship's next voyage
    print("R2 a ship's next voyage: voyages LEFT JOIN voyages ON (number, boatname) = (next_voyage, boatname)")
    sql = '''SELECT v."boatname", v."departure_date", w."departure_date" AS next_departure
             FROM {t} v LEFT JOIN {t} w ON w."number" = v."next_voyage" AND w."boatname" = v."boatname"'''
    for label, t in [('cover indexes', 'voyages'), ('without the key', 'voyages_nokeys')]:
        tm, res, plan = measure(cur, sql.format(t=t))
        cur.execute('EXPLAIN (FORMAT JSON) ' + sql.format(t=t)); p = cur.fetchone()[0][0]['Plan']
        out[f'next voyage {label}'] = dict(plan_ms=tm[0], exec_ms=tm[1], rows=len(res), est=p['Plan Rows'], inner_unique=p.get('Inner Unique'))
        show(label, tm, len(res), plan); print(f'      estimated rows {p["Plan Rows"]}, inner unique: {p.get("Inner Unique")}')
    print('      same result:', measure(cur, sql.format(t='voyages'))[1] == measure(cur, sql.format(t='voyages_nokeys'))[1])

    # (3) eager aggregation
    print('R3 goals against per goalie and season, with names')
    orig = '''SELECT g."playerID", g."year", m."firstName", m."lastName", SUM(g."GA")
              FROM goalies g JOIN master m ON m."playerID" = g."playerID"
              GROUP BY g."playerID", g."year", m."firstName", m."lastName"'''
    eager = '''SELECT g."playerID", g."year", m."firstName", m."lastName", g.s
               FROM (SELECT "playerID", "year", SUM("GA") AS s FROM goalies GROUP BY "playerID", "year") g
               JOIN master m ON m."playerID" = g."playerID"'''
    t0, r0, p0 = measure(cur, orig); t1, r1, p1 = measure(cur, eager)
    show('original', t0, len(r0), p0); show('aggregate before the join', t1, len(r1), p1); print('      same result:', r0 == r1)
    out['eager'] = dict(orig=t0, eager=t1, rows=len(r0), same=r0 == r1)

    # (4) GROUP BY on a primary key promoted from the cover
    print('R4 team totals: GROUP BY t.year, t.tmID while selecting t.name')
    q4 = '''SELECT t."year", t."tmID", t."name", SUM(g."GA") FROM teams t
            JOIN goalies g ON g."year" = t."year" AND g."tmID" = t."tmID" GROUP BY t."year", t."tmID"'''
    q4full = q4.replace('GROUP BY t."year", t."tmID"', 'GROUP BY t."year", t."tmID", t."name"')
    try:
        cur.execute(q4); print('   with UNIQUE only: accepted (unexpected)')
    except psycopg2.Error as e:
        print('   with UNIQUE only: rejected --', str(e).splitlines()[0])
    cur.execute('ALTER TABLE teams ADD PRIMARY KEY ("year", "tmID")')
    ta, ra, pa = measure(cur, q4); tb, rb, pb = measure(cur, q4full)
    show('PRIMARY KEY, GROUP BY key', ta, len(ra), pa); show('GROUP BY key and name', tb, len(rb), pb); print('      same result:', ra == rb)
    out['pk'] = dict(pk=ta, full=tb, rows=len(ra), same=ra == rb)
    json.dump(out, open(outfile('queries2'), 'w'), indent=1, default=str)
    print('done')
