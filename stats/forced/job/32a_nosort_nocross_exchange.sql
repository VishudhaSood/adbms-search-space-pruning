LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off; SET jit = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder((t2 (lt (ml (t1 (mk k))))))  HashJoin(mk k)  HashJoin(t1 mk k)  HashJoin(ml t1 mk k)  HashJoin(lt ml t1 mk k)  HashJoin(t2 lt ml t1 mk k)
   SeqScan(k) SeqScan(lt) SeqScan(mk) SeqScan(ml) SeqScan(t1) SeqScan(t2) */
SELECT MIN(lt.link) AS link_type,
       MIN(t1.title) AS first_movie,
       MIN(t2.title) AS second_movie
FROM keyword AS k,
     link_type AS lt,
     movie_keyword AS mk,
     movie_link AS ml,
     title AS t1,
     title AS t2
WHERE k.keyword ='10,000-mile-club'
  AND mk.keyword_id = k.id
  AND t1.id = mk.movie_id
  AND ml.movie_id = t1.id
  AND ml.linked_movie_id = t2.id
  AND lt.id = ml.link_type_id
  AND mk.movie_id = t1.id;
