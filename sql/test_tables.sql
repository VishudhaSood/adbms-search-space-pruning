DROP TABLE IF EXISTS a, b, c;
CREATE TABLE a (id int PRIMARY KEY, x int);
CREATE TABLE b (id int PRIMARY KEY, a_id int, y int);
CREATE TABLE c (id int PRIMARY KEY, b_id int, z int);
INSERT INTO a SELECT g, g % 10 FROM generate_series(1, 1000) g;
INSERT INTO b SELECT g, g % 1000 + 1, g % 7 FROM generate_series(1, 5000) g;
INSERT INTO c SELECT g, g % 5000 + 1, g % 3 FROM generate_series(1, 20000) g;
ANALYZE;
