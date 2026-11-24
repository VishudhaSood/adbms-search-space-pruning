LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder((((d c) b) a))  HashJoin(d c)  HashJoin(d c b)  HashJoin(d c b a)
   SeqScan(a) SeqScan(b) SeqScan(c) SeqScan(d) */
SELECT * FROM d JOIN c ON c.id = d.c_id JOIN b ON b.id = c.b_id JOIN a ON a.id = b.a_id;
