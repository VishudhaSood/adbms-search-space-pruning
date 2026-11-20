package adbms;

import java.util.ArrayList;
import java.util.List;
import org.apache.calcite.adapter.enumerable.EnumerableConvention;
import org.apache.calcite.adapter.enumerable.EnumerableNestedLoopJoin;
import org.apache.calcite.plan.Convention;
import org.apache.calcite.rel.RelNode;
import org.apache.calcite.rel.convert.ConverterRule;
import org.apache.calcite.rel.core.JoinInfo;
import org.apache.calcite.rel.core.JoinRelType;
import org.apache.calcite.rel.logical.LogicalJoin;

/**
 * Offers a nested-loop join for equality joins too, the way PostgreSQL does.
 *
 * Calcite's own EnumerableJoinRule makes a hash join whenever the condition has an
 * equality key, and a nested loop only when it has none (cross products). PostgreSQL
 * tries a nested loop for every pair of tables. Turned on with the "nlj" option in Main.
 *
 * Only fires on inner joins that HAVE an equality key, so it never duplicates the
 * nested loop EnumerableJoinRule already makes for cross products.
 */
public class EnumerableEquiNestedLoopJoinRule extends ConverterRule {
  public static final EnumerableEquiNestedLoopJoinRule INSTANCE = Config.INSTANCE
      .withConversion(LogicalJoin.class, Convention.NONE,
          EnumerableConvention.INSTANCE, "EnumerableEquiNestedLoopJoinRule")
      .withRuleFactory(EnumerableEquiNestedLoopJoinRule::new)
      .toRule(EnumerableEquiNestedLoopJoinRule.class);

  protected EnumerableEquiNestedLoopJoinRule(Config config) {
    super(config);
  }

  @Override public RelNode convert(RelNode rel) {
    LogicalJoin join = (LogicalJoin) rel;
    if (join.getJoinType() != JoinRelType.INNER) return null;
    JoinInfo info = join.analyzeCondition();
    if (info.leftKeys.isEmpty()) return null;   // no equality key: EnumerableJoinRule already does this

    List<RelNode> inputs = new ArrayList<>();
    for (RelNode input : join.getInputs()) {
      if (!(input.getConvention() instanceof EnumerableConvention)) {
        input = convert(input, input.getTraitSet().replace(EnumerableConvention.INSTANCE));
      }
      inputs.add(input);
    }
    return EnumerableNestedLoopJoin.create(inputs.get(0), inputs.get(1),
        join.getCondition(), join.getVariablesSet(), JoinRelType.INNER);
  }
}
