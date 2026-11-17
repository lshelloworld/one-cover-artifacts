import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.exists(_os.path.join(_ROOT, 'config.py')): _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_ROOT] + [_os.path.join(_ROOT, 'experiments', d) for d in ('lib', 'D_enforcement', 'E_real_tables', 'F_query_optimisation', 'E_mined_keys')]
_os.chdir(_ROOT)
"""Experiment E on public data: exhaustive mining of all minimal keys of every class, then the cover.

  ncvoter   : NC voter file, Wake County (ncvoter92.zip from the NC State Board of Elections),
              active voters, 6 total and 7 nullable columns
  wikidata  : two extracts of the Wikidata query service: people with a GND identifier and their
              library authority identifiers; chemical compounds with a PubChem identifier and
              their registry identifiers (first value per entity)

The raw data contain personal information and are downloaded into data/public/, which is not part
of the artifact; only the mined keys and covers are written to results/E_mined_keys/public/.
Every key removed from the cover is classified as R1 (a stronger class on the same column set),
R4 (partial and certain key on a set with at most one nullable column) or 'other' (any other
implication, including colouring)."""
import sys, csv, io, os, json, time, zipfile, itertools, collections, urllib.request, urllib.parse
import multiprocessing
sys.path.insert(0, 'experiments/lib')
from keys import mincover_general, popcount, subset
Pool = multiprocessing.get_context('fork').Pool
RAW, OUT = 'data/public', 'results/E_mined_keys/public'
MAXK = 6
UA = {'User-Agent': 'onecover-artifacts/1.0 (key-constraint research)'}
NC_URL = 'https://s3.amazonaws.com/dl.ncsbe.gov/data/ncvoter92.zip'
NC_NN = ['last_name', 'first_name', 'birth_year', 'gender_code', 'res_street_address', 'registr_dt']
NC_NUL = ['middle_name', 'name_suffix_lbl', 'zip_code', 'mail_addr1', 'birth_state', 'precinct_abbrv', 'ward_abbrv']
WD = {
 'people': ('gnd', 'SELECT ?item ?gnd ?viaf ?isni ?lc ?bnf ?nta ?ndl ?orcid ?sudoc WHERE { ?item wdt:P227 ?gnd; wdt:P31 wd:Q5. '
            'OPTIONAL{?item wdt:P214 ?viaf} OPTIONAL{?item wdt:P213 ?isni} OPTIONAL{?item wdt:P244 ?lc} OPTIONAL{?item wdt:P268 ?bnf} '
            'OPTIONAL{?item wdt:P1006 ?nta} OPTIONAL{?item wdt:P349 ?ndl} OPTIONAL{?item wdt:P496 ?orcid} OPTIONAL{?item wdt:P269 ?sudoc} } LIMIT 150000'),
 'compounds': ('pubchem', 'SELECT ?item ?pubchem ?inchikey ?cas ?chemspider ?chebi ?chembl ?unii ?kegg ?drugbank WHERE { ?item wdt:P662 ?pubchem. '
            'OPTIONAL{?item wdt:P235 ?inchikey} OPTIONAL{?item wdt:P231 ?cas} OPTIONAL{?item wdt:P661 ?chemspider} OPTIONAL{?item wdt:P683 ?chebi} '
            'OPTIONAL{?item wdt:P592 ?chembl} OPTIONAL{?item wdt:P652 ?unii} OPTIONAL{?item wdt:P665 ?kegg} OPTIONAL{?item wdt:P715 ?drugbank} } LIMIT 150000'),
}

DATA = None                                    # one list of value codes per column, None for null

def encode(records, cols):
    codes = [dict() for _ in cols]
    return [[codes[j].setdefault(r[c], len(codes[j])) if r[c] else None for r in records] for j, c in enumerate(cols)]

def holds(arg):
    cls, K = arg
    cols = [DATA[i] for i in K]
    if cls == 'possible':
        seen = set()
        for vals in zip(*cols):
            if None in vals: continue
            if vals in seen: return False
            seen.add(vals)
        return True
    G = collections.defaultdict(list)                      # null pattern -> projections on its non-null columns
    for vals in zip(*cols):
        G[tuple(i for i, v in zip(K, vals) if v is not None)].append(tuple(v for v in vals if v is not None))
    if cls == 'domain':
        return all(len(set(ps)) == len(ps) for ps in G.values())
    for Q, ps in G.items():
        if len(set(ps)) < len(ps): return False
        for Q2, ps2 in G.items():
            if Q2 == Q or (cls == 'partial' and not set(Q) < set(Q2)) or (cls == 'certain' and Q > Q2): continue
            I = [Q.index(i) for i in Q if i in Q2]; I2 = [Q2.index(i) for i in Q if i in Q2]
            a = {tuple(p[j] for j in I) for p in ps}           # subsumed (partial) or compatible (certain)
            if any(tuple(p[j] for j in I2) in a for p in ps2): return False
    return True

def mine(pool, n):
    """All minimal keys of each class with at most MAXK columns; a class is tested only on
    supersets of keys of the next weaker class, since every key implies the weaker ones."""
    M, base = {}, None
    for cls in ['possible', 'domain', 'partial', 'certain']:
        found = []
        for k in range(1, min(MAXK, n) + 1):
            cand = [K for K in itertools.combinations(range(n), k)
                    if not any(set(F) <= set(K) for F in found) and (base is None or any(set(B) <= set(K) for B in base))]
            found += [K for K, ok in zip(cand, pool.map(holds, [(cls, K) for K in cand], chunksize=1)) if ok]
        M[cls] = base = found
    return M

def report(name, cols, nn, M, nrows):
    NN = sum(1 << i for i, c in enumerate(cols) if c in nn)
    mined = [(c, sum(1 << i for i in K)) for c in M for K in M[c]]
    G = set(mincover_general(mined, NN))
    why = collections.Counter()
    for c, m in mined:
        if (c, m) in G: continue
        if any(L == m for _, L in G): why['R1' if not (c in ('partial', 'certain') and popcount(m & ~NN) <= 1) else 'R4'] += 1
        else: why['other'] += 1
    res = dict(data=name, rows=nrows, columns=cols, not_null=nn, max_size=MAXK,
               mined={c: len(M[c]) for c in M}, cover=len(G), removed_by=dict(why),
               keys={c: [[cols[i] for i in K] for K in M[c]] for c in M})
    json.dump(res, open(f'{OUT}/{name}.json', 'w'), indent=1)
    print(f"{name}: {nrows} rows, mined {res['mined']}, cover {len(G)}, removed by {dict(why)}", flush=True)

def ncvoter():
    path = f'{RAW}/ncvoter92.zip'
    if not os.path.exists(path): urllib.request.urlretrieve(NC_URL, path)
    with zipfile.ZipFile(path) as z:
        f = io.TextIOWrapper(z.open('ncvoter92.txt'), encoding='latin-1')
        recs = [{k: (v or '').strip() for k, v in r.items()} for r in csv.DictReader(f, delimiter='\t') if r['status_cd'].strip() == 'A']
    return recs, NC_NN + NC_NUL, NC_NN

def wikidata(which):
    ident, query = WD[which]; path = f'{RAW}/wikidata_{which}.csv'
    if not os.path.exists(path):
        url = 'https://query.wikidata.org/sparql?' + urllib.parse.urlencode({'query': query})
        req = urllib.request.Request(url, headers=dict(UA, Accept='text/csv'))
        open(path, 'wb').write(urllib.request.urlopen(req, timeout=300).read())
    first = {}
    for r in csv.DictReader(open(path, encoding='utf-8')): first.setdefault(r['item'], r)
    recs = list(first.values())
    cols = [c for c in recs[0] if c not in ('item', ident)]   # the selecting identifier is unique and total
    return recs, cols, [c for c in cols if all(r[c] for r in recs)]

if __name__ == '__main__':
    os.makedirs(RAW, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    jobs = sys.argv[1:] or ['ncvoter', 'wikidata']
    for job in jobs:
        for name, load in ([('ncvoter_wake_active', ncvoter)] if job == 'ncvoter' else
                           [(f'wikidata_{w}', lambda w=w: wikidata(w)) for w in WD]):
            t0 = time.time(); recs, cols, nn = load()
            cols = nn + [c for c in cols if c not in nn]               # NOT NULL columns first
            DATA = encode(recs, cols)
            with Pool(min(12, os.cpu_count())) as pool:
                M = mine(pool, len(cols))
            report(name, cols, nn, M, len(recs)); print(f'   {time.time() - t0:.0f} s', flush=True)
