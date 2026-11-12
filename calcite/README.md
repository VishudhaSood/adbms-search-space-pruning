# Calcite Planner

Plans queries using Apache Calcite with PostgreSQL's statistics and cost model.

## Prerequisites
- The dev container (JDK 17, Maven)
- PostgreSQL running with the `test` database and tables a, b, c, d, e
- `stats/test_tables.json` up to date (`psql test -q -f sql/extract_stats.sql -o stats/test_tables.json`)

## Run
```bash
cd /workspaces/pg_dev/calcite
mvn -q compile exec:java                 # prints the plans, writes ../traces/calcite_Q*.json
```
