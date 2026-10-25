# One Cover to Enforce Them All — artifacts

Artifacts of the paper *One Cover to Enforce Them All: Database Keys over Incomplete
Relations*: the paper and its extended version, the implementation of implication and
covers, every experiment script with its raw results, and the data.

The **extended version** is the same paper plus appendices with all proofs, further
results and examples, Experiment B in full, the absolute timings of Experiment D, and a
description of the logs. It is included ready to read as
[`extended-version.pdf`](extended-version.pdf), and `make paper` rebuilds it from
`paper/vldb-extended.tex`.

SQL tables offer diverse ways to identify their records uniquely — `PRIMARY KEY`,
`UNIQUE`, `NOT NULL`, and the domain, partial and certain keys that key mining
discovers — but a unique way to enforce them all: the paper shows that minimal and
optimal covers coincide and are unique, and the experiments measure what enforcing
that cover saves.

## Quick start

```
pip install -r requirements.txt
make check-data      # every mined key holds on the exported tables
make figures         # redraw the paper's figures from the committed results
make paper           # build the paper and its extended version (needs TeX Live)
```

Each experiment has its own target: `make exp-A-C`, `exp-D-sqlite`, `exp-D-pg`, `exp-E`,
`exp-E-tables` and `exp-F`. The PostgreSQL experiments read the connection from the
environment variables `ONECOVER_DB_HOST`, `ONECOVER_DB_PORT`, `ONECOVER_DB_USER`,
`ONECOVER_DB_PASSWORD` and `ONECOVER_DB_NAME` (defaults in `config.py`). All random
generators are seeded; the long PostgreSQL runs append one JSON line per measurement
and resume where they stopped. `make figures` reproduces the committed figures byte for
byte.

## Layout

```
config.py, Makefile          paths and database settings; one target per experiment
paper/                       vldb.tex (paper), vldb-extended.tex (with appendices),
                             VLDB template files, figs/
experiments/
  lib/                       keys.py (implication, covers), hockey_data.py (loader),
                             check_mined.py (key checks)
  A-C_random_covers/         Experiments A, B, C
  D_enforcement/             Experiment D (SQLite, PostgreSQL, naive and large-table runs)
  E_mined_keys/              Experiment E: covers of mined keys (Hockey, VOC)
  E_real_tables/             Experiment E: enforcing mined keys vs cover on the real tables
  F_query_optimisation/      Experiment F: query rewrites, planning cost, hidden uniqueness
  make_figures.py            redraws the figures of Experiments A-D
results/                     raw outputs (JSON / JSONL) of every experiment, by directory
data/
  hockey/, voc/              table exports (see below)
  mined_keys/                keys mined per class (Hockey levels 1 and 9, VOC level 1, Staff i0)
  profiles/                  column profiles (null, distinct and row counts)
```

## From claims to artifacts

| Paper element | Produced by | Raw results |
|---|---|---|
| Experiments A, B, C (figures in Section 6 and the appendix) | `make exp-A-C`, `make figures` | `results/A-C_random_covers/covers_log.jsonl` |
| Experiment D (figure, speed-up table, appendix tables) | `make exp-D-sqlite exp-D-pg` | `results/D_enforcement/` |
| Experiment E: covers of mined keys (table, levels 1/9, NOT NULL, VOC) | `make exp-E` | `results/E_mined_keys/` |
| Experiment E: enforcement on the real tables | `make exp-E-tables` | `results/E_real_tables/` |
| Experiment F: query optimisation (table, planning cost) | `make exp-F` | `results/F_query_optimisation/` |

## Data

The Hockey and VOC tables come from the CTU Prague Relational Learning Repository.
The exports in `data/hockey` and `data/voc` store each table as a block of 8-byte cells
in row order, with an all-zero cell for `NULL`; values are hashed, which preserves
equality and nulls, all that key tests depend on. `experiments/lib/hockey_data.py`
reads them. The tables marked `-full` are complete; Hockey's `Scoring` and
`TeamVsTeam` are samples and are not used. Column profiles are in
`data/profiles/column_profiles.csv`; a column is treated as `NOT NULL` when its null
count is zero. The keys in `data/mined_keys` are minimal per class among the keys
that pass the miner's orthogonality filter (level 1, or level 9 for the strict Hockey
lists). Please check the terms of the source repository before redistributing the
data.

## Licence

Code and paper sources: MIT (see `LICENSE`). Data: terms of the source datasets.
