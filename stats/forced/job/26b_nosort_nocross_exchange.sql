LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off; SET jit = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder((n ((t ((mk k) (((ci chn) (mi_idx it2)) ((cc cct1) cct2)))) kt)))  HashJoin(mk k)  HashJoin(ci chn)  HashJoin(mi_idx it2)  HashJoin(ci chn mi_idx it2)  HashJoin(cc cct1)  HashJoin(cc cct1 cct2)  HashJoin(ci chn mi_idx it2 cc cct1 cct2)  HashJoin(mk k ci chn mi_idx it2 cc cct1 cct2)  HashJoin(t mk k ci chn mi_idx it2 cc cct1 cct2)  HashJoin(t mk k ci chn mi_idx it2 cc cct1 cct2 kt)  HashJoin(n t mk k ci chn mi_idx it2 cc cct1 cct2 kt)
   SeqScan(cc) SeqScan(cct1) SeqScan(cct2) SeqScan(chn) SeqScan(ci) SeqScan(it2) SeqScan(k) SeqScan(kt) SeqScan(mi_idx) SeqScan(mk) SeqScan(n) SeqScan(t) */
SELECT MIN(chn.name) AS character_name,
       MIN(mi_idx.info) AS rating,
       MIN(t.title) AS complete_hero_movie
FROM complete_cast AS cc,
     comp_cast_type AS cct1,
     comp_cast_type AS cct2,
     char_name AS chn,
     cast_info AS ci,
     info_type AS it2,
     keyword AS k,
     kind_type AS kt,
     movie_info_idx AS mi_idx,
     movie_keyword AS mk,
     name AS n,
     title AS t
WHERE cct1.kind = 'cast'
  AND cct2.kind LIKE '%complete%'
  AND chn.name IS NOT NULL
  AND (chn.name LIKE '%man%'
       OR chn.name LIKE '%Man%')
  AND it2.info = 'rating'
  AND k.keyword IN ('superhero',
                    'marvel-comics',
                    'based-on-comic',
                    'fight')
  AND kt.kind = 'movie'
  AND mi_idx.info > '8.0'
  AND t.production_year > 2005
  AND kt.id = t.kind_id
  AND t.id = mk.movie_id
  AND t.id = ci.movie_id
  AND t.id = cc.movie_id
  AND t.id = mi_idx.movie_id
  AND mk.movie_id = ci.movie_id
  AND mk.movie_id = cc.movie_id
  AND mk.movie_id = mi_idx.movie_id
  AND ci.movie_id = cc.movie_id
  AND ci.movie_id = mi_idx.movie_id
  AND cc.movie_id = mi_idx.movie_id
  AND chn.id = ci.person_role_id
  AND n.id = ci.person_id
  AND k.id = mk.keyword_id
  AND cct1.id = cc.subject_id
  AND cct2.id = cc.status_id
  AND it2.id = mi_idx.info_type_id;
