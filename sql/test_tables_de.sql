-- Two more small tables for 4- and 5-table queries (week 3).
-- Same style as test_tables.sql; a, b, c are left as they are.
DROP TABLE IF EXISTS d, e;
CREATE TABLE d (id int PRIMARY KEY, c_id int, w int);
CREATE TABLE e (id int PRIMARY KEY, a_id int, v int);
INSERT INTO d SELECT g, g % 20000 + 1, g % 5 FROM generate_series(1, 10000) g;
INSERT INTO e SELECT g, g % 1000 + 1, g % 4 FROM generate_series(1, 500) g;
ANALYZE;
