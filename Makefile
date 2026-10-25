# Reproduce the paper, its figures and its experiments. Run from the repository root.
# Experiments D (PostgreSQL), E (real tables) and F need PostgreSQL 16; set ONECOVER_DB_* (see config.py).
PY ?= python3

.PHONY: all paper figures check-data experiments exp-A-C exp-D-sqlite exp-D-pg exp-E exp-E-tables exp-F clean

all: figures paper

paper:                            # the paper (12 pages + references) and its extended version (with appendices)
	cd paper && for f in vldb vldb-extended; do pdflatex -interaction=nonstopmode $$f.tex >/dev/null && pdflatex -interaction=nonstopmode $$f.tex >/dev/null; done

figures:
	$(PY) experiments/make_figures.py

check-data:                       # every mined key holds on the exported tables
	$(PY) experiments/lib/check_mined.py
	$(PY) experiments/E_real_tables/exp_voc.py --check

exp-A-C:                          # Experiments A, B, C: random key sets
	$(PY) experiments/A-C_random_covers/exp_covers.py A B C

exp-D-sqlite:                     # Experiment D on SQLite
	$(PY) experiments/D_enforcement/exp_db2.py

exp-D-pg:                         # Experiment D on PostgreSQL, naive baseline, 100k-row run
	$(PY) experiments/D_enforcement/exp_db2_pg.py 1
	$(PY) experiments/D_enforcement/exp_db2_pg_extra.py naive
	$(PY) experiments/D_enforcement/exp_db2_pg_extra.py large

exp-E:                            # Experiment E: covers of mined keys (Hockey, VOC)
	$(PY) experiments/E_mined_keys/exp_real.py
	$(PY) experiments/E_mined_keys/exp_real2.py
	$(PY) experiments/E_mined_keys/voc_covers.py
	$(PY) experiments/E_mined_keys/find_colouring.py

exp-E-tables:                     # Experiment E: enforcing mined keys vs cover on the real tables
	$(PY) experiments/E_real_tables/exp_real_pg.py
	$(PY) experiments/E_real_tables/exp_voc.py

exp-F:                            # Experiment F: query optimisation
	$(PY) experiments/F_query_optimisation/exp_queries.py
	$(PY) experiments/F_query_optimisation/exp_queries2.py

experiments: exp-A-C exp-D-sqlite exp-D-pg exp-E exp-E-tables exp-F

clean:
	rm -f paper/*.aux paper/*.log paper/*.out
