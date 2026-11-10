package adbms;

import java.sql.Connection;
import java.sql.DriverManager;
import javax.sql.DataSource;

import org.apache.calcite.adapter.enumerable.EnumerableConvention;
import org.apache.calcite.adapter.enumerable.EnumerableRules;
import org.apache.calcite.adapter.jdbc.JdbcSchema;
import org.apache.calcite.jdbc.CalciteConnection;
import org.apache.calcite.plan.RelOptUtil;
import org.apache.calcite.rel.RelNode;
import org.apache.calcite.rel.rules.CoreRules;
import org.apache.calcite.schema.SchemaPlus;
import org.apache.calcite.sql.SqlExplainLevel;
import org.apache.calcite.sql.parser.SqlParser;
import org.apache.calcite.tools.*;

import org.apache.calcite.plan.RelOptRule;
import org.apache.calcite.plan.volcano.RelSubset;
import org.apache.calcite.rel.logical.LogicalJoin;
import org.apache.calcite.rel.rules.JoinAssociateRule;

public class Main {
  public static void main(String[] args) throws Exception {
    String sql = "SELECT * FROM a "
        + "JOIN b ON a.id = b.a_id "
        + "JOIN c ON b.id = c.b_id "
        + "WHERE a.x = 3";

    // 1. Calcite's root schema, with PostgreSQL attached as sub-schema "pg"
    Connection conn = DriverManager.getConnection("jdbc:calcite:");
    SchemaPlus root = conn.unwrap(CalciteConnection.class).getRootSchema();
    DataSource ds = JdbcSchema.dataSource(
        "jdbc:postgresql://localhost:5432/dev",
        "org.postgresql.Driver", "dev", "");
    root.add("pg", JdbcSchema.create(root, "pg", ds, null, "public"));

    RelOptRule joinAssociate = JoinAssociateRule.Config.DEFAULT
    .withOperandSupplier(b0 -> b0.operand(LogicalJoin.class).inputs(
        b1 -> b1.operand(LogicalJoin.class).anyInputs(),
        b2 -> b2.operand(RelSubset.class).anyInputs()))
    .as(JoinAssociateRule.Config.class)
    .toRule();

    // 2. Rules Volcano may use: join reordering + physical operators
    RuleSet rules = RuleSets.ofList(
        CoreRules.FILTER_INTO_JOIN,
        CoreRules.JOIN_COMMUTE,
        joinAssociate,
        EnumerableRules.ENUMERABLE_TABLE_SCAN_RULE,
        EnumerableRules.ENUMERABLE_FILTER_RULE,
        EnumerableRules.ENUMERABLE_PROJECT_RULE,
        EnumerableRules.ENUMERABLE_JOIN_RULE,
        EnumerableRules.ENUMERABLE_MERGE_JOIN_RULE,
        EnumerableRules.ENUMERABLE_SORT_RULE);

    FrameworkConfig cfg = Frameworks.newConfigBuilder()
        .defaultSchema(root.getSubSchema("pg"))
        .parserConfig(SqlParser.config().withCaseSensitive(false))
        .programs(Programs.ofRules(rules))
        .build();

    // 3. Parse -> validate -> logical plan
    Planner planner = Frameworks.getPlanner(cfg);
    RelNode logical = planner.rel(planner.validate(planner.parse(sql))).project();
    System.out.println("=== Logical plan ===");
    System.out.println(RelOptUtil.toString(logical, SqlExplainLevel.ALL_ATTRIBUTES));

    // 4. Volcano: find the cheapest physical plan
    RelNode best = planner.transform(0,
        logical.getTraitSet().replace(EnumerableConvention.INSTANCE), logical);
    System.out.println("=== Physical plan (Volcano) ===");
    System.out.println(RelOptUtil.toString(best, SqlExplainLevel.ALL_ATTRIBUTES));
  }
}