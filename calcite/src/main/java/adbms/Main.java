package adbms;

import java.sql.Connection;
import java.sql.DriverManager;
import java.util.*;
import javax.sql.DataSource;

import org.apache.calcite.adapter.enumerable.EnumerableConvention;
import org.apache.calcite.adapter.enumerable.EnumerableRules;
import org.apache.calcite.adapter.java.JavaTypeFactory;
import org.apache.calcite.adapter.jdbc.JdbcSchema;
import org.apache.calcite.jdbc.CalciteConnection;
import org.apache.calcite.jdbc.JavaTypeFactoryImpl;
import org.apache.calcite.plan.RelOptRule;
import org.apache.calcite.plan.RelOptUtil;
import org.apache.calcite.plan.volcano.AbstractConverter;
import org.apache.calcite.plan.volcano.RelSubset;
import org.apache.calcite.plan.volcano.VolcanoPlanner;
import org.apache.calcite.rel.RelNode;
import org.apache.calcite.rel.logical.LogicalJoin;
import org.apache.calcite.rel.metadata.BuiltInMetadata;
import org.apache.calcite.rel.metadata.ChainedRelMetadataProvider;
import org.apache.calcite.rel.metadata.DefaultRelMetadataProvider;
import org.apache.calcite.rel.metadata.ReflectiveRelMetadataProvider;
import org.apache.calcite.rel.metadata.RelMetadataProvider;
import org.apache.calcite.rel.rules.CoreRules;
import org.apache.calcite.rel.rules.JoinAssociateRule;
import org.apache.calcite.rel.type.RelDataType;
import org.apache.calcite.rel.type.RelDataTypeField;
import org.apache.calcite.schema.SchemaPlus;
import org.apache.calcite.schema.Table;
import org.apache.calcite.schema.impl.AbstractSchema;
import org.apache.calcite.sql.SqlExplainLevel;
import org.apache.calcite.sql.parser.SqlParser;
import org.apache.calcite.tools.*;
import org.apache.calcite.util.ImmutableBitSet;

public class Main {
  public static void main(String[] args) throws Exception {
    // Arguments, in any order: a path ending in .json = the stats file; anything else is an option.
    //   nosort  : don't turn sort requests into real Sorts (the week-3 baseline: merge join never gets a cost)
    //   nlj     : also offer a nested-loop join for equality joins, as PostgreSQL does
    //   topdown : Calcite's top-down mode with cost-bound pruning (stretch)
    // Example: mvn -q compile exec:java -Dexec.args="nlj"
    String statsPath = "../stats/test_tables.json";
    Set<String> opts = new HashSet<>();
    for (String a : args) {
      if (a.endsWith(".json")) statsPath = a; else opts.add(a.toLowerCase());
    }
    boolean sortEnforcer = !opts.contains("nosort");
    boolean nlj = opts.contains("nlj");
    boolean topDown = opts.contains("topdown");
    // Trace files get a suffix per non-default option, so runs with different options never overwrite each other
    String traceSuffix = (sortEnforcer ? "" : "_nosort") + (nlj ? "_nlj" : "") + (topDown ? "_topdown" : "");
    System.err.println("Options: sort enforcer=" + sortEnforcer + ", nested loop for equi-joins=" + nlj
        + ", top-down=" + topDown + "; traces -> calcite_Q*" + traceSuffix + ".json");
    PgStats stats = PgStats.load(statsPath);

    String[] queries = {
      "SELECT * FROM a WHERE x = 3",
      "SELECT * FROM a JOIN b ON a.id = b.a_id",
      "SELECT * FROM a JOIN b ON a.id = b.a_id WHERE a.x = 3",
      "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id WHERE a.x = 3",
      "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id",
      // week 3: 4 and 5 tables (needs sql/test_tables_de.sql + re-run extract_stats.sql)
      "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id JOIN d ON c.id = d.c_id WHERE a.x = 3",
      "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id JOIN d ON c.id = d.c_id JOIN e ON a.id = e.a_id WHERE a.x = 3",
      "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id JOIN d ON c.id = d.c_id",
      // Q9 = Q4 + ORDER BY on the next join's key: a merge join on b.id = c.b_id already outputs
      // rows sorted on b.id, so sort order becomes "interesting" (System R) / a required property (Volcano)
      "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id WHERE a.x = 3 ORDER BY b.id"
    };

    // 1. PostgreSQL connection, used only to read each table's columns
    Connection conn = DriverManager.getConnection("jdbc:calcite:");
    SchemaPlus root = conn.unwrap(CalciteConnection.class).getRootSchema();
    DataSource ds = JdbcSchema.dataSource(
        "jdbc:postgresql://localhost:5432/test", "org.postgresql.Driver", "dev", "");
    JdbcSchema jdbc = JdbcSchema.create(root, "pg", ds, null, "public");

    // 2. Our own tables: PG's columns + PG's row counts (and keys where n_distinct = -1)
    JavaTypeFactory tf = new JavaTypeFactoryImpl();
    Map<String, Table> statTables = new HashMap<>();
    for (Map.Entry<String, PgStats.Table> e : stats.tables.entrySet()) {
      Table pgTable = jdbc.getTable(e.getKey());
      if (pgTable == null) { System.err.println("No PG table " + e.getKey()); continue; }
      RelDataType rt = pgTable.getRowType(tf);
      List<ImmutableBitSet> keys = new ArrayList<>();
      for (RelDataTypeField f : rt.getFieldList()) {
        PgStats.Column c = e.getValue().columns.get(f.getName());
        if (c != null && c.nDistinctRaw == -1) keys.add(ImmutableBitSet.of(f.getIndex()));
      }
      statTables.put(e.getKey(), new StatTable(pgTable, e.getValue().reltuples, keys));
    }
    root.add("pgstats", new AbstractSchema() {
      @Override protected Map<String, Table> getTableMap() { return statTables; }
    });

    // 3. Metadata: our selectivity first, Calcite's defaults for everything else
    RelMetadataProvider provider = ChainedRelMetadataProvider.of(List.of(
        ReflectiveRelMetadataProvider.reflectiveSource(
            new PgSelectivity(stats), BuiltInMetadata.Selectivity.Handler.class),
        ReflectiveRelMetadataProvider.reflectiveSource(
            new PgCostModel(stats), BuiltInMetadata.NonCumulativeCost.Handler.class),
        DefaultRelMetadataProvider.INSTANCE));

    // 4. Rules (same as Day 1)
    RelOptRule joinAssociate = JoinAssociateRule.Config.DEFAULT
        .withOperandSupplier(b0 -> b0.operand(LogicalJoin.class).inputs(
            b1 -> b1.operand(LogicalJoin.class).anyInputs(),
            b2 -> b2.operand(RelSubset.class).anyInputs()))
        .as(JoinAssociateRule.Config.class)
        .toRule();

    List<RelOptRule> ruleList = new ArrayList<>(List.of(
        CoreRules.FILTER_INTO_JOIN,
        CoreRules.JOIN_COMMUTE,
        joinAssociate,
        EnumerableRules.ENUMERABLE_TABLE_SCAN_RULE,
        EnumerableRules.ENUMERABLE_FILTER_RULE,
        EnumerableRules.ENUMERABLE_PROJECT_RULE,
        EnumerableRules.ENUMERABLE_JOIN_RULE,
        EnumerableRules.ENUMERABLE_MERGE_JOIN_RULE,
        EnumerableRules.ENUMERABLE_SORT_RULE));
    // Merge join asks for sorted inputs through AbstractConverter placeholders. This rule turns each
    // placeholder into a LogicalSort, which ENUMERABLE_SORT_RULE then makes an EnumerableSort.
    // Without it the sorted subsets stay empty and every merge join has infinite cost.
    if (sortEnforcer) ruleList.add(AbstractConverter.ExpandConversionRule.INSTANCE);
    if (nlj) ruleList.add(EnumerableEquiNestedLoopJoinRule.INSTANCE);
    RuleSet rules = RuleSets.ofList(ruleList);

    FrameworkConfig cfg = Frameworks.newConfigBuilder()
        .defaultSchema(root.getSubSchema("pgstats"))
        .parserConfig(SqlParser.config().withCaseSensitive(false))
        .programs(Programs.ofRules(rules))
        .costFactory(new PgCostFactory())   // PG-style cost model (Vishudha)
        .build();

    // 5. Plan each query
    for (int qi = 0; qi < queries.length; qi++) {
      String sql = queries[qi];
      String qname = "Q" + (qi + 1);
      Planner planner = Frameworks.getPlanner(cfg);      // fresh planner per query
      RelNode logical = planner.rel(planner.validate(planner.parse(sql))).project();

      logical.getCluster().setMetadataProvider(provider); // must be before transform()
      logical.getCluster().invalidateMetadataQuery();

      // week 3: record the search (memo, rule firings, best-plan timeline)
      VolcanoPlanner vp = (VolcanoPlanner) logical.getCluster().getPlanner();
      if (topDown) vp.setTopDownOpt(true);
      SearchTrace trace = new SearchTrace(vp, qname, sql);
      vp.addListener(trace);

      RelNode best = planner.transform(0,
          logical.getTraitSet().replace(EnumerableConvention.INSTANCE), logical);

      trace.finish();
      trace.write("../traces/calcite_" + qname + traceSuffix + ".json");

      System.out.println("\n### " + sql);
      System.out.println(RelOptUtil.toString(best, SqlExplainLevel.ALL_ATTRIBUTES));
      planner.close();
    }
  }
}