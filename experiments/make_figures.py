"""Redraw the figures of the paper from the committed raw results:
Experiments A and B (figs/expA.pdf, expB.pdf), Experiment C (figs/expC_col.pdf),
Experiment D (figs/expD_both.pdf, and expD.pdf, expD_pg.pdf of the appendix)."""
import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_os.chdir(_ROOT)
import json, statistics as st, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt
plt.rcParams['pdf.compression'] = 6
_save = plt.Figure.savefig
plt.Figure.savefig = lambda self, *a, **k: _save(self, *a, metadata={'CreationDate': None}, **k)   # reproducible PDFs
J = C = 'paper/figs'
COL = {'F1': 'tab:blue', 'F2': 'tab:orange', 'ALL': 'tab:green'}
LBL = {'F1': r'$\mathcal{F}_1$', 'F2': r'$\mathcal{F}_2$', 'ALL': 'combined class'}
SHORT = dict(LBL, ALL='combined')        # shorter legend label for the compact figures
recs = [json.loads(l) for l in open('results/A-C_random_covers/covers_log.jsonl')]
def agg(rows, key, x):
    xs = sorted({r[x] for r in rows}); return xs, [st.mean(r[key] for r in rows if r[x] == v) for v in xs]
# Experiments A and B
for exp, x, xlabel, title in (('A', 'in_keys', r'$|\Sigma|$', 'Experiment A: n = 12 columns, 4 NOT NULL, growing input size (mean of 10 trials)'),
                              ('B', 'n', 'n (columns)', r'Experiment B: $|\Sigma|$ = 200, NOT NULL = n/3, growing schema (mean of 10 trials)')):
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.6))
    for f in COL:
        rows = [r for r in recs if r['exp'] == exp and r['fragment'] == f]
        xs, ys = agg(rows, 'out_keys', x); ax[0].plot(xs, ys, 'o-', color=COL[f], label=LBL[f])
        xs, a = agg(rows, 'out_occ', x); _, b = agg(rows, 'in_occ', x); ax[1].plot(xs, [p / q for p, q in zip(a, b)], 'o-', color=COL[f])
        xs, ys = agg(rows, 'time', x); ax[2].plot(xs, [y * 1000 for y in ys], 'o-', color=COL[f])
    for a in ax: a.set_xlabel(xlabel)
    if exp == 'A':
        for a in ax: a.set_xscale('log')
    ax[0].set_ylabel('keys in cover'); ax[1].set_ylabel('attribute occurrences, cover / input'); ax[2].set_ylabel('time (ms)'); ax[2].set_yscale('log')
    ax[0].legend(); fig.suptitle(title); fig.tight_layout(); fig.savefig(f'{J}/exp{exp}.pdf'); plt.close(fig)
# Experiment C
rc = [r for r in recs if r['exp'] == 'C']; ps, kept = agg(rc, 'certain_kept', 'p'); _, tms = agg(rc, 'time', 'p')
fig, ax = plt.subplots(1, 2, figsize=(6.6, 2.5))
ax[0].plot(ps, kept, 'o-', color='tab:green'); ax[0].set_xlabel('binary partial keys $p$'); ax[0].set_ylabel('certain keys kept (of 50)')
ax[1].plot(ps, [t * 1000 for t in tms], 'o-', color='tab:green'); ax[1].set_xlabel('binary partial keys $p$'); ax[1].set_ylabel('time (ms)')
fig.tight_layout(); fig.savefig(f'{C}/expC_col.pdf'); plt.close(fig)
# Experiment D
sq = [json.loads(l) for l in open('results/D_enforcement/db2_log.jsonl')]
pg = json.load(open('results/D_enforcement/db2_pg_results.json'))
def mean(R, f, m, side, k): return st.mean(r[side][k] for r in R if r['fragment'] == f and r['m'] == m)
for R, name, title in ((sq, 'expD', 'Experiment D (SQLite)'), (pg, 'expD_pg', 'Experiment D (PostgreSQL 16)')):
    fig, ax = plt.subplots(1, 4, figsize=(16, 3.6))
    for f in COL:
        xs = sorted({r['m'] for r in R if r['fragment'] == f})
        for j, (k, t) in enumerate((('t_insert', 'inserts'), ('t_update', 'updates'), ('t_check', 'integrity check'), ('indexes', 'indexes created'))):
            ax[j].plot(xs, [mean(R, f, x, 'sigma', k) for x in xs], 'o--', color=COL[f], label=LBL[f] + ', input')
            ax[j].plot(xs, [mean(R, f, x, 'cover', k) for x in xs], 's-', color=COL[f], label=LBL[f] + ', cover')
            ax[j].set_title(t); ax[j].set_xlabel(r'$|\Sigma|$')
            if j < 3: ax[j].set_ylabel('seconds')
    ax[0].legend(fontsize=7); fig.suptitle(f'{title}: filtered-index enforcement, 8 columns, 1500 inserts, 600 updates (mean of 5 trials)')
    fig.tight_layout(); fig.savefig(f'{J}/{name}.pdf'); plt.close(fig)
fig, ax = plt.subplots(2, 3, figsize=(13, 5.0))
for row, (R, eng) in enumerate(((sq, 'SQLite 3.45 (in memory)'), (pg, 'PostgreSQL 16'))):
    for j, (k, t) in enumerate((('t_insert', 'inserts'), ('t_update', 'updates'), ('t_check', 'integrity check'))):
        for f in COL:
            xs = sorted({r['m'] for r in R if r['fragment'] == f})
            ax[row][j].plot(xs, [mean(R, f, x, 'sigma', k) for x in xs], 'o--', color=COL[f], ms=4, label=SHORT[f] + ', input')
            ax[row][j].plot(xs, [mean(R, f, x, 'cover', k) for x in xs], 's-', color=COL[f], ms=4, label=SHORT[f] + ', cover')
        ax[row][j].set_title(f'{eng}: {t}', fontsize=10); ax[row][j].set_ylabel('seconds')
        if row == 1: ax[row][j].set_xlabel(r'$|\Sigma|$')
ax[0][0].legend(fontsize=7, ncol=2); fig.tight_layout(); fig.savefig(f'{C}/expD_both.pdf'); plt.close(fig)
print('figures redrawn')
