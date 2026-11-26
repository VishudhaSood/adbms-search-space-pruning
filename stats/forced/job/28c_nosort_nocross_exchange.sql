LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off; SET jit = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder((k (mk ((kt (t (ct (cn ((cc (mc ((mi it1) (mi_idx it2)))) cct1))))) cct2))))  HashJoin(mi it1)  HashJoin(mi_idx it2)  HashJoin(mi it1 mi_idx it2)  HashJoin(mc mi it1 mi_idx it2)  HashJoin(cc mc mi it1 mi_idx it2)  HashJoin(cc mc mi it1 mi_idx it2 cct1)  HashJoin(cn cc mc mi it1 mi_idx it2 cct1)  HashJoin(ct cn cc mc mi it1 mi_idx it2 cct1)  HashJoin(t ct cn cc mc mi it1 mi_idx it2 cct1)  HashJoin(kt t ct cn cc mc mi it1 mi_idx it2 cct1)  HashJoin(kt t ct cn cc mc mi it1 mi_idx it2 cct1 cct2)  HashJoin(mk kt t ct cn cc mc mi it1 mi_idx it2 cct1 cct2)  HashJoin(k mk kt t ct cn cc mc mi it1 mi_idx it2 cct1 cct2)
   SeqScan(cc) SeqScan(cct1) SeqScan(cct2) SeqScan(cn) SeqScan(ct) SeqScan(it1) SeqScan(it2) SeqScan(k) SeqScan(kt) SeqScan(mc) SeqScan(mi) SeqScan(mi_idx) SeqScan(mk) SeqScan(t) */
SELECT MIN(cn.name) AS movie_company,
       MIN(mi_idx.info) AS rating,
       MIN(t.title) AS complete_euro_dark_movie
FROM complete_cast AS cc,
     comp_cast_type AS cct1,
     comp_cast_type AS cct2,
     company_name AS cn,
     company_type AS ct,
     info_type AS it1,
     info_type AS it2,
     keyword AS k,
     kind_type AS kt,
     movie_companies AS mc,
     movie_info AS mi,
     movie_info_idx AS mi_idx,
     movie_keyword AS mk,
     title AS t
WHERE cct1.kind = 'cast'
  AND cct2.kind = 'complete'
  AND cn.country_code != '[us]'
  AND it1.info = 'countries'
  AND it2.info = 'rating'
  AND k.keyword IN ('murder',
                    'murder-in-title',
                    'blood',
                    'violence')
  AND kt.kind IN ('movie',
                  'episode')
  AND mc.note NOT LIKE '%(USA)%'
  AND mc.note LIKE '%(200%)%'
  AND mi.info IN ('Sweden',
                  'Norway',
                  'Germany',
                  'Denmark',
                  'Swedish',
                  'Danish',
                  'Norwegian',
                  'German',
                  'USA',
                  'American')
  AND mi_idx.info < '8.5'
  AND t.production_year > 2005
  AND kt.id = t.kind_id
  AND t.id = mi.movie_id
  AND t.id = mk.movie_id
  AND t.id = mi_idx.movie_id
  AND t.id = mc.movie_id
  AND t.id = cc.movie_id
  AND mk.movie_id = mi.movie_id
  AND mk.movie_id = mi_idx.movie_id
  AND mk.movie_id = mc.movie_id
  AND mk.movie_id = cc.movie_id
  AND mi.movie_id = mi_idx.movie_id
  AND mi.movie_id = mc.movie_id
  AND mi.movie_id = cc.movie_id
  AND mc.movie_id = mi_idx.movie_id
  AND mc.movie_id = cc.movie_id
  AND mi_idx.movie_id = cc.movie_id
  AND k.id = mk.keyword_id
  AND it1.id = mi.info_type_id
  AND it2.id = mi_idx.info_type_id
  AND ct.id = mc.company_type_id
  AND cn.id = mc.company_id
  AND cct1.id = cc.subject_id
  AND cct2.id = cc.status_id;
