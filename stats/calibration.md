# Calibration: PostgreSQL EXPLAIN vs Calcite (PG stats + PG cost model)

| Query | Operator | PG rows | Calcite rows | q-error | PG cost | Calcite cost | cost ratio |
|---|---|---|---|---|---|---|---|
| Q1 | Scan a + filter x=3 | 100 | 100 | 1.00 | 0.00..17.50 | 0.00..17.50 | 1.000 |
| Q2 | Scan b | 5000 | 5000 | 1.00 | 0.00..78.00 | 0.00..78.00 | 1.000 |
| Q2 | Scan a | 1000 | 1000 | 1.00 | 0.00..15.00 | 0.00..15.00 | 1.000 |
| Q2 | Hash join a⋈b | 5000 | 5000 | 1.00 | 27.50..118.68 | 27.50..118.68 | 1.000 |
| Q3 | Hash join a⋈b (x=3) | 500 | 500 | 1.00 | 18.75..109.93 | 18.75..109.93 | 1.000 |
| Q4 | Scan c | 20000 | 20000 | 1.00 | 0.00..309.00 | 0.00..309.00 | 1.000 |
| Q4 | Hash join (a⋈b)⋈c | 2000 | 2000 | 1.00 | 116.18..520.18 | 116.18..520.18 | 1.000 |
| Q5 | Hash join c⋈b | 20000 | 20000 | 1.00 | 140.50..502.04 | 140.50..502.04 | 1.000 |
| Q5 | Hash join (c⋈b)⋈a | 20000 | 20000 | 1.00 | 168.00..582.27 | 168.00..582.27 | 1.000 |

Join order: same as PostgreSQL for Q2-Q5 (same build/probe sides).
Sources: stats/pg_explain_vishudha.txt (PG), stats/calcite_final_12Nov.txt (Calcite).
Limits: one hash batch, bucket clamps = 1, uniqueness only for base tables,
merge/NL joins simplified, in-memory sort only, ranges/LIKE/IN use Calcite's default selectivity.
