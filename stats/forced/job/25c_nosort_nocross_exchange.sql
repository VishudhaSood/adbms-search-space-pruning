LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off; SET jit = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder((((mk k) (((mi it1) (ci (mi_idx it2))) n)) t))  HashJoin(mk k)  HashJoin(mi it1)  HashJoin(mi_idx it2)  HashJoin(ci mi_idx it2)  HashJoin(mi it1 ci mi_idx it2)  HashJoin(mi it1 ci mi_idx it2 n)  HashJoin(mk k mi it1 ci mi_idx it2 n)  HashJoin(mk k mi it1 ci mi_idx it2 n t)
   SeqScan(ci) SeqScan(it1) SeqScan(it2) SeqScan(k) SeqScan(mi) SeqScan(mi_idx) SeqScan(mk) SeqScan(n) SeqScan(t) */
SELECT MIN(mi.info) AS movie_budget,
       MIN(mi_idx.info) AS movie_votes,
       MIN(n.name) AS male_writer,
       MIN(t.title) AS violent_movie_title
FROM cast_info AS ci,
     info_type AS it1,
     info_type AS it2,
     keyword AS k,
     movie_info AS mi,
     movie_info_idx AS mi_idx,
     movie_keyword AS mk,
     name AS n,
     title AS t
WHERE ci.note IN ('(writer)',
                  '(head writer)',
                  '(written by)',
                  '(story)',
                  '(story editor)')
  AND it1.info = 'genres'
  AND it2.info = 'votes'
  AND k.keyword IN ('murder',
                    'violence',
                    'blood',
                    'gore',
                    'death',
                    'female-nudity',
                    'hospital')
  AND mi.info IN ('Horror',
                  'Action',
                  'Sci-Fi',
                  'Thriller',
                  'Crime',
                  'War')
  AND n.gender = 'm'
  AND t.id = mi.movie_id
  AND t.id = mi_idx.movie_id
  AND t.id = ci.movie_id
  AND t.id = mk.movie_id
  AND ci.movie_id = mi.movie_id
  AND ci.movie_id = mi_idx.movie_id
  AND ci.movie_id = mk.movie_id
  AND mi.movie_id = mi_idx.movie_id
  AND mi.movie_id = mk.movie_id
  AND mi_idx.movie_id = mk.movie_id
  AND n.id = ci.person_id
  AND it1.id = mi.info_type_id
  AND it2.id = mi_idx.info_type_id
  AND k.id = mk.keyword_id;
