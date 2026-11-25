package adbms;

import java.util.List;
import org.apache.calcite.adapter.enumerable.EnumerableHashJoin;
import org.apache.calcite.adapter.enumerable.EnumerableMergeJoin;
import org.apache.calcite.adapter.enumerable.EnumerableNestedLoopJoin;
import org.apache.calcite.plan.RelOptCost;
import org.apache.calcite.plan.RelOptUtil;
import org.apache.calcite.plan.volcano.RelSubset;
import org.apache.calcite.rel.RelNode;
import org.apache.calcite.rel.core.Filter;
import org.apache.calcite.rel.core.Join;
import org.apache.calcite.rel.core.JoinInfo;
import org.apache.calcite.rel.core.Project;
import org.apache.calcite.rel.core.Sort;
import org.apache.calcite.rel.core.TableScan;
import org.apache.calcite.rel.metadata.BuiltInMetadata;
import org.apache.calcite.rel.metadata.RelMetadataQuery;
import org.apache.calcite.rex.RexInputRef;
import org.apache.calcite.rex.RexNode;

/**
 * Per-node (non-cumulative) cost with PostgreSQL's costsize.c formulas.
 * The planner adds the inputs' costs, so a node's cumulative cost = PG's total_cost.
 * Methods for specific classes, because Calcite picks the most specific handler method.
 */
public class PgCostModel implements BuiltInMetadata.NonCumulativeCost.Handler {
  private final PgStats stats;
  private final double seqPage, cpuTuple, cpuOp;

  public PgCostModel(PgStats stats) {
    this.stats = stats;
    this.seqPage = stats.costParams.get("seq_page_cost");
    this.cpuTuple = stats.costParams.get("cpu_tuple_cost");
    this.cpuOp = stats.costParams.get("cpu_operator_cost");
  }

  /** Fallback for operators we don't model: Calcite's own estimate. */
  @Override public RelOptCost getNonCumulativeCost(RelNode rel, RelMetadataQuery mq) {
    return rel.computeSelfCost(rel.getCluster().getPlanner(), mq);
  }

  /** cost_seqscan: relpages * seq_page_cost + reltuples * cpu_tuple_cost (filter is a separate node). */
  public RelOptCost getNonCumulativeCost(TableScan scan, RelMetadataQuery mq) {
    List<String> name = scan.getTable().getQualifiedName();
    PgStats.Table t = stats.table(name.get(name.size() - 1));
    if (t == null) return getNonCumulativeCost((RelNode) scan, mq);
    return new PgCost(t.reltuples, 0, t.relpages * seqPage + t.reltuples * cpuTuple);
  }

  /** The qual part of cost_seqscan: rows_in * n_quals * cpu_operator_cost. */
  public RelOptCost getNonCumulativeCost(Filter f, RelMetadataQuery mq) {
    int nQuals = RelOptUtil.conjunctions(f.getCondition()).size();
    return new PgCost(rows(f, mq), 0, rows(f.getInput(), mq) * nQuals * cpuOp);
  }

  /** PG doesn't charge for a plain column list. */
  public RelOptCost getNonCumulativeCost(Project p, RelMetadataQuery mq) {
    return PgCost.ZERO;
  }

  /** cost_sort, in-memory case: startup = input + 2*op*N*log2(N), run = op*N. */
  public RelOptCost getNonCumulativeCost(Sort s, RelMetadataQuery mq) {
    double n = Math.max(2, rows(s.getInput(), mq));
    double compare = 2 * cpuOp * n * (Math.log(n) / Math.log(2));
    double run = cpuOp * n;
    return new PgCost(n, runCost(s.getInput(), mq) + compare, compare + run);
  }

  /**
   * initial/final_cost_hashjoin. Right input = inner (hashed), left = outer (probe).
   * Assumes one batch (inner fits in hash_mem). Rows per bucket follow estimate_hash_bucket_stats (see
   * innerBucketSize): 1 for unique keys, more for duplicate keys (Q13: c.b_id has 4 rows per value).
   */
  public RelOptCost getNonCumulativeCost(EnumerableHashJoin j, RelMetadataQuery mq) {
    JoinInfo ji = j.analyzeCondition();
    int k = Math.max(1, ji.leftKeys.size());
    double outer = rows(j.getLeft(), mq), inner = rows(j.getRight(), mq), out = rows(j, mq);

    double build = inner * (cpuOp * k + cpuTuple);   // hash every inner row (startup)
    double probe = cpuOp * k * outer;                 // hash every outer row
    double bucket, passing;
    if (innerUnique(j.getRight(), ji.rightKeys)) {    // PG stops at the first match
      double matched = Math.rint(outer * (out / (outer * inner)));
      bucket = cpuOp * k * matched * 0.5 + cpuOp * k * (outer - matched) * 0.05;
      passing = matched;
    } else {                                          // each probe scans half of its bucket
      double perBucket = clampRows(inner * innerBucketSize(j.getRight(), ji.rightKeys, inner, mq));
      bucket = cpuOp * k * outer * perBucket * 0.5;
      passing = out;
    }
    double run = probe + bucket + cpuTuple * passing;
    return new PgCost(out, runCost(j.getRight(), mq) + build, build + run);
  }

  /**
   * initial/final_cost_mergejoin for full merges (both inputs read to the end). Inner rows with duplicate keys are
   * re-read: rescanratio = 1 + (output rows - inner rows) / inner rows. Run cost = comparisons on outer rows and
   * re-read inner rows + cpu_tuple_cost per output row + the extra inner re-reads, either re-running the inner
   * input (inner run cost x rescanratio) or reading a Materialize (inner run cost + cpu_operator_cost per re-read
   * row), whichever is cheaper; an inner that isn't a Sort must be materialized (a seq scan can't mark/restore).
   * The inputs' own startup and one run are already in their cumulative cost, so only the extra re-reads are added.
   * Checked on Q11 (1170.39) and Q12 (4775.54) against PostgreSQL's EXPLAIN.
   */
  public RelOptCost getNonCumulativeCost(EnumerableMergeJoin j, RelMetadataQuery mq) {
    int k = Math.max(1, j.analyzeCondition().leftKeys.size());
    double outer = rows(j.getLeft(), mq), inner = rows(j.getRight(), mq), out = rows(j, mq);
    double rescanned = Math.max(0, out - inner);
    double rescanRatio = 1 + rescanned / Math.max(1, inner);
    double innerRun = runCost(j.getRight(), mq);
    double bare = innerRun * rescanRatio;
    double mat = innerRun + cpuOp * inner * rescanRatio;
    double innerCost = isSort(j.getRight()) ? Math.min(bare, mat) : mat;
    double run = cpuOp * k * (outer + inner * rescanRatio) + cpuTuple * out + (innerCost - innerRun);
    return new PgCost(out, 0, run);
  }

  /** final_cost_nestloop, simplified (no Materialize): rescan inner per outer row. */
  public RelOptCost getNonCumulativeCost(EnumerableNestedLoopJoin j, RelMetadataQuery mq) {
    int nq = RelOptUtil.conjunctions(j.getCondition()).size();
    double outer = rows(j.getLeft(), mq), inner = rows(j.getRight(), mq), out = rows(j, mq);
    double run = (outer - 1) * runCost(j.getRight(), mq)
        + outer * inner * (cpuTuple + nq * cpuOp);
    return new PgCost(out, 0, run);
  }

  // ---------- helpers ----------

  /** clamp_row_est: round, at least 1. */
  private static double clampRows(double r) {
    return r <= 1 ? 1 : Math.rint(r);
  }

  private static boolean isSort(RelNode r) {
    if (r instanceof RelSubset s) r = s.getBest() != null ? s.getBest() : s.getOriginal();
    return r instanceof Sort;
  }

  /**
   * estimate_hash_bucket_stats + ExecChooseHashTableSize: the fraction of inner rows in one hash bucket, smallest
   * over the hash keys. nbuckets = next power of 2 of the inner rows (at least 1024, at most what hash_mem =
   * 2 x work_mem holds). ndistinct of the key's base column is scaled by the base table's filtered rows, the
   * fraction is 1/nbuckets or 1/ndistinct, raised for skew (first MCV frequency over the average frequency),
   * and clamped to [1e-6, 1]. A key with no statistics gives PostgreSQL's default of 0.1.
   */
  private double innerBucketSize(RelNode innerRel, List<Integer> keys, double innerRows, RelMetadataQuery mq) {
    double workMemKb = stats.costParams.getOrDefault("work_mem", 4096.0);
    double maxPointers = workMemKb * 1024 * 2.0 / 8;            // hash_mem / sizeof(pointer)
    double pow2 = nextPow2(maxPointers);
    if (pow2 != maxPointers) maxPointers = pow2 / 2;
    double nbuckets = nextPow2(Math.max(1024, Math.min(Math.ceil(innerRows), maxPointers)));
    double best = 1.0;
    for (int key : keys) {
      Object[] v = baseVar(innerRel, key, mq);
      PgStats.Column c = v == null ? null : stats.column((String) v[0], (String) v[1]);
      PgStats.Table t = v == null ? null : stats.table((String) v[0]);
      if (c == null || t == null || t.reltuples <= 0) { best = Math.min(best, 0.1); continue; }
      double nd = c.nDistinctRaw >= 0 ? c.nDistinctRaw : -c.nDistinctRaw * t.reltuples;
      if (nd <= 0) { best = Math.min(best, 0.1); continue; }
      double avgFreq = (1 - c.nullFrac) / nd;
      nd = clampRows(nd * (double) v[2] / t.reltuples);        // restriction clauses on the base table
      double frac = nd > nbuckets ? 1.0 / nbuckets : 1.0 / nd;
      double mcv = c.mcvFreqs.isEmpty() ? 0 : c.mcvFreqs.get(0);
      if (avgFreq > 0 && mcv > avgFreq) frac *= mcv / avgFreq;
      best = Math.min(best, Math.max(1.0e-6, Math.min(1.0, frac)));
    }
    return best;
  }

  private static double nextPow2(double x) {
    double p = 1;
    while (p < x) p *= 2;
    return p;
  }

  /**
   * Like baseColumn, but also through joins, as PostgreSQL's Var does: {table, column, rows of that table after
   * its own filters}, or null.
   */
  private Object[] baseVar(RelNode rel, int i, RelMetadataQuery mq) {
    if (rel instanceof RelSubset s) {
      RelNode r = s.getBest() != null ? s.getBest() : s.getOriginal();
      return r == null ? null : baseVar(r, i, mq);
    }
    if (rel instanceof TableScan ts) {
      List<String> name = ts.getTable().getQualifiedName();
      return new Object[] {name.get(name.size() - 1), ts.getRowType().getFieldList().get(i).getName(), rows(ts, mq)};
    }
    if (rel instanceof Filter f) {
      Object[] v = baseVar(f.getInput(), i, mq);
      if (v != null && isScan(f.getInput())) v[2] = rows(f, mq);  // the base table's own restriction
      return v;
    }
    if (rel instanceof Sort s) return baseVar(s.getInput(), i, mq);
    if (rel instanceof Project p) {
      RexNode e = p.getProjects().get(i);
      return e instanceof RexInputRef r ? baseVar(p.getInput(), r.getIndex(), mq) : null;
    }
    if (rel instanceof Join j) {
      int nl = j.getLeft().getRowType().getFieldCount();
      return i < nl ? baseVar(j.getLeft(), i, mq) : baseVar(j.getRight(), i - nl, mq);
    }
    return null;
  }

  private static boolean isScan(RelNode r) {
    if (r instanceof RelSubset s) r = s.getBest() != null ? s.getBest() : s.getOriginal();
    return r instanceof TableScan;
  }

  private static double rows(RelNode r, RelMetadataQuery mq) {
    Double d = mq.getRowCount(r);
    return d == null ? 1 : d;
  }

  /** Run cost (total - startup) of an input's best plan so far; 0 if not known yet. */
  private static double runCost(RelNode input, RelMetadataQuery mq) {
    RelOptCost c = input.getCluster().getPlanner().getCost(input, mq);
    return (c instanceof PgCost p && !p.isInfinite()) ? p.total - p.startup : 0;
  }

  /** PG proves inner uniqueness only for base tables with a unique key (n_distinct = -1). */
  private boolean innerUnique(RelNode inner, List<Integer> keys) {
    if (keys.size() != 1) return false;
    String[] col = baseColumn(inner, keys.get(0));
    if (col == null) return false;
    PgStats.Column c = stats.column(col[0], col[1]);
    return c != null && c.nDistinctRaw == -1 && col[1].equals("id");
  }

  /** Follow column i down to a base-table column; null if it passes through a join. */
  private String[] baseColumn(RelNode rel, int i) {
    if (rel instanceof RelSubset s) {
      RelNode r = s.getBest() != null ? s.getBest() : s.getOriginal();
      return r == null ? null : baseColumn(r, i);
    }
    if (rel instanceof TableScan ts) {
      List<String> name = ts.getTable().getQualifiedName();
      return new String[] {name.get(name.size() - 1),
          ts.getRowType().getFieldList().get(i).getName()};
    }
    if (rel instanceof Filter f) return baseColumn(f.getInput(), i);
    if (rel instanceof Sort s) return baseColumn(s.getInput(), i);
    if (rel instanceof Project p) {
      RexNode e = p.getProjects().get(i);
      return e instanceof RexInputRef r ? baseColumn(p.getInput(), r.getIndex()) : null;
    }
    return null;
  }
}
