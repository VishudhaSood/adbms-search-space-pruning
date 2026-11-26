LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off; SET jit = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder((cn ((mc (((mi it2) (miidx it)) (t kt))) ct)))  HashJoin(mi it2)  HashJoin(miidx it)  HashJoin(mi it2 miidx it)  HashJoin(t kt)  HashJoin(mi it2 miidx it t kt)  HashJoin(mc mi it2 miidx it t kt)  HashJoin(mc mi it2 miidx it t kt ct)  HashJoin(cn mc mi it2 miidx it t kt ct)
   SeqScan(cn) SeqScan(ct) SeqScan(it) SeqScan(it2) SeqScan(kt) SeqScan(mc) SeqScan(mi) SeqScan(miidx) SeqScan(t) */
SELECT MIN(cn.name) AS producing_company,
       MIN(miidx.info) AS rating,
       MIN(t.title) AS movie_about_winning
FROM company_name AS cn,
     company_type AS ct,
     info_type AS it,
     info_type AS it2,
     kind_type AS kt,
     movie_companies AS mc,
     movie_info AS mi,
     movie_info_idx AS miidx,
     title AS t
WHERE cn.country_code ='[us]'
  AND ct.kind ='production companies'
  AND it.info ='rating'
  AND it2.info ='release dates'
  AND kt.kind ='movie'
  AND t.title != ''
  AND (t.title LIKE 'Champion%'
       OR t.title LIKE 'Loser%')
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
