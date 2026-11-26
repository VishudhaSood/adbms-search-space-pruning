LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off; SET jit = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder(((((ci rt) (mc cn)) (an1 n1)) t))  HashJoin(ci rt)  HashJoin(mc cn)  HashJoin(ci rt mc cn)  HashJoin(an1 n1)  HashJoin(ci rt mc cn an1 n1)  HashJoin(ci rt mc cn an1 n1 t)
   SeqScan(an1) SeqScan(ci) SeqScan(cn) SeqScan(mc) SeqScan(n1) SeqScan(rt) SeqScan(t) */
SELECT MIN(an1.name) AS costume_designer_pseudo,
       MIN(t.title) AS movie_with_costumes
FROM aka_name AS an1,
     cast_info AS ci,
     company_name AS cn,
     movie_companies AS mc,
     name AS n1,
     role_type AS rt,
     title AS t
WHERE cn.country_code ='[us]'
  AND rt.role ='costume designer'
  AND an1.person_id = n1.id
  AND n1.id = ci.person_id
  AND ci.movie_id = t.id
  AND t.id = mc.movie_id
  AND mc.company_id = cn.id
  AND ci.role_id = rt.id
  AND an1.person_id = ci.person_id
  AND ci.movie_id = mc.movie_id;
