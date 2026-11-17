import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment D on MySQL (8.0.13 or later): the index scheme of Section 2, large-table run.

Port of exp_db2_pg_extra.py (modes 'large' and 'xl', same key sets and workloads).
MySQL has neither filtered indexes nor NULLS NOT DISTINCT, so:
  * domain(K)        : UNIQUE functional index on COALESCE(c,-1) for the nullable columns
                       (values are >= 0), as in the SQLite run
  * partial/certain  : the filtered index of pattern P is a UNIQUE functional index on
                       IF(pattern, c, NULL) per column; outside P every part is NULL, and
                       NULLs are distinct, so only rows of pattern P are compared
                       (IF(pattern, 1, NULL) when the index has no key columns)
  * triggers         : MySQL has no INSERT OR UPDATE trigger: two per key (BEFORE INSERT,
                       BEFORE UPDATE) with the same pattern branches; the probes compare the
                       same IF(...) expressions so that they can use the functional indexes
  * row identity     : rid is AUTO_INCREMENT PRIMARY KEY (InnoDB clusters on it), so unlike
                       PostgreSQL the updates find their row through an index
  * durability       : innodb_flush_log_at_trx_commit=2 during the run (the counterpart of
                       synchronous_commit=off); the previous value is restored at the end
InnoDB allows at most 64 indexes per table, which the filtered scheme exceeds for most
key sets with |Sigma| >= 20.  The scheme 'perkey' therefore creates one index per key:
  * possible/domain  : the unique index above
  * partial/certain  : one non-unique index on K (NOT NULL columns first); the triggers
                       probe every pattern P' (the same pattern P included), with plain
                       equality and IS [NOT] NULL conditions, so uniqueness within a
                       pattern is checked by the trigger instead of a filtered index
Every statement runs in autocommit; a rejected statement raises an IntegrityError
(duplicate key) or a SIGNAL from a trigger.  Input and cover must end in the same state,
and the accepted/updated counts are compared with the PostgreSQL run of the same size.
"""
import sys, os, json, time, random, hashlib
import mysql.connector
from exp_db2_pg import N, K, cname, cols, subsets, pattern_where
from exp_db2_pg_extra import keyset, workload, KEYSET
MYSQL = __import__('config').MYSQL

OUTF = os.environ.get('ONECOVER_MYSQL_OUT', 'results/D_enforcement/db2_mysql_extra.jsonl')
PGF = os.environ.get('ONECOVER_XL_OUT', 'results/D_enforcement/db2_pg_extra.jsonl')
SIZES = {'large': ([10, 20], 100000, 20000, 10000), 'xl': ([10, 20, 30, 40, 50], 1000000, 200000, 32000),
         'small': ([10, 20, 30, 40, 50], 1500, 600, 200),   # small: validation only, not logged
         'test': ([10, 20], 1500, 600, 200)}                # test: small sizes, logged, to test the checkpoints

def save(f, rec):
    """Append one record and force it to disk, so that it survives a power cut or reboot."""
    f.write(json.dumps(rec) + '\n'); f.flush(); os.fsync(f.fileno())

def iff(pat, c): return f'IF({pat}, {c}, NULL)'

def table_ddl(NNmask):
    return ('CREATE TABLE T(rid INT AUTO_INCREMENT PRIMARY KEY, ' +
            ','.join(f'{cname(i)} INT' + (' NOT NULL' if NNmask >> i & 1 else '') for i in range(N)) + ') ENGINE=InnoDB')

def index_ddl(i, cls, mask, NNmask, scheme='filtered'):
    cs = cols(mask); X = cols(mask & NNmask); NK = cols(mask & ~NNmask)
    if cls == 'possible':
        return [f"CREATE UNIQUE INDEX k{i} ON T({','.join(cs)})"]
    if cls == 'domain':
        return [f"CREATE UNIQUE INDEX k{i} ON T({','.join(X + [f'(COALESCE({c},-1))' for c in NK])})"]
    if scheme == 'perkey':
        return [f"CREATE INDEX k{i} ON T({','.join(X + NK)})"]
    out = []
    for j, P in enumerate(subsets(NK)):
        pat = pattern_where(P, NK); keycols = X + [c for c in NK if c not in P]
        parts = [f'({iff(pat, c)})' for c in keycols] or [f'({iff(pat, 1)})']
        out.append(f"CREATE UNIQUE INDEX k{i}_{j} ON T({','.join(parts)})")
    return out

def trigger_ddl(i, cls, mask, NNmask, scheme='filtered'):
    X = cols(mask & NNmask); NK = cols(mask & ~NNmask); out = []
    for ev in ('INSERT', 'UPDATE'):
        body = []
        for P in subsets(NK):
            newpat = ' AND '.join([f'NEW.{c} IS NULL' for c in P] + [f'NEW.{c} IS NOT NULL' for c in NK if c not in P]) or 'TRUE'
            probes = []
            for P2 in subsets(NK):
                if cls == 'partial' and not (set(P) <= set(P2) or set(P2) <= set(P)):
                    continue
                pat2 = pattern_where(P2, NK); eqcols = X + [c for c in NK if c not in P and c not in P2]
                if scheme == 'perkey':
                    cond = [pat2] + [f'{c} = NEW.{c}' for c in eqcols]
                else:
                    cond = [f'{iff(pat2, c)} = NEW.{c}' for c in eqcols] or [f'{iff(pat2, 1)} = 1']
                probes.append(' AND '.join(cond) + (' AND rid <> OLD.rid' if ev == 'UPDATE' else ''))
            exists = ' OR '.join(f'EXISTS (SELECT 1 FROM T WHERE {p})' for p in probes)
            body.append(f"  IF ({newpat}) AND ({exists}) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '{cls} key k{i} violated'; END IF;")
        out.append(f"CREATE TRIGGER trg_k{i}_{ev[0].lower()} BEFORE {ev} ON T FOR EACH ROW BEGIN\n" + '\n'.join(body) + '\nEND')
    return out

def make_indexed(cur, keys, NN, scheme):
    cur.execute('DROP TABLE IF EXISTS T'); cur.execute(table_ddl(NN)); n = 0
    for i, (cls, K_) in enumerate(keys):
        for s in index_ddl(i, cls, K_, NN, scheme): cur.execute(s); n += 1
        if cls in ('partial', 'certain'):
            for s in trigger_ddl(i, cls, K_, NN, scheme): cur.execute(s)
    return n

def guarded(cur, sql, params):
    try:
        cur.execute(sql, params); return True
    except mysql.connector.IntegrityError:
        return False
    except mysql.connector.DatabaseError as e:
        if e.sqlstate == '45000': return False
        raise

def run(con, keys, NN, rows, ups, scheme='perkey'):
    cur = con.cursor(); t0 = time.perf_counter()
    nobj = make_indexed(cur, keys, NN, scheme); t_ddl = time.perf_counter() - t0
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
    return dict(objects=nobj, accepted=acc, updated=ok, t_ddl=t_ddl, t_insert=t_ins, t_update=t_upd, t_check=0.0), state

if __name__ == '__main__':
    # usage: exp_db2_mysql.py [large|xl|small] [perkey|filtered] [m,m,...]
    which = sys.argv[1] if len(sys.argv) > 1 else 'xl'
    scheme = sys.argv[2] if len(sys.argv) > 2 else 'perkey'
    ms, ROWS_, UPD_, V_ = SIZES[which]
    if len(sys.argv) > 3: ms = [int(x) for x in sys.argv[3].split(',')]
    con = mysql.connector.connect(**MYSQL); con.autocommit = True; cur = con.cursor()
    cur.execute('SELECT @@GLOBAL.innodb_flush_log_at_trx_commit'); flush0 = cur.fetchone()[0]
    cur.execute('SET GLOBAL innodb_flush_log_at_trx_commit = 2')
    pg = {(r['exp'], r['m']): r for r in map(json.loads, open(PGF))} if os.path.exists(PGF) else {}
    done = {(r['exp'], r['scheme'], r['m']) for r in map(json.loads, open(OUTF))} if os.path.exists(OUTF) else set()
    out = open(OUTF, 'a') if which != 'small' else None
    # checkpoint per side (input, cover): a restart redoes only a side that had not finished
    part = {(r['exp'], r['scheme'], r['m'], r['side']): r for r in map(json.loads, open(OUTF + '.partial'))} if os.path.exists(OUTF + '.partial') else {}
    pout = open(OUTF + '.partial', 'a') if out else None
    def side(name, keys, m, NN, rows, ups):
        if (which, scheme, m, name) in part:
            print(which, scheme, m, name, 'taken from the checkpoint', flush=True)
            c = part[(which, scheme, m, name)]; return c['result'], c['state_sha256']
        r, st = run(con, keys, NN, rows, ups, scheme); h = hashlib.sha256(json.dumps(st).encode()).hexdigest()
        if pout: save(pout, dict(exp=which, scheme=scheme, m=m, side=name, keyset=KEYSET, result=r, state_sha256=h, finished=time.strftime('%F %T')))
        print(which, scheme, m, name, 'finished', time.strftime('%F %T'), flush=True)
        return r, h
    try:
        for m in ms:
            if (which, scheme, m) in done: continue
            S, G, NN = keyset(m); rows, ups = workload(random.Random(11), ROWS_, UPD_, V_)
            rS, stS = side('sigma', S, m, NN, rows, ups); rG, stG = side('cover', G, m, NN, rows, ups)
            assert stS == stG, 'cover and input accepted different data!'
            p = pg.get((which, m))
            same = None if p is None else (rS['accepted'], rS['updated']) == (p['sigma']['accepted'], p['sigma']['updated'])
            rec = dict(exp=which, scheme=scheme, m=m, keyset=KEYSET, in_keys=len(S), out_keys=len(G), sigma=rS, cover=rG, same_as_pg=same)
            if out: save(out, rec)
            print(which, scheme, m, 'idx %d/%d ins %.1f/%.1f upd %.1f/%.1f acc %d upd %d' % (rS['objects'], rG['objects'], rS['t_insert'], rG['t_insert'], rS['t_update'], rG['t_update'], rS['accepted'], rS['updated']),
                  {None: 'no-pg-run', True: 'pg-match', False: 'PG-MISMATCH'}[same], flush=True)
    finally:
        cur.execute(f'SET GLOBAL innodb_flush_log_at_trx_commit = {flush0}')
    print('done')
