LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off; SET jit = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder((k (mk (t ((mi it1) (ct (at (mc cn))))))))  HashJoin(mi it1)  HashJoin(mc cn)  HashJoin(at mc cn)  HashJoin(ct at mc cn)  HashJoin(mi it1 ct at mc cn)  HashJoin(t mi it1 ct at mc cn)  HashJoin(mk t mi it1 ct at mc cn)  HashJoin(k mk t mi it1 ct at mc cn)
   SeqScan(at) SeqScan(cn) SeqScan(ct) SeqScan(it1) SeqScan(k) SeqScan(mc) SeqScan(mi) SeqScan(mk) SeqScan(t) */
SELECT MIN(mi.info) AS release_date,
       MIN(t.title) AS youtube_movie
FROM aka_title AS at,
     company_name AS cn,
     company_type AS ct,
     info_type AS it1,
     keyword AS k,
     movie_companies AS mc,
     movie_info AS mi,
     movie_keyword AS mk,
     title AS t
WHERE cn.country_code = '[us]'
  AND cn.name = 'YouTube'
  AND it1.info = 'release dates'
  AND mc.note LIKE '%(200%)%'
  AND mc.note LIKE '%(worldwide)%'
  AND mi.note LIKE '%internet%'
  AND mi.info LIKE 'USA:% 200%'
  AND t.production_year BETWEEN 2005 AND 2010
  AND t.id = at.movie_id
  AND t.id = mi.movie_id
  AND t.id = mk.movie_id
  AND t.id = mc.movie_id
  AND mk.movie_id = mi.movie_id
  AND mk.movie_id = mc.movie_id
  AND mk.movie_id = at.movie_id
  AND mi.movie_id = mc.movie_id
  AND mi.movie_id = at.movie_id
  AND mc.movie_id = at.movie_id
  AND k.id = mk.keyword_id
  AND it1.id = mi.info_type_id
  AND cn.id = mc.company_id
  AND ct.id = mc.company_type_id;
