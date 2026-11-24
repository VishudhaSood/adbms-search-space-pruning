LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder(((c b) a))  HashJoin(c b)  HashJoin(c b a)
   SeqScan(a) SeqScan(b) SeqScan(c) */
SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id;
