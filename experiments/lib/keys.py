"""Keys over incomplete relations: implication and covers.

Column sets are bit masks over n columns.  A key is a pair (cls, mask) with
cls in {'possible','domain','partial','certain'}.  NN is the bit mask of the
NOT NULL columns.  Candidate keys are modelled as certain keys on NN columns.
"""
import random, itertools

RANK = {'possible': 1, 'domain': 2, 'partial': 3, 'certain': 4}
FRAGMENTS = {
    'F1': ['possible', 'domain', 'partial'],
    'F2': ['possible', 'domain', 'certain'],
    'ALL': ['possible', 'domain', 'partial', 'certain'],
}

def popcount(x):
    return bin(x).count('1')

def subset(a, b):
    return a & ~b == 0

# ---------------------------------------------------------------- colouring
def not_two_colourable(V, edges):
    """Algorithm 2.  V: vertex mask; edges: list of masks (subsets of V)."""
    if any(popcount(e) <= 1 for e in edges):
        return True
    # minimal edges only
    edges = sorted(set(edges), key=popcount)
    minimal = []
    for e in edges:
        if not any(subset(f, e) for f in minimal):
            minimal.append(e)
    edges = minimal
    E2 = [e for e in edges if popcount(e) == 2]
    E3 = [e for e in edges if popcount(e) >= 3]
    verts = [i for i in range(V.bit_length()) if V >> i & 1]

    def bipartite(graph_edges):
        adj = {v: [] for v in verts}
        for e in graph_edges:
            a, b = [i for i in verts if e >> i & 1]
            adj[a].append(b); adj[b].append(a)
        colour = {}
        for s in verts:
            if s in colour:
                continue
            colour[s] = 0
            stack = [s]
            while stack:
                u = stack.pop()
                for w in adj[u]:
                    if w not in colour:
                        colour[w] = 1 - colour[u]; stack.append(w)
                    elif colour[w] == colour[u]:
                        return False
        return True

    def branch(j, F):
        if j == len(E3):
            return not bipartite(F)
        e = E3[j]
        vs = [i for i in verts if e >> i & 1]
        v = vs[0]
        for w in vs[1:]:
            if not branch(j + 1, F + [(1 << v) | (1 << w)]):
                return False
        return True

    return branch(0, E2)

# -------------------------------------------------------------- implication
def implies(sigma, phi, NN):
    """Algorithm 1: does the key set `sigma` imply key `phi`?"""
    cls, K = phi
    if cls != 'certain':
        for c2, L in sigma:
            if subset(L, K) and (RANK[c2] >= RANK[cls] or subset(L, NN)):
                return True
        return False
    E = []
    NK = K & ~NN
    for c2, L in sigma:
        if subset(L, K):
            if c2 == 'certain' or subset(L, NN):
                return True
            if c2 == 'partial':
                E.append(L & NK)
    if not E:
        return False
    return not_two_colourable(NK, E)

def equivalent(sigma, gamma, NN):
    return all(implies(gamma, s, NN) for s in sigma) and all(implies(sigma, g, NN) for g in gamma)

# ------------------------------------------------------------------ covers
def mincover_fragment(sigma, NN, top):
    """Algorithm 3 for F1 (top='partial') or F2 (top='certain')."""
    sig = set()
    for cls, L in sigma:
        if subset(L, NN):
            cls = top
        sig.add((cls, L))
    order = sorted(sig, key=lambda k: (popcount(k[1]), -RANK[k[0]]))
    gamma = []
    for cls, K in order:
        red = False
        for c2, L in gamma:
            if subset(L, K) and (RANK[c2] >= RANK[cls] or subset(L, NN)):
                red = True; break
        if not red:
            gamma.append((cls, K))
    return gamma

def mincover_general(sigma, NN):
    """Algorithm 4."""
    sig = set()
    for cls, L in sigma:
        if subset(L, NN):
            cls = 'certain'
        if cls == 'partial' and popcount(L & ~NN) <= 1:
            cls = 'certain'
        sig.add((cls, L))
    gamma = sorted(sig, key=lambda k: -popcount(k[1]))
    i = 0
    while i < len(gamma):
        s = gamma[i]
        rest = gamma[:i] + gamma[i + 1:]
        if implies(rest, s, NN):
            gamma.pop(i)
        else:
            i += 1
    return gamma

# --------------------------------------------------------------- generation
def random_keys(n, k, m, fragment, rng, size_p=0.3):
    """Random set of m keys over n columns, the first k NOT NULL."""
    NN = (1 << k) - 1
    classes = FRAGMENTS[fragment]
    total = (2 ** n - n - 1) * len(classes)
    m = min(m, total // 2)
    keys = set()
    while len(keys) < m:
        size = 2 + sum(rng.random() < size_p for _ in range(n - 2))
        cols = rng.sample(range(n), size)
        mask = sum(1 << c for c in cols)
        keys.add((rng.choice(classes), mask))
    return NN, list(keys)

def occ(keys):
    return sum(popcount(m) for _, m in keys)

def fmt_mask(mask, n):
    return ''.join(chr(ord('A') + i) for i in range(n) if mask >> i & 1)
