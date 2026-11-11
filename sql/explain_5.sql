SET max_parallel_workers_per_gather = 0;
SET jit = off;
EXPLAIN SELECT * FROM a WHERE x = 3;
EXPLAIN SELECT * FROM a JOIN b ON a.id = b.a_id;
EXPLAIN SELECT * FROM a JOIN b ON a.id = b.a_id WHERE a.x = 3;
EXPLAIN SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id WHERE a.x = 3;
EXPLAIN SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id;
