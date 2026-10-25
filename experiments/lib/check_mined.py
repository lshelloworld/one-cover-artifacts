import sys, collections, itertools, json
sys.path.insert(0, 'experiments/lib'); from hockey_data import load, tables
U = 'data/mined_keys'
FILES = {1: {c: f'{U}/mined_{c}_keys.txt' for c in ['possible','domain','partial','certain']},
         9: {c: f'{U}/{c}_keys-orth9.txt' for c in ['possible','domain','partial','certain']}}
def read(level):
    T = collections.defaultdict(list)
    for cls, f in FILES[level].items():
        for line in open(f, encoding='utf-8-sig'):
            line = line.strip()
            if line:
                t, cs = line.split('['); T[t.split('.')[1]].append((cls, tuple(cs.rstrip(']').split(','))))
    return T
def holds(rows, idx, cls):
    proj = [tuple(r[i] for i in idx) for r in rows]
    if cls == 'possible':
        tot = [p for p in proj if None not in p]; return len(tot) == len(set(tot))
    if cls == 'domain': return len(proj) == len(set(proj))
    groups = collections.defaultdict(list)
    for p in proj: groups[tuple(v is not None for v in p)].append(p)
    for P, Q in itertools.product(groups, repeat=2):
        if cls == 'certain':
            if P > Q: continue
            common = [j for j in range(len(idx)) if P[j] and Q[j]]
            a = [tuple(p[j] for j in common) for p in groups[P]]
            if P == Q:
                if len(a) != len(set(a)): return False
            else:
                b = {tuple(q[j] for j in common) for q in groups[Q]}
                if any(x in b for x in a): return False
        else:   # partial: t (pattern P) subsumed by t' (pattern Q) needs nonnull(P) <= nonnull(Q)
            if not all(Q[j] for j in range(len(idx)) if P[j]): continue
            common = [j for j in range(len(idx)) if P[j]]
            a = [tuple(p[j] for j in common) for p in groups[P]]
            if P == Q:
                if len(a) != len(set(a)): return False
            else:
                b = {tuple(q[j] for j in common) for q in groups[Q]}
                if any(x in b for x in a): return False
    return True
if __name__ == '__main__':
    full = set(tables()); res = {}
    for level in [1, 9]:
        T = read(level); ok = bad = skipped = 0; fails = []
        for t, keys in T.items():
            if t not in full: skipped += len(keys); continue
            cols, rows, nn = load(t); ci = {c: i for i, c in enumerate(cols)}
            for cls, K in keys:
                if holds(rows, [ci[c] for c in K], cls): ok += 1
                else: bad += 1; fails.append(f'{cls}({",".join(K)}) on {t}')
        print(f'level {level}: {ok} keys hold, {bad} fail, {skipped} on sampled tables not checked'); print('  ', fails[:10])
