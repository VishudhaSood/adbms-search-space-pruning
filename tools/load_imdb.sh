#!/bin/bash
# Workstream D: load the full IMDB (JOB) into database imdb.
# Schema: imdb_data/job/schema.sql (primary keys only; fkindexes.sql is skipped: index scans are off anyway).
# Data: imdb_data/csv/*.csv (May 2013 snapshot). The CSVs use backslash escapes, hence escape '\'.
# Run from /workspaces/pg_dev after: source env.sh
#   nohup bash tools/load_imdb.sh > imdb_data/load.log 2>&1 &
set -e
DATA=${DATA:-/workspaces/pg_dev/imdb_data}
DB=${DB:-imdb}
createdb "$DB"
psql "$DB" -X -q -v ON_ERROR_STOP=1 -f "$DATA/job/schema.sql"
for f in "$DATA"/csv/*.csv; do
  t=$(basename "$f" .csv)
  s=$(date +%s)
  psql "$DB" -X -q -v ON_ERROR_STOP=1 -c "\copy $t from '$f' with (format csv, escape '\\')"
  echo "$(date +%H:%M:%S) $t loaded in $(( $(date +%s) - s ))s"
done
echo "$(date +%H:%M:%S) VACUUM ANALYZE ..."
psql "$DB" -X -q -c "VACUUM ANALYZE"
psql "$DB" -X -At -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname"
psql "$DB" -X -At -c "SELECT pg_size_pretty(pg_database_size('$DB'))"
echo "$(date +%H:%M:%S) DONE"
