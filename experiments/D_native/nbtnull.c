/*
 * nbtnull: a prototype PostgreSQL 18 index access method that enforces one partial key (mode subsumed)
 * or certain key (mode compatible), used for the native enforcement runs of "One Cover to Enforce Them
 * All" (Experiment D and the extended version's appendix). Its design is described separately.
 * Create indexes with nbtnull_key_ddl() (nbtnull.sql) on an empty table; violations raise SQLSTATE 23505.
 */
#include "postgres.h"

#include "access/amapi.h"
#include "access/htup_details.h"
#include "access/nbtree.h"
#include "access/reloptions.h"
#include "access/relscan.h"
#include "access/tableam.h"
#include "catalog/index.h"
#include "common/hashfn.h"
#include "fmgr.h"
#include "funcapi.h"
#include "miscadmin.h"
#include "storage/bufmgr.h"
#include "storage/lmgr.h"
#include "storage/lock.h"
#include "utils/builtins.h"
#include "utils/datum.h"
#include "utils/rel.h"
#include "utils/snapmgr.h"

PG_MODULE_MAGIC;

#define MODE_SUBSUMED   1
#define MODE_COMPATIBLE 2
#define LOCK_CLASS      0x4E4E
#define MAXN            16

typedef struct NbtnullOptions
{
	BTOptions	bt;
	int			nx;
	int			shadow_depth;
	int			mode;
} NbtnullOptions;

static relopt_kind nbtnull_relopt_kind;
static relopt_enum_elt_def mode_values[] = {
	{"subsumed", MODE_SUBSUMED}, {"partial", MODE_SUBSUMED},
	{"compatible", MODE_COMPATIBLE}, {"certain", MODE_COMPATIBLE},
	{NULL}
};

static uint64 st_rows, st_entries, st_probes, st_range_probes, st_items, st_heap_checks,
			st_locks, st_waits, st_violations;

void		_PG_init(void);

void
_PG_init(void)
{
	nbtnull_relopt_kind = add_reloption_kind();
	add_int_reloption(nbtnull_relopt_kind, "fillfactor", "Packs btree index pages only to this percentage",
					  BTREE_DEFAULT_FILLFACTOR, BTREE_MIN_FILLFACTOR, 100, ShareUpdateExclusiveLock);
	add_real_reloption(nbtnull_relopt_kind, "vacuum_cleanup_index_scale_factor", "Deprecated",
					   -1, 0.0, 1e10, ShareUpdateExclusiveLock);
	add_bool_reloption(nbtnull_relopt_kind, "deduplicate_items", "Enables deduplication",
					   true, AccessExclusiveLock);
	add_int_reloption(nbtnull_relopt_kind, "nx", "Number of NOT NULL key columns before the pattern column",
					  0, 0, INDEX_MAX_KEYS, AccessExclusiveLock);
	add_int_reloption(nbtnull_relopt_kind, "shadow_depth", "Shadow entries up to this many masked columns",
					  1, 0, MAXN, AccessExclusiveLock);
	add_enum_reloption(nbtnull_relopt_kind, "mode", "Key class: subsumed (partial) or compatible (certain)",
					   mode_values, MODE_COMPATIBLE, "Valid values are \"subsumed\" and \"compatible\".",
					   AccessExclusiveLock);
}

static bytea *
nbtnull_options(Datum reloptions, bool validate)
{
	static const relopt_parse_elt tab[] = {
		{"fillfactor", RELOPT_TYPE_INT, offsetof(NbtnullOptions, bt.fillfactor), 0},
		{"vacuum_cleanup_index_scale_factor", RELOPT_TYPE_REAL,
		offsetof(NbtnullOptions, bt.vacuum_cleanup_index_scale_factor), 0},
		{"deduplicate_items", RELOPT_TYPE_BOOL, offsetof(NbtnullOptions, bt.deduplicate_items), 0},
		{"nx", RELOPT_TYPE_INT, offsetof(NbtnullOptions, nx), 0},
		{"shadow_depth", RELOPT_TYPE_INT, offsetof(NbtnullOptions, shadow_depth), 0},
		{"mode", RELOPT_TYPE_ENUM, offsetof(NbtnullOptions, mode), 0},
	};

	return (bytea *) build_reloptions(reloptions, validate, nbtnull_relopt_kind,
									  sizeof(NbtnullOptions), tab, lengthof(tab));
}

typedef struct Layout
{
	int			nx,
				n,
				qatt,
				oatt,
				natts,
				depth,
				mode;
} Layout;

static Layout
get_layout(Relation rel)
{
	NbtnullOptions *o = (NbtnullOptions *) rel->rd_options;
	Layout		L;

	L.natts = IndexRelationGetNumberOfKeyAttributes(rel);
	if (IndexRelationGetNumberOfAttributes(rel) != L.natts)
		elog(ERROR, "nbtnull: INCLUDE columns are not supported");
	L.nx = o ? o->nx : 0;
	L.depth = o ? o->shadow_depth : 1;
	L.mode = o ? o->mode : MODE_COMPATIBLE;
	L.n = L.natts - L.nx - 2;
	if (L.n < 1 || L.n > MAXN)
		elog(ERROR, "nbtnull: index needs nx NOT NULL columns, the pattern column, the origin column and "
			 "1..%d nullable columns (has %d columns, nx = %d)", MAXN, L.natts, L.nx);
	L.qatt = L.nx;
	L.oatt = L.nx + 1;
	return L;
}

#define NCOL(L, j) ((L)->qatt + 2 + (j))

static inline int
popcount(uint32 v)
{
	return __builtin_popcount(v);
}

static inline bool
compatible_patterns(const Layout *L, uint32 a, uint32 b)
{
	return L->mode == MODE_COMPATIBLE || (a & b) == a || (a & b) == b;
}

static inline bool
resolved(const Layout *L, uint32 P, uint32 T)
{
	int			sp = popcount(P & ~T),
				st = popcount(T & ~P);

	if (L->mode == MODE_COMPATIBLE)
		return sp <= L->depth && st <= L->depth;

	return (sp == 0 && st <= L->depth) || (st == 0 && sp <= L->depth);
}

static uint32
key_hash(Relation rel, const Layout *L, uint32 Q, Datum *values, bool *isnull)
{
	TupleDesc	td = RelationGetDescr(rel);
	uint32		h = hash_bytes_uint32(Q);

	for (int a = 0; a < L->natts; a++)
	{
		Form_pg_attribute att = TupleDescAttr(td, a);

		if (a == L->qatt || a == L->oatt)
			continue;
		if (a > L->oatt && (Q >> (a - NCOL(L, 0)) & 1))
			continue;
		h = hash_combine(h, isnull[a] ? 0x9e3779b9 : datum_image_hash(values[a], att->attbyval, att->attlen));
	}
	return h;
}

static int
cmp_uint32(const void *a, const void *b)
{
	uint32		x = *(const uint32 *) a,
				y = *(const uint32 *) b;

	return x < y ? -1 : x > y;
}

typedef struct Conflict
{
	bool		found;
	TransactionId wait;
	ItemPointerData tid;
} Conflict;

static bool
check_heap(Relation heapRel, ItemPointer itid, Conflict *c)
{
	SnapshotData dirty;
	bool		all_dead = false;
	ItemPointerData tidbuf = *itid;
	ItemPointer tid = &tidbuf;

	InitDirtySnapshot(dirty);
	st_heap_checks++;
	if (!table_index_fetch_tuple_check(heapRel, tid, &dirty, &all_dead))
		return false;
	if (TransactionIdIsValid(dirty.xmin) || TransactionIdIsValid(dirty.xmax))
	{
		c->wait = TransactionIdIsValid(dirty.xmin) ? dirty.xmin : dirty.xmax;
		c->tid = *tid;
		return true;
	}
	c->found = true;
	c->tid = *tid;
	return true;
}

static inline bool
att_equal(Relation rel, int att, Datum a, bool anull, Datum b, bool bnull)
{
	if (anull || bnull)
		return anull && bnull;
	return DatumGetInt32(FunctionCall2Coll(index_getprocinfo(rel, att + 1, BTORDER_PROC),
										   rel->rd_indcollation[att], a, b)) == 0;
}

static bool
accept_entry(const Layout *L, uint32 P, uint32 Q, uint32 o)
{
	if (L->mode == MODE_COMPATIBLE)
		return (P | o) == Q;
	return P == Q || o == Q;
}

static void
search(Relation rel, Relation heapRel, const Layout *L, Datum *pv, bool *pn, int prefix,
	   uint32 unbound, ItemPointer self, Conflict *c)
{
	TupleDesc	td = RelationGetDescr(rel);
	IndexTuple	itup = index_form_tuple(td, pv, pn);
	BTScanInsert key = _bt_mkscankey(rel, itup);
	Buffer		buf;
	BTStack		stack;

	key->scantid = NULL;
	key->keysz = prefix;
	key->nextkey = false;
	key->backward = false;
	st_probes++;
	if (prefix < L->natts)
		st_range_probes++;

	stack = _bt_search(rel, heapRel, key, &buf, BT_READ);
	if (stack)
		_bt_freestack(stack);
	if (!BufferIsValid(buf))
	{
		pfree(key);
		pfree(itup);
		return;
	}

	for (;;)
	{
		Page		page = BufferGetPage(buf);
		BTPageOpaque op = BTPageGetOpaque(page);
		OffsetNumber lo = P_FIRSTDATAKEY(op),
					hi = PageGetMaxOffsetNumber(page) + 1,
					off;
		bool		more = true;

		if (P_IGNORE(op))
			goto next_page;
		while (lo < hi)
		{
			OffsetNumber mid = lo + (hi - lo) / 2;

			if (_bt_compare(rel, key, page, mid) > 0)
				lo = mid + 1;
			else
				hi = mid;
		}
		for (off = lo; off <= PageGetMaxOffsetNumber(page); off++)
		{
			ItemId		iid = PageGetItemId(page, off);
			IndexTuple	it;
			bool		isn;
			int			ok = 1;

			if (_bt_compare(rel, key, page, off) != 0)
			{
				more = false;
				break;
			}
			if (ItemIdIsDead(iid))
				continue;
			it = (IndexTuple) PageGetItem(page, iid);
			st_items++;
			for (int a = prefix; a < L->natts && ok; a++)
			{
				Datum		d;

				if (a > L->oatt && (unbound >> (a - NCOL(L, 0)) & 1))
					continue;
				d = index_getattr(it, a + 1, td, &isn);
				ok = att_equal(rel, a, d, isn, pv[a], pn[a]);
			}
			if (!ok)
				continue;
			if (BTreeTupleIsPosting(it))
			{
				for (int i = 0; i < BTreeTupleGetNPosting(it); i++)
				{
					ItemPointer t = BTreeTupleGetPostingN(it, i);

					if (!ItemPointerEquals(t, self) && check_heap(heapRel, t, c))
						goto done;
				}
			}
			else if (!ItemPointerEquals(&it->t_tid, self) && check_heap(heapRel, &it->t_tid, c))
				goto done;
		}
		if (!more || P_RIGHTMOST(op))
			break;

		if (_bt_compare(rel, key, page, P_HIKEY) < 0)
			break;
next_page:
		if (P_RIGHTMOST(op))
			break;
		buf = _bt_relandgetbuf(rel, buf, op->btpo_next, BT_READ);
	}
done:
	_bt_relbuf(rel, buf);
	pfree(key);
	pfree(itup);
}

static void
masked(const Layout *L, uint32 Q, uint32 o, Datum *values, bool *isnull, Datum *pv, bool *pn)
{
	for (int a = 0; a < L->natts; a++)
	{
		pv[a] = values[a];
		pn[a] = isnull[a];
	}
	for (int j = 0; j < L->n; j++)
		if (Q >> j & 1)
		{
			pv[NCOL(L, j)] = (Datum) 0;
			pn[NCOL(L, j)] = true;
		}
	pv[L->qatt] = UInt32GetDatum(Q);
	pn[L->qatt] = false;
	pv[L->oatt] = UInt32GetDatum(o);
	pn[L->oatt] = false;
}

static bool
nbtnull_insert(Relation rel, Datum *values, bool *isnull, ItemPointer ht_ctid, Relation heapRel,
			   IndexUniqueCheck checkUnique, bool indexUnchanged, IndexInfo *indexInfo)
{
	Layout		L = get_layout(rel);
	uint32		full = (L.n == 32) ? ~0u : ((1u << L.n) - 1);
	uint32		P = 0,
				nent = 0,
				nunres = 0,
				nlocks;
	uint32		ent[1 << 12],
				unres[1 << 12],
				locks[2 << 12];
	Datum		pv[INDEX_MAX_KEYS];
	bool		pn[INDEX_MAX_KEYS];
	LOCKTAG		tag;

	if (L.n > 12)
		elog(ERROR, "nbtnull: at most 12 nullable columns in this stage");
	for (int a = 0; a < L.nx; a++)
		if (isnull[a])
			elog(ERROR, "nbtnull: NULL in NOT NULL key column %d", a + 1);
	for (int j = 0; j < L.n; j++)
		if (isnull[NCOL(&L, j)])
			P |= 1u << j;
	st_rows++;

	for (uint32 Q = 0; Q <= full; Q++)
	{
		if ((Q & P) == P && popcount(Q & ~P) <= L.depth)
			ent[nent++] = Q;
		if (compatible_patterns(&L, P, Q) && !resolved(&L, P, Q))
			unres[nunres++] = Q;
	}

restart:
	nlocks = 0;
	for (uint32 i = 0; i < nent; i++)
		locks[nlocks++] = key_hash(rel, &L, ent[i], values, isnull);
	for (uint32 i = 0; i < nunres; i++)
		locks[nlocks++] = key_hash(rel, &L, P | unres[i], values, isnull);
	qsort(locks, nlocks, sizeof(uint32), cmp_uint32);
	{
		uint32		m = 0;

		for (uint32 i = 0; i < nlocks; i++)
			if (m == 0 || locks[i] != locks[m - 1])
				locks[m++] = locks[i];
		nlocks = m;
	}
	for (uint32 i = 0; i < nlocks; i++)
	{
		SET_LOCKTAG_ADVISORY(tag, MyDatabaseId, RelationGetRelid(rel), locks[i], LOCK_CLASS);
		(void) LockAcquire(&tag, ExclusiveLock, false, false);
		st_locks++;
	}

	{
		Conflict	c = {false, InvalidTransactionId};

		for (uint32 i = 0; i < nent && !c.found && !TransactionIdIsValid(c.wait); i++)
		{
			uint32		Q = ent[i],
						o = Q;

			for (;;)
			{
				if (popcount(Q & ~o) <= L.depth && accept_entry(&L, P, Q, o))
				{
					masked(&L, Q, o, values, isnull, pv, pn);
					search(rel, heapRel, &L, pv, pn, L.natts, 0, ht_ctid, &c);
					if (c.found || TransactionIdIsValid(c.wait))
						break;
				}
				if (o == 0)
					break;
				o = (o - 1) & Q;
			}
		}

		for (uint32 i = 0; i < nunres && !c.found && !TransactionIdIsValid(c.wait); i++)
		{
			uint32		T = unres[i],
						unb = P & ~T;
			int			prefix = L.oatt + 1;

			masked(&L, T, T, values, isnull, pv, pn);

			for (int j = 0; j < L.n; j++)
			{
				if (unb >> j & 1)
					break;
				prefix++;
			}
			search(rel, heapRel, &L, pv, pn, prefix, unb, ht_ctid, &c);
		}

		if (TransactionIdIsValid(c.wait))
		{
			for (uint32 i = 0; i < nlocks; i++)
			{
				SET_LOCKTAG_ADVISORY(tag, MyDatabaseId, RelationGetRelid(rel), locks[i], LOCK_CLASS);
				LockRelease(&tag, ExclusiveLock, false);
			}
			st_waits++;
			XactLockTableWait(c.wait, heapRel, &c.tid, XLTW_InsertIndex);
			goto restart;
		}
		if (c.found)
		{
			st_violations++;
			ereport(ERROR,
					(errcode(ERRCODE_UNIQUE_VIOLATION),
					 errmsg("duplicate key value violates %s key \"%s\"",
							L.mode == MODE_COMPATIBLE ? "certain" : "partial",
							RelationGetRelationName(rel)),
					 errdetail("Conflicting row at (%u,%u).",
							   ItemPointerGetBlockNumber(&c.tid), ItemPointerGetOffsetNumber(&c.tid))));
		}
	}

	for (uint32 i = 0; i < nent; i++)
	{
		masked(&L, ent[i], P, values, isnull, pv, pn);
		btinsert(rel, pv, pn, ht_ctid, heapRel, UNIQUE_CHECK_NO, indexUnchanged, indexInfo);
		st_entries++;
	}
	for (uint32 i = 0; i < nlocks; i++)
	{
		SET_LOCKTAG_ADVISORY(tag, MyDatabaseId, RelationGetRelid(rel), locks[i], LOCK_CLASS);
		LockRelease(&tag, ExclusiveLock, false);
	}
	return false;
}

static IndexBuildResult *
nbtnull_build(Relation heap, Relation index, IndexInfo *indexInfo)
{
	IndexBuildResult *r;

	(void) get_layout(index);
	r = btbuild(heap, index, indexInfo);
	if (r->heap_tuples > 0)
		ereport(ERROR,
				(errmsg("nbtnull: index \"%s\" can only be built on an empty table in this stage",
						RelationGetRelationName(index))));
	return r;
}

PG_FUNCTION_INFO_V1(nbtnull_handler);
Datum
nbtnull_handler(PG_FUNCTION_ARGS)
{
	IndexAmRoutine *am = (IndexAmRoutine *) DatumGetPointer(bthandler(fcinfo));

	am->amcanunique = false;
	am->amcanreturn = NULL;
	am->amgettuple = NULL;
	am->amgetbitmap = NULL;
	am->amcanparallel = false;
	am->amcanbuildparallel = false;
	am->amoptions = nbtnull_options;
	am->ambuild = nbtnull_build;
	am->aminsert = nbtnull_insert;
	PG_RETURN_POINTER(am);
}

PG_FUNCTION_INFO_V1(onecover_nullpat);
Datum
onecover_nullpat(PG_FUNCTION_ARGS)
{
	int32		p = 0;

	for (int i = 0; i < PG_NARGS() && i < 31; i++)
		if (PG_ARGISNULL(i))
			p |= 1 << i;
	PG_RETURN_INT32(p);
}

PG_FUNCTION_INFO_V1(nbtnull_stats);
Datum
nbtnull_stats(PG_FUNCTION_ARGS)
{
	TupleDesc	td;
	Datum		v[9];
	bool		n[9] = {0};
	HeapTuple	t;

	if (get_call_result_type(fcinfo, NULL, &td) != TYPEFUNC_COMPOSITE)
		elog(ERROR, "nbtnull_stats: return type must be a row type");
	v[0] = Int64GetDatum(st_rows);
	v[1] = Int64GetDatum(st_entries);
	v[2] = Int64GetDatum(st_probes);
	v[3] = Int64GetDatum(st_range_probes);
	v[4] = Int64GetDatum(st_items);
	v[5] = Int64GetDatum(st_heap_checks);
	v[6] = Int64GetDatum(st_locks);
	v[7] = Int64GetDatum(st_waits);
	v[8] = Int64GetDatum(st_violations);
	if (PG_NARGS() > 0 && PG_GETARG_BOOL(0))
		st_rows = st_entries = st_probes = st_range_probes = st_items = st_heap_checks = st_locks =
			st_waits = st_violations = 0;
	t = heap_form_tuple(BlessTupleDesc(td), v, n);
	PG_RETURN_DATUM(HeapTupleGetDatum(t));
}
