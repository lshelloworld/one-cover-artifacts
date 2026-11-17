import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Where the redundancy comes from. For every key set of Experiments D and E, compares
three ways of shrinking it:
  same-set   keep, for each column set, only keys not implied by another key on the same column set
  one-key    drop every key implied by a single other key (rules R1-R4 applied one premise at a time)
  cover      the cover (Algorithm 4), which also uses colouring
and reports keys and indexes (one per possible/domain key, 2^|N_K| per partial/certain key) for each.
Writes results/rule_breakdown.json."""
import json, collections
from keys import implies, mincover_general, popcount
from exp_db2_pg import parse_key, K as KNN

def reduce_by(S, NN, ok):
    """Drop keys implied by one other key that `ok` allows; among equivalent keys keep the first."""
    S = list(dict.fromkeys(S)); out = []
    for i, k in enumerate(S):
        if any(ok(o, k) and implies([o], k, NN) and not (implies([k], o, NN) and j > i) for j, o in enumerate(S) if j != i): continue
        out.append(k)
    return out
def idx(keys, NN): return sum(2 ** popcount(m & ~NN) if c in ('partial', 'certain') else 1 for c, m in keys)
def stages(S, NN, G=None):
    A = reduce_by(S, NN, lambda o, k: o[1] == k[1]); B = reduce_by(S, NN, lambda o, k: True)
    G = mincover_general(S, NN) if G is None else G
    return {n: (len(X), idx(X, NN)) for n, X in (('input', S), ('same-set', A), ('one-key', B), ('cover', G))}

out = {}
# Experiment D: the random key sets of db2_log.jsonl (5 per configuration), NOT NULL = first K columns
agg = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0])); cnt = collections.Counter()
for l in open('results/D_enforcement/db2_log.jsonl'):
    r = json.loads(l); NN = (1 << KNN) - 1
    st = stages([parse_key(s) for s in r['input']], NN, [parse_key(s) for s in r['output']]); key = f"D {r['fragment']} m={r['m']}"
    cnt[key] += 1
    for n, (a, b) in st.items(): agg[key][n][0] += a; agg[key][n][1] += b
for key in agg: out[key] = {n: (round(a / cnt[key], 1), round(b / cnt[key], 1)) for n, (a, b) in agg[key].items()}
# Experiment E: Hockey, levels 1 and 9, without and with the profiled NOT NULL columns
U = 'data/mined_keys'
FILES = {1: {c: f'{U}/mined_{c}_keys.txt' for c in ['possible', 'domain', 'partial', 'certain']},
         9: {c: f'{U}/{c}_keys-orth9.txt' for c in ['possible', 'domain', 'partial', 'certain']}}
NOTNULL = {t: set(v) for t, v in json.load(open('results/E_mined_keys/hockey/notnull.json')).items()}
for level in (1, 9):
    T = collections.defaultdict(lambda: collections.defaultdict(set))
    for cls, f in FILES[level].items():
        for line in open(f):
            line = line.strip()
            if line: t, cs = line.split('['); T[t.split('.')[1]][cls].add(frozenset(cs.rstrip(']').split(',')))
    for use_nn in (0, 1):
        for skip in ((), ('TeamSplits',)):
            tot = collections.defaultdict(lambda: [0, 0])
            for t in T:
                if t in skip: continue
                cols = sorted({c for s in T[t].values() for k in s for c in k}); ci = {c: i for i, c in enumerate(cols)}
                m = lambda k: sum(1 << ci[c] for c in k)
                S = sorted((cls, m(k)) for cls, ks in T[t].items() for k in ks)
                NN = m(NOTNULL.get(t, set()) & set(cols)) if use_nn else 0
                for n, (a, b) in stages(S, NN).items(): tot[n][0] += a; tot[n][1] += b
            out[f"E Hockey level {level} NN={use_nn}{' without TeamSplits' if skip else ''}"] = {n: tuple(v) for n, v in tot.items()}
# Experiment E: VOC, level 1
VF = {'possible': '1791953466091_voc-possible-orth1.txt', 'domain': '1791953466092_voc-domain-orth1.txt',
      'partial': '1791953466092_voc-partial-orth.txt', 'certain': '1791953466092_voc-certain-orth1.txt'}
prof = json.load(open('data/profiles/voc_profile.json')); T = collections.defaultdict(list)
for cls, f in VF.items():
    for line in open(f'{U}/{f}', encoding='utf-8-sig'):
        line = line.strip()
        if line: t, cs = line.split('['); T[t.split('.')[1]].append((cls, tuple(cs.rstrip(']').split(','))))
for use_nn in (0, 1):
    tot = collections.defaultdict(lambda: [0, 0])
    for t in T:
        cols = sorted({c for _, k in T[t] for c in k} | set(prof[t])); ci = {c: i for i, c in enumerate(cols)}
        S = sorted(set((cls, sum(1 << ci[c] for c in k)) for cls, k in T[t]))
        NN = sum(1 << ci[c] for c, v in prof[t].items() if v['nulls'] == 0) if use_nn else 0
        for n, (a, b) in stages(S, NN).items(): tot[n][0] += a; tot[n][1] += b
    out[f'E VOC level 1 NN={use_nn}'] = {n: tuple(v) for n, v in tot.items()}
json.dump(out, open('results/rule_breakdown.json', 'w'), indent=1)
for k, v in out.items(): print(f'{k:42s}', '  '.join(f'{n} {a}/{b}' for n, (a, b) in v.items()))
