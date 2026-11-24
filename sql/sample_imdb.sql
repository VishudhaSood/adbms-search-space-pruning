-- Correlated sample of IMDB for JOB (Workstream D / task ii, step 2).
--
-- Run against the FULL database, with the sampling rate as a psql variable:
--     psql -v ON_ERROR_STOP=1 -v p=0.1 -d imdb -f sql/sample_imdb.sql
-- It builds the sample as schema s10 inside imdb; tools/build_imdb_s10.sh then copies that schema into its own
-- database imdb_s10 (as public), ANALYZEs it and extracts the stats for Calcite.
--
-- Method (correlated sampling, Vengerov et al., VLDB 2015): one hash on the movie id,
--     h(x) = (x * 2654435761) mod 2^32,   keep a movie if h(x) < p * 2^32,
-- applied to title.id and to movie_id in every movie table. A movie is then kept in all tables or dropped from all
-- of them, so a join on movie_id keeps about p of its matches, not p^2.
--   movie tables    : title (by id); movie_companies, movie_info, movie_info_idx, movie_keyword, cast_info,
--                     complete_cast, aka_title, movie_link (by movie_id)
--   lookup tables   : exactly the rows still referenced: name (cast_info.person_id), char_name
--                     (cast_info.person_role_id), company_name (movie_companies.company_id), keyword
--                     (movie_keyword.keyword_id); then aka_name and person_info by the kept name ids
--   type tables     : kept whole: info_type, kind_type, role_type, company_type, comp_cast_type, link_type
-- Every table keeps its columns, NOT NULL constraints and primary key (CREATE TABLE ... LIKE ... INCLUDING ALL).
-- Known losses, reported at the end: movie_link rows whose linked_movie_id was dropped, and complete_cast rows
-- with a NULL movie_id.

\if :{?p}
\else
  \echo 'set the sampling rate: psql -v p=0.1 -d imdb -f sql/sample_imdb.sql'
  \quit
\endif

\timing on
SET max_parallel_workers_per_gather = 4;     -- building the sample may use parallel scans; the experiments don't

DROP SCHEMA IF EXISTS s10 CASCADE;
CREATE SCHEMA s10;

-- the rate actually used, kept with the sample
CREATE TABLE s10._sample_info AS
SELECT :p::float8 AS p,
       floor(:p::float8 * 4294967296)::bigint AS threshold,
       'h(x) = (x * 2654435761) mod 2^32 < threshold' AS rule,
       now() AS built_at;

-- keep(x): is movie x in the sample?  (x::bigint so the product can't overflow; NULL -> not kept)
-- The threshold is written into the function body as a constant (psql can't substitute inside $$ ... $$).
SELECT format('CREATE FUNCTION s10.keep(x integer) RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS %L',
              'SELECT (x::bigint * 2654435761) % 4294967296 < ' || threshold)
FROM s10._sample_info \gexec

-- empty copies with the same columns, constraints and primary keys
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['aka_name','aka_title','cast_info','char_name','comp_cast_type','company_name',
                           'company_type','complete_cast','info_type','keyword','kind_type','link_type',
                           'movie_companies','movie_info','movie_info_idx','movie_keyword','movie_link','name',
                           'person_info','role_type','title'] LOOP
    EXECUTE format('CREATE TABLE s10.%I (LIKE public.%I INCLUDING ALL)', t, t);
  END LOOP;
END $$;

-- 1. movie tables: correlated on the movie id
INSERT INTO s10.title           SELECT * FROM public.title           WHERE s10.keep(id);
INSERT INTO s10.movie_companies SELECT * FROM public.movie_companies WHERE s10.keep(movie_id);
INSERT INTO s10.movie_info      SELECT * FROM public.movie_info      WHERE s10.keep(movie_id);
INSERT INTO s10.movie_info_idx  SELECT * FROM public.movie_info_idx  WHERE s10.keep(movie_id);
INSERT INTO s10.movie_keyword   SELECT * FROM public.movie_keyword   WHERE s10.keep(movie_id);
INSERT INTO s10.cast_info       SELECT * FROM public.cast_info       WHERE s10.keep(movie_id);
INSERT INTO s10.complete_cast   SELECT * FROM public.complete_cast   WHERE s10.keep(movie_id);
INSERT INTO s10.aka_title       SELECT * FROM public.aka_title       WHERE s10.keep(movie_id);
INSERT INTO s10.movie_link      SELECT * FROM public.movie_link      WHERE s10.keep(movie_id);

-- 2. lookup tables: exactly the rows the kept movie rows still reference
INSERT INTO s10.name         SELECT * FROM public.name n
  WHERE n.id IN (SELECT person_id FROM s10.cast_info);
INSERT INTO s10.char_name    SELECT * FROM public.char_name c
  WHERE c.id IN (SELECT person_role_id FROM s10.cast_info WHERE person_role_id IS NOT NULL);
INSERT INTO s10.company_name SELECT * FROM public.company_name c
  WHERE c.id IN (SELECT company_id FROM s10.movie_companies);
INSERT INTO s10.keyword      SELECT * FROM public.keyword k
  WHERE k.id IN (SELECT keyword_id FROM s10.movie_keyword);
INSERT INTO s10.aka_name     SELECT * FROM public.aka_name a
  WHERE a.person_id IN (SELECT id FROM s10.name);
INSERT INTO s10.person_info  SELECT * FROM public.person_info p
  WHERE p.person_id IN (SELECT id FROM s10.name);

-- 3. small type tables: whole
INSERT INTO s10.info_type      SELECT * FROM public.info_type;
INSERT INTO s10.kind_type      SELECT * FROM public.kind_type;
INSERT INTO s10.role_type      SELECT * FROM public.role_type;
INSERT INTO s10.company_type   SELECT * FROM public.company_type;
INSERT INTO s10.comp_cast_type SELECT * FROM public.comp_cast_type;
INSERT INTO s10.link_type      SELECT * FROM public.link_type;

DROP FUNCTION s10.keep(integer);   -- not part of the sample database

-- ---------------------------------------------------------------- checks (Workstream D, step 3)
-- a) rows per table, sample vs full
CREATE TABLE s10._check_rows (tbl text PRIMARY KEY, full_rows bigint, sample_rows bigint, ratio float8);
DO $$
DECLARE t text; f bigint; s bigint;
BEGIN
  FOREACH t IN ARRAY ARRAY['aka_name','aka_title','cast_info','char_name','comp_cast_type','company_name',
                           'company_type','complete_cast','info_type','keyword','kind_type','link_type',
                           'movie_companies','movie_info','movie_info_idx','movie_keyword','movie_link','name',
                           'person_info','role_type','title'] LOOP
    EXECUTE format('SELECT count(*) FROM public.%I', t) INTO f;
    EXECUTE format('SELECT count(*) FROM s10.%I', t) INTO s;
    INSERT INTO s10._check_rows VALUES (t, f, s, CASE WHEN f > 0 THEN s::float8 / f END);
  END LOOP;
END $$;

-- b) four 2-table joins on the movie: should shrink to about p (correlated), not p^2 (independent).
--    Join sizes are computed as sum over movies of (rows on one side x rows on the other), which is exact and
--    avoids materialising billions of matches (movie_info x movie_keyword is huge on the full data).
CREATE FUNCTION pg_temp.join_size(l text, lcol text, r text, rcol text) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE n numeric;
BEGIN
  EXECUTE format('SELECT sum(a.n * b.n) FROM (SELECT %2$I AS k, count(*) AS n FROM %1$s GROUP BY 1) a '
                 'JOIN (SELECT %4$I AS k, count(*) AS n FROM %3$s GROUP BY 1) b USING (k)', l, lcol, r, rcol) INTO n;
  RETURN coalesce(n, 0)::bigint;
END $$;

CREATE TABLE s10._check_joins (join_name text PRIMARY KEY, full_rows bigint, sample_rows bigint, ratio float8);
INSERT INTO s10._check_joins
SELECT j, f, s, s::float8 / NULLIF(f, 0) FROM (VALUES
  ('title x movie_companies',
     pg_temp.join_size('public.title', 'id', 'public.movie_companies', 'movie_id'),
     pg_temp.join_size('s10.title', 'id', 's10.movie_companies', 'movie_id')),
  ('title x cast_info',
     pg_temp.join_size('public.title', 'id', 'public.cast_info', 'movie_id'),
     pg_temp.join_size('s10.title', 'id', 's10.cast_info', 'movie_id')),
  ('movie_info x movie_keyword',
     pg_temp.join_size('public.movie_info', 'movie_id', 'public.movie_keyword', 'movie_id'),
     pg_temp.join_size('s10.movie_info', 'movie_id', 's10.movie_keyword', 'movie_id')),
  ('movie_companies x movie_info_idx',
     pg_temp.join_size('public.movie_companies', 'movie_id', 'public.movie_info_idx', 'movie_id'),
     pg_temp.join_size('s10.movie_companies', 'movie_id', 's10.movie_info_idx', 'movie_id'))
) AS v(j, f, s);

-- c) the known losses
CREATE TABLE s10._check_losses AS
SELECT 'movie_link rows whose linked_movie_id was dropped' AS what,
       (SELECT count(*) FROM s10.movie_link ml WHERE ml.linked_movie_id NOT IN (SELECT id FROM s10.title)) AS n,
       (SELECT count(*) FROM s10.movie_link) AS out_of
UNION ALL
SELECT 'complete_cast rows with NULL movie_id (full DB, never sampled)',
       (SELECT count(*) FROM public.complete_cast WHERE movie_id IS NULL),
       (SELECT count(*) FROM public.complete_cast);

\echo
\echo '== sample'
SELECT p, threshold, rule FROM s10._sample_info;
\echo '== rows per table (movie tables should be near p; lookup tables higher; type tables 1.0)'
SELECT tbl, full_rows, sample_rows, round(ratio::numeric, 4) AS ratio FROM s10._check_rows ORDER BY ratio, tbl;
\echo '== 2-table joins on movie_id (should be near p, not p^2)'
SELECT join_name, full_rows, sample_rows, round(ratio::numeric, 4) AS ratio,
       round((ratio / (SELECT p FROM s10._sample_info))::numeric, 2) AS ratio_over_p
FROM s10._check_joins ORDER BY join_name;
\echo '== known losses'
SELECT what, n, out_of, round(n::numeric / NULLIF(out_of, 0), 4) AS share FROM s10._check_losses;
