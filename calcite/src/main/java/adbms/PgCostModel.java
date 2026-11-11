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
    PgStats.Table t = stats.tables.get(name.get(name.size() - 1).toLowerCase());
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
   * Assumes one batch (inner fits in work_mem) and bucket clamps of 1 (true for small tables).
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
    } else {
      bucket = cpuOp * k * outer * 0.5;
      passing = out;
    }
    double run = probe + bucket + cpuTuple * passing;
    return new PgCost(out, runCost(j.getRight(), mq) + build, build + run);
  }

  /** final_cost_mergejoin, simplified: compare both inputs once + cpu_tuple_cost per output row. */
  public RelOptCost getNonCumulativeCost(EnumerableMergeJoin j, RelMetadataQuery mq) {
    int k = Math.max(1, j.analyzeCondition().leftKeys.size());
    double outer = rows(j.getLeft(), mq), inner = rows(j.getRight(), mq), out = rows(j, mq);
    return new PgCost(out, 0, cpuOp * k * (outer + inner) + cpuTuple * out);
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
    return c != null && c.nDistinctRaw == -1;
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
