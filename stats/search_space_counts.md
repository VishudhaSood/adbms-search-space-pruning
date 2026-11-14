# Search-space counts (test tables a-e)

PG = PostgreSQL, from tools/pg_trace.sh (fair = index scans off; native = normal settings).
Calcite = from SearchTrace in calcite/ (default bottom-up Volcano planner).

| Query | Tables | PG costed | PG precheck | PG rejected | PG evicted | PG kept | PG costed (native) | PG kept (native) | Calcite nodes | logical | physical | rule firings | RelSets | winners | in final plan |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Q1 | 1 | 1 | 0 | 0 | 0 | 1 | 1 | 1 | 7 | 3 | 4 | 3 | 3 | 3 | 3 |
| Q2 | 2 | 16 | 6 | 4 | 2 | 4 | 18 | 5 | 19 | 7 | 12 | 11 | 5 | 5 | 5 |
| Q3 | 2 | 16 | 6 | 4 | 2 | 4 | 18 | 5 | 34 | 13 | 21 | 22 | 8 | 8 | 6 |
| Q4 | 3 | 55 | 29 | 10 | 7 | 9 | 64 | 11 | 132 | 51 | 81 | 100 | 21 | 21 | 9 |
| Q5 | 3 | 55 | 28 | 10 | 8 | 9 | 64 | 11 | 75 | 28 | 47 | 53 | 13 | 13 | 8 |
| Q6 | 4 | 131 | 83 | 17 | 15 | 16 | 154 | 19 | 460 | 182 | 278 | 378 | 53 | 53 | 12 |
| Q7 | 5 | 381 | 278 | 30 | 38 | 35 | 442 | 39 | 1984 | 800 | 1184 | 1768 | 164 | 164 | 15 |
| Q8 | 4 | 131 | 76 | 23 | 16 | 16 | 154 | 19 | 268 | 104 | 164 | 211 | 33 | 33 | 10 |

- PG costed = precheck + kept + rejected (every path PostgreSQL computed a cost for).
- PG kept = paths left in each set's pathlist when set_cheapest ran, summed over all sets.
- Calcite nodes = RelNodes registered in the memo. Nothing is removed during the search.
- PG paths and Calcite nodes are not the same unit; compare how each grows with the number of tables.
