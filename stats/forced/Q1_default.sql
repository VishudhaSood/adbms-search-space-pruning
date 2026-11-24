LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   SeqScan(a) */
SELECT * FROM a WHERE x = 3;
