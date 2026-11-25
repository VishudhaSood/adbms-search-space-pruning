#!/usr/bin/env bash
# Re-run every Calcite mode on the test queries (Q1-Q14), so every trace has timestamps, then check them all
# against PostgreSQL. Run from anywhere:   bash tools/run_calcite_modes.sh
# Takes roughly 20-30 minutes (the sort-enforcer modes are slow on Q7, which runs on its own: 1 run, no warm-up).
#
# Mode suffix -> trace files traces/calcite_Q*<suffix>.json, logs stats/calcite_run<suffix>{,_err}.txt
#   ""                         bottom-up + sort enforcer (default)
#   _nlj                       bottom-up + sorts + nested loop for equi-joins
#   _topdown                   top-down + sorts
#   _nosort, _nosort_topdown   without the sort enforcer
#   _nosort_nocross, _nosort_nocross_exchange, _nosort_topdown_nocross, _nosort_topdown_nocross_exchange
set -u
cd "$(dirname "$0")/.."
ALL=$(grep -o '^Q[0-9]*' tools/queries.txt | paste -sd, -)          # Q1,...,Q14
NO_Q7=$(echo "$ALL" | tr ',' '\n' | grep -vx Q7 | paste -sd, -)
export MAVEN_OPTS=${MAVEN_OPTS:--Xmx4g}

run() {   # run <suffix> <mvn args...>
  local suffix=$1; shift
  echo "== calcite_run${suffix}: $*"
  (cd calcite && mvn -q compile exec:java -Dexec.args="$*" \
      > "../stats/calcite_run${suffix}.txt" 2> "../stats/calcite_run${suffix}_err.txt")
  if grep -q "ERROR" "stats/calcite_run${suffix}.txt"; then
    echo "   MAVEN ERROR: $(grep -m1 ERROR "stats/calcite_run${suffix}.txt" | cut -c1-150)"
  fi
  grep -E "FAILED|Not planned" "stats/calcite_run${suffix}_err.txt" | sed 's/^/   /'
}

(cd calcite && mvn -q compile 2>&1 | grep ERROR | head -3)

# sort-enforcer modes: everything but Q7 with a short warm-up, then Q7 alone (minutes per plan)
run ""                 "warmup=3 reps=3 only=$NO_Q7"
run "_q7"              "warmup=0 reps=1 only=Q7"
run "_nlj"             "nlj warmup=3 reps=3 only=$NO_Q7"
run "_nlj_q7"          "nlj warmup=0 reps=1 only=Q7"
run "_topdown"         "topdown warmup=3 reps=3 only=$NO_Q7"
run "_topdown_q7"      "topdown warmup=0 reps=1 only=Q7"
# no sort enforcer: fast, full warm-up
run "_nosort"                          "nosort warmup=30 only=$ALL"
run "_nosort_topdown"                  "nosort topdown warmup=30 only=$ALL"
run "_nosort_nocross"                  "nosort nocross warmup=30 only=$ALL"
run "_nosort_nocross_exchange"         "nosort nocross exchange warmup=30 only=$ALL"
run "_nosort_topdown_nocross"          "topdown nosort nocross warmup=30 only=$ALL"
run "_nosort_topdown_nocross_exchange" "topdown nosort nocross exchange warmup=30 only=$ALL"

echo
echo "== checks against PostgreSQL (expected: Q8 differs in _topdown and _nosort_topdown; Q7 in the two nocross modes without exchange)"
for s in "" _nlj _topdown _nosort _nosort_topdown _nosort_nocross _nosort_nocross_exchange \
         _nosort_topdown_nocross _nosort_topdown_nocross_exchange; do
  printf "%-36s " "${s:-(default)}"
  python3 tools/check_day1.py $s > /tmp/check$s.txt 2>&1 && echo "all match" \
    || echo "differs: $(grep -o 'FAIL: Q[0-9]*' /tmp/check$s.txt | sed 's/FAIL: //' | sort -u | paste -sd' ' -)"
done
echo
echo "== timestamps: traces without t_us"
python3 - <<'EOF'
import glob, json
missing = [f for f in sorted(glob.glob("traces/calcite_Q*.json"))
           if not (lambda t: t.get("events") and "t_us" in t["events"][0])(json.load(open(f)))]
print("   none" if not missing else "   " + " ".join(missing))
EOF
