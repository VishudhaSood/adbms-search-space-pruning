package adbms;

import org.apache.calcite.plan.RelOptCost;
import org.apache.calcite.plan.RelOptCostFactory;

/** Gives the Volcano planner PgCost objects instead of VolcanoCost. */
public class PgCostFactory implements RelOptCostFactory {
  // Only used by operators we don't model (they call makeCost from computeSelfCost)
  @Override public RelOptCost makeCost(double rows, double cpu, double io) {
    return new PgCost(rows, 0, cpu + io);
  }
  @Override public RelOptCost makeHugeCost() { return PgCost.HUGE; }
  @Override public RelOptCost makeInfiniteCost() { return PgCost.INFINITY; }
  @Override public RelOptCost makeTinyCost() { return PgCost.TINY; }
  @Override public RelOptCost makeZeroCost() { return PgCost.ZERO; }
}
