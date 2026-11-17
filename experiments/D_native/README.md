# Native enforcement of partial and certain keys (Experiment D, "Native enforcement")

`nbtnull` is a prototype index access method for PostgreSQL 18 that enforces one partial key
(mode `subsumed`) or certain key (mode `compatible`) in a single B-tree index, wrapping PostgreSQL's
B-tree. It serves only enforcement, not queries; create it on an empty table. Its design is described
separately; this directory holds what is needed to rebuild it and rerun the paper's measurements.

## Build and load

PostgreSQL 18 with PGXS (tested with 18.6 on macOS arm64):

```
cd experiments/D_native
make PG_CONFIG=/path/to/pg_config        # on macOS with the EDB build add PG_SYSROOT=$(xcrun --show-sdk-path)
cp nbtnull.dylib DIR/                    # nbtnull.so on Linux; any directory the server can read
psql -d DB -v libpath=DIR/nbtnull -f nbtnull.sql
```

`nbtnull_key_ddl(name, table, not_null_cols, nullable_cols, mode, depth)` returns the
`CREATE INDEX` statement for one key, for example

```
SELECT nbtnull_key_ddl('k', 't', ARRAY['x'], ARRAY['a','b'], 'compatible', 1);
```

Use a private cluster as for the other PostgreSQL experiments (top-level README).

## Tests

```
python experiments/D_native/test_correctness.py [statements] [seeds] [domain] [mode:nx:n]
python experiments/D_native/test_concurrency.py [transactions per thread] [x0 domain] [n domain]
```

`test_correctness.py` runs random inserts and updates for every mode, number of NOT NULL and
nullable columns, and shadow depth, and compares every accept/reject decision with a brute-force
oracle. `test_concurrency.py` checks that an insert waits on a conflicting in-progress insert and
fails or succeeds as that one commits or rolls back, runs 8 concurrent sessions and checks the
result for conflicting pairs, and, if `ONECOVER_PG_DATA` names the cluster's data directory, stops
the server with `-m immediate`, restarts it and checks the index (set `ONECOVER_PG_BIN` to its
`bin` directory). Both connect through `config.py`.

## Experiment

```
python experiments/D_native/exp_d_native.py 2      # about 1 hour
```

Experiment D's 75 configurations (1,500 inserts, 600 updates, the key sets and workloads of
`exp_db2_pg.py`), each run four times, interleaved: the emulation of Section 2 and the native index,
each on the input and on its cover. Possible and domain keys get the same `UNIQUE` indexes in both;
a partial or certain key gets one `nbtnull` index, shadow depth 0 if it has a NOT NULL column and 1
otherwise. All four runs must accept the same statements and end in the same table. Output:
`results/D_native/m2_expD.jsonl`, one line per configuration and repetition; `m2.log` is the
console log of the committed run.

## Cost per insert of one key (summarised in the appendix)

```
python experiments/D_native/bench_m1.py --rows 100000 --nx 0,1,2 --n 2,3,4 --nulls light,heavy \
    --schemes none,btree,unnd,today,nbt0,nbt1 --reps 3 --out results/D_native/m1_100k.jsonl
```

One key on a table with `nx` NOT NULL and `n` nullable key columns; rows inserted by a PL/pgSQL loop,
one subtransaction per row. Schemes: no index, plain B-tree, `UNIQUE NULLS NOT DISTINCT`, the
emulation (`today`), and the native index at depth 0, 1 (`nbt0`, `nbt1`; `nbt2` for depth 2).
Committed results: `m1_100k.jsonl` (ten configurations, 3 runs),
`m1_1m.jsonl` (10^6 rows, heavy nulls, n = 3) and `m1_depth2_100k.jsonl` (depth 1 against depth 2).

## Experiment E on the real tables

```
results/D_native/run_e_native.sh hockey voc
```

The mined keys of Hockey (levels 9 and 1) and VOC (level 1) and their covers, enforced on the real
tables as in `experiments/E_real_tables/` with the emulation and with the native index, the four runs
of a table interleaved. The script waits for a quiet machine before each table and repeats a table
that ends at a 5-minute load of 6 or more (`ONECOVER_MAXLOAD`). Hockey's TeamSplits, whose 3,708
plain `UNIQUE` indexes raise the load by themselves, was checked before its start only. Output:
`results/D_native/e_hockey_native.jsonl`, `e_voc_native.jsonl`; records set aside for high load are in
`superseded/*_highload.jsonl`, the console log in `e_native.log`.

## Experiment D at scale

```
results/D_native/run_dxl_native.sh
```

Runs `exp_dxl_native.py 30,40,50` for `ONECOVER_KEYSET` = 1, 2, 3: the 10^6-insert, 2*10^5-update
workload of `experiments/D_enforcement/exp_db2_pg_extra.py xl` on the same key sets, with the native
index for partial and certain keys. Input and cover must end in the same table; the accepted counts
also match the emulated runs in `results/D_enforcement/db2_pg_extra_ks*.jsonl`. Output:
`results/D_native/dxl_native_ks{1,2,3}.jsonl`, console log `dxl_native.log`. About 1.5 hours per key set.

## Concurrent inserts

```
python3 experiments/D_native/exp_concurrency.py --keyset 1 --m 40 --rows 30000 --clients 1,4,8 --cap 600
python3 experiments/D_native/exp_concurrency.py --keyset 2 --m 50 --rows 30000 --clients 1,4,8 --cap 600
```

(`results/D_native/run_concurrency2.sh` is the runner used for the reported results.) Key set 1
at 40 keys and key set 2 at 50 keys, 3*10^4 rows, 1, 4 and 8 client sessions, and four schemes: the native index (READ COMMITTED), the emulation behind a table
lock, the emulation under SERIALIZABLE with up to 50 retries per row, and the emulation under READ
COMMITTED without a lock. The final table of each run is reloaded into a table enforced by the native
index for the input keys; every rejected row counts as a violation. Output:
`results/D_native/concurrency.jsonl`, console log `concurrency.log`. About 1.5 hours (30 minutes for key set 1, an hour for key set 2).
