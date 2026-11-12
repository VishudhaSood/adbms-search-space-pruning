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
    String statsPath = args.length > 0 ? args[0] : "../stats/test_tables.json";
    boolean topDown = args.length > 1 && args[1].equals("topdown");   // stretch: Calcite's top-down mode with cost-bound pruning
    String traceSuffix = topDown ? "_topdown" : "";
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
      "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id JOIN d ON c.id = d.c_id"
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