LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder((d (c (b (e a)))))  HashJoin(e a)  HashJoin(b e a)  HashJoin(c b e a)  HashJoin(d c b e a)
   SeqScan(a) SeqScan(b) SeqScan(c) SeqScan(d) SeqScan(e) */
SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id JOIN d ON c.id = d.c_id JOIN e ON a.id = e.a_id WHERE a.x = 3;
