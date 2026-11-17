import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement')]
_os.chdir(_ROOT)
"""Experiment D at scale with the native index: exp_db2_pg_extra.py xl (10^6 inserts, 2*10^5 updates,
autocommit, synchronous_commit off, index on rid) with the native scheme in place of the emulation:
UNIQUE (possible), UNIQUE NULLS NOT DISTINCT (domain), one nbtnull index per partial or certain key
(shadow depth 0 if the key has a NOT NULL column, else 1). Input and cover run one after the other, as in
the emulated runs, and must end in the same table. The key set is chosen by ONECOVER_KEYSET as there.
Usage: ONECOVER_KEYSET=k exp_dxl_native.py 30,40,50
Output: results/D_native/dxl_native_ks<k>.jsonl (resumable by size)."""
import sys, json, random
import psycopg2
import exp_db2_pg_extra as X

def native_indexed(cur, keys, NN):
    cur.execute('DROP TABLE IF EXISTS T CASCADE'); cur.execute(X.table_ddl(NN)); n = 0
    for i, (cls, mask) in enumerate(keys):
        Xc = X.cols(mask & NN); NK = X.cols(mask & ~NN)
        if cls in ('possible', 'domain') or not NK:
            for s in X.index_ddl(i, 'possible' if cls in ('partial', 'certain') else cls, mask, NN): cur.execute(s)
        else:
            cur.execute('SELECT nbtnull_key_ddl(%s, %s, %s, %s, %s, %s)',
                        (f'k{i}', 't', Xc or None, NK, 'subsumed' if cls == 'partial' else 'compatible', 0 if Xc else 1))
            cur.execute(cur.fetchone()[0])
        n += 1
    return n

X.make_indexed = native_indexed

if __name__ == '__main__':
    os = _os
    ms = [int(x) for x in sys.argv[1].split(',')] if len(sys.argv) > 1 else [30, 40, 50]
    OUT = f'results/D_native/dxl_native_ks{X.KEYSET}.jsonl'
    done = {json.loads(l)['m'] for l in open(OUT)} if os.path.exists(OUT) else set()
    con = psycopg2.connect(**dict(X.DSN, gssencmode='disable')); con.autocommit = True
    con.cursor().execute('SET synchronous_commit = off')
    out = open(OUT, 'a')
    for m in ms:
        if m in done: continue
        S, G, NN = X.keyset(m); rows, ups = X.workload(random.Random(11), 1000000, 200000, 32000)
        rS, stS = X.run(con, S, NN, rows, ups, 'indexed', True); rG, stG = X.run(con, G, NN, rows, ups, 'indexed', True)
        assert stS == stG, (m, 'input and cover ended in different tables')
        rec = dict(exp='xl_native', m=m, keyset=X.KEYSET, rid_index=True, in_keys=len(S), out_keys=len(G), sigma=rS, cover=rG,
                   load=os.getloadavg())
        out.write(json.dumps(rec) + '\n'); out.flush()
        print('xl_native ks%d m=%d keys %d/%d idx %d/%d ins %.1f/%.1f upd %.1f/%.1f acc %d upd %d' % (
            X.KEYSET, m, len(S), len(G), rS['objects'], rG['objects'], rS['t_insert'], rG['t_insert'], rS['t_update'], rG['t_update'],
            rS['accepted'], rS['updated']), flush=True)
    print('done')
