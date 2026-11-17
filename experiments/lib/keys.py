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
    """Algorithm 2.  V: vertex mask; edges: list of masks (subsets of V).
    A partial colouring is a pair of disjoint masks (R, B); search branches on vertices."""
    if any(popcount(e) <= 1 for e in edges):
        return True
    # minimal edges only
    edges = sorted(set(edges), key=popcount)
    minimal = []
    for e in edges:
        if not any(subset(f, e) for f in minimal):
            minimal.append(e)

    def free_bits(e, R, B):
        f = e & ~(R | B)
        while f:
            b = f & -f; yield b; f ^= b

    def colourable(R, B, active):
        changed = True
        while changed:                                   # propagation
            changed = False; rest = []
            for e in active:
                if e & R and e & B:
                    continue                             # both colours: satisfied
                f = e & ~(R | B)
                if f == 0:
                    return False                         # monochromatic
                if f & (f - 1) == 0:                     # one free vertex: forced
                    if e & R: B |= f
                    else: R |= f
                    changed = True; continue
                rest.append(e)
            active = rest
        while True:                                      # a free vertex in one edge only satisfies it
            occ = {}
            for e in active:
                for b in free_bits(e, R, B):
                    occ[b] = occ.get(b, 0) + 1
            keep = [e for e in active if all(occ[b] > 1 for b in free_bits(e, R, B))]
            if len(keep) == len(active):
                break
            active = keep
        if not active:
            return True
        w = {}                                           # branch on the vertex in most and smallest edges
        for e in active:
            k = popcount(e & ~(R | B))
            for b in free_bits(e, R, B):
                w[b] = w.get(b, 0) + 1.0 / k
        v = max(w, key=w.get)
        return colourable(R | v, B, active) or colourable(R, B | v, active)

    # connected components are coloured independently
    comps = []                                           # (vertex mask, edges)
    for e in minimal:
        cv, ce = e, [e]
        for c in [c for c in comps if c[0] & e]:
            cv |= c[0]; ce += c[1]; comps.remove(c)
        comps.append((cv, ce))
    # the two colours are symmetric: one vertex of each component starts red
    return not all(colourable(cv & -cv, 0, ce) for cv, ce in comps)

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
