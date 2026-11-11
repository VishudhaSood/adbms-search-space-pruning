package adbms;

import org.apache.calcite.plan.RelOptCost;
import org.apache.calcite.plan.RelOptUtil;

/** PostgreSQL-style cost: startup and total (PG cost units). Plans are compared by total. */
public class PgCost implements RelOptCost {
  static final PgCost INFINITY = new PgCost(Double.POSITIVE_INFINITY,
      Double.POSITIVE_INFINITY, Double.POSITIVE_INFINITY);
  static final PgCost HUGE = new PgCost(Double.MAX_VALUE, Double.MAX_VALUE, Double.MAX_VALUE);
  static final PgCost ZERO = new PgCost(0, 0, 0);
  static final PgCost TINY = new PgCost(0, 0, 1e-6);

  final double rows, startup, total;

  PgCost(double rows, double startup, double total) {
    this.rows = rows; this.startup = startup; this.total = total;
  }

  private static double totalOf(RelOptCost c) { return c instanceof PgCost p ? p.total : c.getCpu(); }
  private static double startupOf(RelOptCost c) { return c instanceof PgCost p ? p.startup : 0; }

  @Override public double getRows() { return rows; }
  @Override public double getCpu() { return total; }
  @Override public double getIo() { return 0; }
  @Override public boolean isInfinite() { return Double.isInfinite(total); }

  @Override public boolean equals(RelOptCost c) {
    return c instanceof PgCost p && total == p.total && startup == p.startup;
  }
  @Override public boolean isEqWithEpsilon(RelOptCost c) {
    return Math.abs(total - totalOf(c)) < RelOptUtil.EPSILON;
  }
  @Override public boolean isLe(RelOptCost c) { return total <= totalOf(c); }
  @Override public boolean isLt(RelOptCost c) { return total < totalOf(c); }

  @Override public RelOptCost plus(RelOptCost c) {
    if (isInfinite() || c.isInfinite()) return INFINITY;
    return new PgCost(rows + c.getRows(), startup + startupOf(c), total + totalOf(c));
  }
  @Override public RelOptCost minus(RelOptCost c) {
    if (isInfinite()) return this;
    return new PgCost(rows - c.getRows(), startup - startupOf(c), total - totalOf(c));
  }
  @Override public RelOptCost multiplyBy(double f) {
    if (isInfinite()) return this;
    return new PgCost(rows * f, startup * f, total * f);
  }
  @Override public double divideBy(RelOptCost c) {
    double t = totalOf(c);
    return (t > 0 && !Double.isInfinite(t) && !isInfinite()) ? total / t : 1.0;
  }
  @Override public String toString() {
    return isInfinite() ? "{inf}" : String.format("{cost=%.2f..%.2f}", startup, total);
  }
}
