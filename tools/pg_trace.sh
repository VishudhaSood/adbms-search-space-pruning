#!/bin/bash
# Runs every query in tools/queries.txt through PostgreSQL with the trace patch,
# saves the raw log and the EXPLAIN per query, and converts each log to traces/pg_<Q>.json.
#
# Run from /workspaces/pg_dev at the dev@ prompt, after: source /workspaces/pg_dev/env.sh
#   bash tools/pg_trace.sh            # index scans OFF (same operator menu as Calcite)
#   bash tools/pg_trace.sh native     # index scans ON  (PostgreSQL as it normally plans)
set -e
MODE=${1:-fair}
DB=${DB:-test}
OUT=stats/pg_trace_$MODE
mkdir -p "$OUT" traces

SETS="SET max_parallel_workers_per_gather = 0; SET jit = off;"
if [ "$MODE" = "fair" ]; then
  SETS="$SETS SET enable_indexscan = off; SET enable_bitmapscan = off; SET enable_indexonlyscan = off;"
fi

while IFS='|' read -r Q SQL; do
  [ -z "$Q" ] && continue
  # client_min_messages = log sends the TRACE lines to this psql session (stderr)
  psql "$DB" -X -q -P pager=off -c "$SETS SET client_min_messages = log; EXPLAIN $SQL" \
       > "$OUT/$Q.log" 2>&1
  psql "$DB" -X -q -P pager=off -c "$SETS EXPLAIN $SQL" > "$OUT/${Q}_explain.txt"
  SUFFIX=""; [ "$MODE" != "fair" ] && SUFFIX="_$MODE"
  python3 tools/pg_log_to_trace.py "$OUT/$Q.log" --query "$Q" --sql "$SQL" \
       --explain "$OUT/${Q}_explain.txt" -o "traces/pg_${Q}${SUFFIX}.json"
done < tools/queries.txt

echo "Done. Traces in traces/, raw logs in $OUT/"
