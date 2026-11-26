LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off; SET jit = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder(((mk k) (((t kt) ((mi it1) ((mc cn) (cc cct1)))) ct)))  HashJoin(mk k)  HashJoin(t kt)  HashJoin(mi it1)  HashJoin(mc cn)  HashJoin(cc cct1)  HashJoin(mc cn cc cct1)  HashJoin(mi it1 mc cn cc cct1)  HashJoin(t kt mi it1 mc cn cc cct1)  HashJoin(t kt mi it1 mc cn cc cct1 ct)  HashJoin(mk k t kt mi it1 mc cn cc cct1 ct)
   SeqScan(cc) SeqScan(cct1) SeqScan(cn) SeqScan(ct) SeqScan(it1) SeqScan(k) SeqScan(kt) SeqScan(mc) SeqScan(mi) SeqScan(mk) SeqScan(t) */
SELECT MIN(kt.kind) AS movie_kind,
       MIN(t.title) AS complete_nerdy_internet_movie
FROM complete_cast AS cc,
     comp_cast_type AS cct1,
     company_name AS cn,
     company_type AS ct,
     info_type AS it1,
     keyword AS k,
     kind_type AS kt,
     movie_companies AS mc,
     movie_info AS mi,
     movie_keyword AS mk,
     title AS t
WHERE cct1.kind = 'complete+verified'
  AND cn.country_code = '[us]'
  AND it1.info = 'release dates'
  AND k.keyword IN ('nerd',
                    'loner',
                    'alienation',
                    'dignity')
  AND kt.kind IN ('movie')
  AND mi.note LIKE '%internet%'
  AND mi.info LIKE 'USA:% 200%'
  AND t.production_year > 2000
  AND kt.id = t.kind_id
  AND t.id = mi.movie_id
  AND t.id = mk.movie_id
  AND t.id = mc.movie_id
  AND t.id = cc.movie_id
  AND mk.movie_id = mi.movie_id
  AND mk.movie_id = mc.movie_id
  AND mk.movie_id = cc.movie_id
  AND mi.movie_id = mc.movie_id
  AND mi.movie_id = cc.movie_id
  AND mc.movie_id = cc.movie_id
  AND k.id = mk.keyword_id
  AND it1.id = mi.info_type_id
  AND cn.id = mc.company_id
  AND ct.id = mc.company_type_id
  AND cct1.id = cc.status_id;
