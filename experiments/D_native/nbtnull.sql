-- Load the nbtnull access method into the current database. :libpath is the library without suffix.
CREATE FUNCTION nbtnull_handler(internal) RETURNS index_am_handler AS :'libpath' LANGUAGE C;
CREATE ACCESS METHOD nbtnull TYPE INDEX HANDLER nbtnull_handler;
CREATE FUNCTION onecover_nullpat(VARIADIC "any") RETURNS int4 AS :'libpath' LANGUAGE C IMMUTABLE PARALLEL SAFE;
CREATE FUNCTION nbtnull_stats(reset bool DEFAULT false, OUT nrows int8, OUT entries int8, OUT probes int8,
  OUT range_probes int8, OUT items int8, OUT heap_checks int8, OUT locks int8, OUT waits int8, OUT violations int8)
  AS :'libpath' LANGUAGE C;
CREATE OPERATOR CLASS nbtnull_int4_ops DEFAULT FOR TYPE int4 USING nbtnull AS
  OPERATOR 1 <, OPERATOR 2 <=, OPERATOR 3 =, OPERATOR 4 >=, OPERATOR 5 >,
  FUNCTION 1 btint4cmp(int4, int4), FUNCTION 2 btint4sortsupport(internal),
  FUNCTION 4 btequalimage(oid), FUNCTION 6 btint4skipsupport(internal);
CREATE OPERATOR CLASS nbtnull_int8_ops DEFAULT FOR TYPE int8 USING nbtnull AS
  OPERATOR 1 <, OPERATOR 2 <=, OPERATOR 3 =, OPERATOR 4 >=, OPERATOR 5 >,
  FUNCTION 1 btint8cmp(int8, int8), FUNCTION 2 btint8sortsupport(internal),
  FUNCTION 4 btequalimage(oid), FUNCTION 6 btint8skipsupport(internal);
-- nbtnull_key_index(index, table, X columns, N columns, mode, shadow depth): the DDL of a key index
CREATE OR REPLACE FUNCTION nbtnull_key_ddl(idx text, tbl text, xcols text[], ncols text[], mode text, depth int DEFAULT 1)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT format('CREATE INDEX %I ON %I USING nbtnull (%s(onecover_nullpat(%s)), (onecover_nullpat(%s)), %s) '
                'WITH (nx = %s, mode = %L, shadow_depth = %s)',
     idx, tbl, coalesce(nullif(array_to_string(xcols, ', '), '') || ', ', ''), array_to_string(ncols, ', '),
     array_to_string(ncols, ', '), array_to_string(ncols, ', '), coalesce(cardinality(xcols), 0), mode, depth)
$$;
