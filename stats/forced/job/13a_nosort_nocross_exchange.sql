LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off; SET jit = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder(((t (((mi it2) (miidx it)) ((mc cn) ct))) kt))  HashJoin(mi it2)  HashJoin(miidx it)  HashJoin(mi it2 miidx it)  HashJoin(mc cn)  HashJoin(mc cn ct)  HashJoin(mi it2 miidx it mc cn ct)  HashJoin(t mi it2 miidx it mc cn ct)  HashJoin(t mi it2 miidx it mc cn ct kt)
   SeqScan(cn) SeqScan(ct) SeqScan(it) SeqScan(it2) SeqScan(kt) SeqScan(mc) SeqScan(mi) SeqScan(miidx) SeqScan(t) */
SELECT MIN(mi.info) AS release_date,
       MIN(miidx.info) AS rating,
       MIN(t.title) AS german_movie
FROM company_name AS cn,
     company_type AS ct,
     info_type AS it,
     info_type AS it2,
     kind_type AS kt,
     movie_companies AS mc,
     movie_info AS mi,
     movie_info_idx AS miidx,
     title AS t
WHERE cn.country_code ='[de]'
  AND ct.kind ='production companies'
  AND it.info ='rating'
  AND it2.info ='release dates'
  AND kt.kind ='movie'
  AND mi.movie_id = t.id
  AND it2.id = mi.info_type_id
  AND kt.id = t.kind_id
  AND mc.movie_id = t.id
  AND cn.id = mc.company_id
  AND ct.id = mc.company_type_id
  AND miidx.movie_id = t.id
  AND it.id = miidx.info_type_id
  AND mi.movie_id = miidx.movie_id
  AND mi.movie_id = mc.movie_id
  AND miidx.movie_id = mc.movie_id;
