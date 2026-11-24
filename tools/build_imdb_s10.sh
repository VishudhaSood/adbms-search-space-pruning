#!/usr/bin/env bash
# Build the correlated IMDB sample as its own database (Workstream D), from the full imdb database.
#
#   bash tools/build_imdb_s10.sh            # p = 0.1  -> database imdb_s10
#   bash tools/build_imdb_s10.sh 0.05       # another rate (the database is still called imdb_s10 unless DST_DB is set)
#   NO_JOB_CHECK=1 bash tools/build_imdb_s10.sh     # skip step 5
#
# Steps:
#   1. sql/sample_imdb.sql builds schema s10 inside imdb and prints the checks  -> stats/imdb_s10_build.txt
#   2. copies schema s10 into a fresh database imdb_s10 and renames it to public; the bookkeeping tables
#      (_sample_info, _check_*) go to schema sample_meta so they don't show up as JOB tables
#   3. VACUUM ANALYZE
#   4. sql/extract_stats.sql                                                   -> stats/imdb_s10_tables.json
#   5. runs every JOB query on the sample (fair mode, geqo off, 5 min timeout) -> stats/imdb_s10_job_check.tsv
#      status: ok = at least one non-NULL value; empty = every MIN() is NULL, i.e. no matching rows
# Needs: env.sh sourced, PostgreSQL running, the full imdb loaded and ANALYZEd, JOB queries in job/.
set -euo pipefail
cd "$(dirname "$0")/.."

P=${1:-0.1}
SRC=${SRC_DB:-imdb}
DST=${DST_DB:-imdb_s10}
JOB_DIR=${JOB_DIR:-job}
mkdir -p stats

echo "== 1. sampling $SRC at p = $P (schema s10)"
psql -X -v ON_ERROR_STOP=1 -v p="$P" -d "$SRC" -f sql/sample_imdb.sql | tee "stats/${DST}_build.txt"

echo "== 2. copying s10 into database $DST"
dropdb --if-exists "$DST"
createdb "$DST"
pg_dump -d "$SRC" -n s10 --no-owner --no-privileges | psql -X -q -v ON_ERROR_STOP=1 -d "$DST" > /dev/null
psql -X -q -v ON_ERROR_STOP=1 -d "$DST" <<'SQL'
DROP SCHEMA public CASCADE;
ALTER SCHEMA s10 RENAME TO public;
CREATE SCHEMA sample_meta;
ALTER TABLE public._sample_info   SET SCHEMA sample_meta;
ALTER TABLE public._check_rows    SET SCHEMA sample_meta;
ALTER TABLE public._check_joins   SET SCHEMA sample_meta;
ALTER TABLE public._check_losses  SET SCHEMA sample_meta;
SQL
psql -X -At -d "$DST" -c "SELECT count(*) || ' tables in public' FROM pg_tables WHERE schemaname = 'public'"

echo "== 3. VACUUM ANALYZE"
psql -X -q -d "$DST" -c "VACUUM ANALYZE"

echo "== 4. stats for Calcite -> stats/${DST}_tables.json"
psql -X -q -d "$DST" -f sql/extract_stats.sql > "stats/${DST}_tables.json"
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(len(d['tables']), 'tables in the stats file')" \
  "stats/${DST}_tables.json"

if [ -n "${NO_JOB_CHECK:-}" ]; then echo "== 5. skipped (NO_JOB_CHECK)"; exit 0; fi
echo "== 5. every JOB query on $DST -> stats/${DST}_job_check.tsv"
OUT="stats/${DST}_job_check.tsv"
printf "query\tstatus\tseconds\n" > "$OUT"
SETTINGS="SET statement_timeout = '5min'; SET geqo = off; SET max_parallel_workers_per_gather = 0;
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;"
for f in $(ls "$JOB_DIR"/[0-9]*.sql | sort -V); do
  q=$(basename "$f" .sql)
  start=$(date +%s.%N)
  if res=$( { echo "$SETTINGS"; cat "$f"; } | psql -X -q -At -v ON_ERROR_STOP=1 -d "$DST" 2>&1 ); then
    last=$(printf "%s\n" "$res" | tail -1)
    if [[ "$last" =~ ^\|*$ ]]; then status=empty; else status=ok; fi   # only separators = every MIN() is NULL
  elif printf "%s" "$res" | grep -q "statement timeout"; then status=timeout
  else status="error: $(printf "%s" "$res" | grep -m1 ERROR | cut -c1-80)"
  fi
  secs=$(awk -v s="$start" -v e="$(date +%s.%N)" 'BEGIN{print e-s}')
  printf "%s\t%s\t%.1f\n" "$q" "$status" "$secs" >> "$OUT"
  printf "%-5s %-8s %6.1fs\n" "$q" "$status" "$secs"
done
echo "== summary"
cut -f2 "$OUT" | tail -n +2 | sed 's/:.*//' | sort | uniq -c
