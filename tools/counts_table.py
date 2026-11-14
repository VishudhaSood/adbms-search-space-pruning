import json
rows = []
for q in [f"Q{i}" for i in range(1, 9)]:
    p = json.load(open(f"traces/pg_{q}.json")); n = json.load(open(f"traces/pg_{q}_native.json"))
    c = json.load(open(f"traces/calcite_{q}.json"))
    a, b, s = p["summary"], n["summary"], c["summary"]
    rows.append(f"| {q} | {a['tables']} | {a['considered']} | {a['pruned_precheck']} | {a['pruned_on_arrival']} | {a['evicted_later']} | {a['retained']} | {b['considered']} | {b['retained']} | {s['registered']} | {s['registered_logical']} | {s['registered_physical']} | {s['rules_produced']} | {s['relsets']} | {s['winners']} | {s['chosen']} |")
out = """# Search-space counts (test tables a-e)

PG = PostgreSQL, from tools/pg_trace.sh (fair = index scans off; native = normal settings).
Calcite = from SearchTrace in calcite/ (default bottom-up Volcano planner).

| Query | Tables | PG costed | PG precheck | PG rejected | PG evicted | PG kept | PG costed (native) | PG kept (native) | Calcite nodes | logical | physical | rule firings | RelSets | winners | in final plan |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
""" + "\n".join(rows) + """

- PG costed = precheck + kept + rejected (every path PostgreSQL computed a cost for).
- PG kept = paths left in each set's pathlist when set_cheapest ran, summed over all sets.
- Calcite nodes = RelNodes registered in the memo. Nothing is removed during the search.
- PG paths and Calcite nodes are not the same unit; compare how each grows with the number of tables.
"""
open("stats/search_space_counts.md", "w").write(out)
print(out)
