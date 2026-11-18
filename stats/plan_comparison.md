# Plan comparison: PostgreSQL vs Calcite (fair mode, Q1 to Q8)

Both optimizers use the same statistics and the same cost formulas (task i), so any difference
would come from the search. Source: `stats/pg_trace_fair/Q*_explain.txt` and
`stats/calcite_run_14Nov.txt`, after the `innerUnique` fix in `PgCostModel.java`.

In a hash join, "probe X, hash Y" means X is the outer (probe) side and Y is hashed (build side).
PostgreSQL shows the build side under `Hash`; in Calcite's `EnumerableHashJoin` it is the right input.

| Query | Tables | Join order (bottom-up) | PostgreSQL plan | Calcite plan | Cost (both) | Rows | Same? | Why |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Q1 | 1 | a | Seq scan a, filter x = 3 | Same | 0.00..17.50 | 100 | Yes | One table, nothing to choose |
| Q2 | 2 | a, b | probe b, hash a | Same | 27.50..118.68 | 5000 | Yes | Hash the smaller table (a, 1000 rows) |
| Q3 | 2 | σa, b | probe b, hash σa | Same | 18.75..109.93 | 500 | Yes | Filtered a is smallest (100 rows) |
| Q4 | 3 | σa, b, c | probe c, hash (probe b, hash σa) | Same | 116.18..520.18 | 2000 | Yes | Same costs, same space |
| Q5 | 3 | b, c, then a | probe (probe c, hash b), hash a | Same | 168.00..582.27 | 20000 | Yes | Same costs, same space |
| Q6 | 4 | σa, b, c, d | probe d, hash [Q4 plan] | Same | 545.18..747.68 | 1000 | Yes | Same costs, same space |
| Q7 | 5 | σa, e, b, c, d | probe d, hash [probe c, hash [probe b, hash (probe e, hash σa)]] | Same (after fix) | 537.56..735.06 | 500 | Yes | Before the fix Calcite joined σa⋈b first and then hashed e (732.62) because it under-costed hashing e |
| Q8 | 4 | c, d, then b, a | probe (probe (probe d, hash c), hash b), hash a | Same (after fix) | 727.00..960.88 | 10000 | Yes | Before the fix Calcite hashed d instead of c (862.14) because it under-costed hashing d |

All final joins are hash joins. In Calcite, merge join never really competed: it is generated for
every equi-join, but none of the 450 merge joins across Q1 to Q8 gets a finite cost, because their
sorted inputs (`AbstractConverter` placeholders) are never turned into an `EnumerableSort`.
Nested loop appears in Calcite only for cross products. PostgreSQL costs all three join methods
for every table pair.

## The innerUnique bug (found on Q7 and Q8)

`PgCostModel.innerUnique` treated `n_distinct = -1` as proof of a unique key. `d.c_id` and `e.a_id`
are unique in the data but have no primary key or unique index, so PostgreSQL uses the normal
hash-join cost for them. Calcite used the cheaper "stop at first match" cost:

| Join | PostgreSQL (log) | Calcite before fix | PostgreSQL's choice for that set |
| --- | --- | --- | --- |
| Q8: probe c, hash d | 280.00..764.00 | 280.00..641.51 | probe d, hash c: 559.00..740.25 |
| Q7: probe a⋈b, hash e | 33.00..128.56 | 33.00..125.49 | probe b, hash a⋈e: 28.69..127.94 |

Fix: only columns with a primary key (`id`) count as unique. After it, all 8 plans match.

**Finding:** with the same costs, the System R DP and the Volcano memo pick the same winner on all
8 queries. The only difference left is the size of the search (see `search_space_counts.md`).
