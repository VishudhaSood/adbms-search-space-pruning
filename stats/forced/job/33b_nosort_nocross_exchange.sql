LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off; SET jit = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder(((t1 (kt2 (t2 (cn2 (mc2 ((mc1 cn1) ((mi_idx1 it1) ((ml (mi_idx2 it2)) lt)))))))) kt1))  HashJoin(mc1 cn1)  HashJoin(mi_idx1 it1)  HashJoin(mi_idx2 it2)  HashJoin(ml mi_idx2 it2)  HashJoin(ml mi_idx2 it2 lt)  HashJoin(mi_idx1 it1 ml mi_idx2 it2 lt)  HashJoin(mc1 cn1 mi_idx1 it1 ml mi_idx2 it2 lt)  HashJoin(mc2 mc1 cn1 mi_idx1 it1 ml mi_idx2 it2 lt)  HashJoin(cn2 mc2 mc1 cn1 mi_idx1 it1 ml mi_idx2 it2 lt)  HashJoin(t2 cn2 mc2 mc1 cn1 mi_idx1 it1 ml mi_idx2 it2 lt)  HashJoin(kt2 t2 cn2 mc2 mc1 cn1 mi_idx1 it1 ml mi_idx2 it2 lt)  HashJoin(t1 kt2 t2 cn2 mc2 mc1 cn1 mi_idx1 it1 ml mi_idx2 it2 lt)  HashJoin(t1 kt2 t2 cn2 mc2 mc1 cn1 mi_idx1 it1 ml mi_idx2 it2 lt kt1)
   SeqScan(cn1) SeqScan(cn2) SeqScan(it1) SeqScan(it2) SeqScan(kt1) SeqScan(kt2) SeqScan(lt) SeqScan(mc1) SeqScan(mc2) SeqScan(mi_idx1) SeqScan(mi_idx2) SeqScan(ml) SeqScan(t1) SeqScan(t2) */
SELECT MIN(cn1.name) AS first_company,
       MIN(cn2.name) AS second_company,
       MIN(mi_idx1.info) AS first_rating,
       MIN(mi_idx2.info) AS second_rating,
       MIN(t1.title) AS first_movie,
       MIN(t2.title) AS second_movie
FROM company_name AS cn1,
     company_name AS cn2,
     info_type AS it1,
     info_type AS it2,
     kind_type AS kt1,
     kind_type AS kt2,
     link_type AS lt,
     movie_companies AS mc1,
     movie_companies AS mc2,
     movie_info_idx AS mi_idx1,
     movie_info_idx AS mi_idx2,
     movie_link AS ml,
     title AS t1,
     title AS t2
WHERE cn1.country_code = '[nl]'
  AND it1.info = 'rating'
  AND it2.info = 'rating'
  AND kt1.kind IN ('tv series')
  AND kt2.kind IN ('tv series')
  AND lt.link LIKE '%follow%'
  AND mi_idx2.info < '3.0'
  AND t2.production_year = 2007
  AND lt.id = ml.link_type_id
  AND t1.id = ml.movie_id
  AND t2.id = ml.linked_movie_id
  AND it1.id = mi_idx1.info_type_id
  AND t1.id = mi_idx1.movie_id
  AND kt1.id = t1.kind_id
  AND cn1.id = mc1.company_id
  AND t1.id = mc1.movie_id
  AND ml.movie_id = mi_idx1.movie_id
  AND ml.movie_id = mc1.movie_id
  AND mi_idx1.movie_id = mc1.movie_id
  AND it2.id = mi_idx2.info_type_id
  AND t2.id = mi_idx2.movie_id
  AND kt2.id = t2.kind_id
  AND cn2.id = mc2.company_id
  AND t2.id = mc2.movie_id
  AND ml.linked_movie_id = mi_idx2.movie_id
  AND ml.linked_movie_id = mc2.movie_id
  AND mi_idx2.movie_id = mc2.movie_id;
