# Raw results

One directory per experiment; every file is the raw output of a script in `experiments/`, as JSON
(one object) or JSONL (one line per measurement). The file without a suffix is the run reported in
the paper; `_rerun` and `_rerun2` are confirmation reruns of the same script; `_x10` and `_x100`
are the tables replicated 10 and 100 times. `superseded/` in each directory holds runs that the
paper does not use: runs on the shared PostgreSQL server before the private cluster
(`before_clean_run/`), runs on PostgreSQL 16 (`pg16/`), runs with a limit of 256 open files
(`pg18_fdlimit256/`, see the top-level README), runs on a busy machine (`*_under_load`,
`*_highload`, `*_pg18_loaded`, `xl_shared_machine`), interim snapshots and smoke tests, and the
covers of an earlier version of the cover algorithm (`old_algorithm/`).

| Directory | Contents |
|---|---|
| `A-C_random_covers/` | `covers_log.jsonl`: every random input and its cover (Experiments A-C); `alg2_stress.jsonl`: the colouring test at the 2-colourability threshold |
| `D_enforcement/` | `db2_log.jsonl` (SQLite), `db2_pg_log.jsonl` (PostgreSQL) and `db2_pg_results.json`: Experiment D; `pg/`: the generated schemas; `naive_clean.jsonl`: no indexes, one trigger per key; `db2_pg_extra*.jsonl`: the 100k- and 10^6-row runs (`_ks1`-`_ks3`: the key sets at 10^6 rows, `_run2`: their second runs); `db2_mysql*.jsonl`: MySQL; `tier2/`: robustness runs (five repetitions of every configuration, wider schemas); `unique_vs_exclude.json`, `probe_model.json`, `check_plan_pg.json`, `mysql_diag.json`: unit costs and plan checks; `sqlite_laptop/`, `sqlite_laptop_clean/`: SQLite reruns of Experiment D on the laptop (the second on a quiet machine); `run_*.sh`: the runners |
| `D_native/` | the native index: `m2_expD.jsonl` (Experiment D), `dxl_native_ks*.jsonl` (10^6 rows), `e_*_native.jsonl` (real tables), `concurrency_reps.jsonl` (three repetitions; `concurrency.jsonl` is the first single run), `m1_*.jsonl` (cost per insert); see `experiments/D_native/README.md` |
| `E_mined_keys/` | covers of the mined keys: `hockey/` (levels 1 and 9, NOT NULL, the paper's table), `voc/`, `public/` (Wake County voters and Wikidata: keys and counts only, no records) |
| `E_real_tables/` | `real_pg.jsonl`, `voc_pg.jsonl`: mined keys against their cover on the real tables |
| `F_query_optimisation/` | `queries.json`, `queries2.json`, `queries3.json`: the three query batches of Experiment F |
| `rule_breakdown.json` | which inference rule removes each redundant key (Experiment D) |

The `run_*.sh` scripts are the runners used for the reported results; they expect the private
cluster of the top-level README. Console logs (`*.log`) are not committed.
