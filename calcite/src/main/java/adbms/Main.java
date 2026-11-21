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
import org.apache.calcite.rel.rules.JoinCommuteRule;
import org.apache.calcite.rel.rules.JoinPushThroughJoinRule;

public class Main {
  public static void main(String[] args) throws Exception {
    // Arguments, in any order: a path ending in .json = the stats file; anything else is an option.
    //   nosort  : don't turn sort requests into real Sorts (the week-3 baseline: merge join never gets a cost)
    //   nlj     : also offer a nested-loop join for equality joins, as PostgreSQL does
    //   topdown : Calcite's top-down mode with cost-bound pruning (stretch)
    //   reps=N  : plan each query N times untraced and N times traced (default 5); timings = median of runs 2..N
    //   only=Q8 : plan only these queries (comma-separated, e.g. only=Q4,Q8)
    // Example: mvn -q compile exec:java -Dexec.args="nlj"
    String statsPath = "../stats/test_tables.json";
    Set<String> opts = new HashSet<>();
    int reps = 5;
    int warmup = 10;
    Set<String> only = new HashSet<>();
    for (String a : args) {
      String lower = a.toLowerCase();
      if (a.endsWith(".json")) statsPath = a;
      else if (lower.startsWith("reps=")) reps = Math.max(1, Integer.parseInt(lower.substring(5)));
      else if (lower.startsWith("warmup=")) warmup = Math.max(0, Integer.parseInt(lower.substring(7)));
      else if (lower.startsWith("only=")) only.addAll(Arrays.asList(a.substring(5).toUpperCase().split(",")));
      else opts.add(lower);
    }
    boolean sortEnforcer = !opts.contains("nosort");
    boolean nlj = opts.contains("nlj");
    boolean topDown = opts.contains("topdown");
    boolean noCross = opts.contains("nocross");   // rules may not create new cross products
    boolean exchange = opts.contains("exchange");  // add JoinPushThroughJoinRule (LEFT + RIGHT)
    // Trace files get a suffix per non-default option, so runs with different options never overwrite each other
    String traceSuffix = (sortEnforcer ? "" : "_nosort") + (nlj ? "_nlj" : "") + (topDown ? "_topdown" : "") + (noCross ? "_nocross" : "") + (exchange ? "_exchange" : "");
    System.err.println("Options: sort enforcer=" + sortEnforcer + ", nested loop for equi-joins=" + nlj
        + ", top-down=" + topDown + ", reps=" + reps + (only.isEmpty() ? "" : ", only=" + only)
        + "; traces -> calcite_Q*" + traceSuffix + ".json");
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
      "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id WHERE a.x = 3 ORDER BY b.id",
            // Q10 = Q8 written in reverse join order: tests whether top-down's result depends on the starting tree
      "SELECT * FROM d JOIN c ON c.id = d.c_id JOIN b ON b.id = c.b_id JOIN a ON a.id = b.a_id"
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
        JoinAssociateRule.Config assocCfg = JoinAssociateRule.Config.DEFAULT
        .withOperandSupplier(b0 -> b0.operand(LogicalJoin.class).inputs(
            b1 -> b1.operand(LogicalJoin.class).anyInputs(),
            b2 -> b2.operand(RelSubset.class).anyInputs()))
        .as(JoinAssociateRule.Config.class);
    if (noCross) assocCfg = assocCfg.withAllowAlwaysTrueCondition(false);
    RelOptRule joinAssociate = assocCfg.toRule();
    RelOptRule joinCommute = noCross? JoinCommuteRule.Config.DEFAULT.withAllowAlwaysTrueCondition(false).toRule(): CoreRules.JOIN_COMMUTE;

    List<RelOptRule> ruleList = new ArrayList<>(List.of(
        CoreRules.FILTER_INTO_JOIN,
        joinCommute,
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
    if (exchange) {
      ruleList.add(JoinPushThroughJoinRule.Config.LEFT.toRule());
      ruleList.add(JoinPushThroughJoinRule.Config.RIGHT.toRule());
    }
    RuleSet rules = RuleSets.ofList(ruleList);

    FrameworkConfig cfg = Frameworks.newConfigBuilder()
        .defaultSchema(root.getSubSchema("pgstats"))
        .parserConfig(SqlParser.config().withCaseSensitive(false))
        .programs(Programs.ofRules(rules))
        .costFactory(new PgCostFactory())   // PG-style cost model (Vishudha)
        .build();
        // 4b. Warm up the JVM: plan every selected query `warmup` times, untraced, before measuring anything.
        for (int w = 0; w < warmup; w++) {
          for (int qi = 0; qi < queries.length; qi++) {
            String qname = "Q" + (qi + 1);
            if (!only.isEmpty() && !only.contains(qname)) continue;
            planOnce(cfg, provider, queries[qi], qname, topDown, false);
          }
        }
    System.err.println("Warm-up: " + warmup + " rounds done");
    // 5. Plan each query: `reps` untraced runs, then `reps` traced runs (the last traced run's trace is kept).
    //    The first run of a query is slow (JIT, metadata handlers being generated), so the medians use runs 2..reps.
    for (int qi = 0; qi < queries.length; qi++) {
      String sql = queries[qi];
      String qname = "Q" + (qi + 1);
      if (!only.isEmpty() && !only.contains(qname)) continue;

         List<Long> untraced = new ArrayList<>(), traced = new ArrayList<>();
        PlanRun last = null;
        for (int r = 0; r < reps; r++) {            // alternate, so warm-up hits both equally
          untraced.add(planOnce(cfg, provider, sql, qname, topDown, false).nanos);
          last = planOnce(cfg, provider, sql, qname, topDown, true);
          traced.add(last.nanos);
        }

      Map<String, Object> timing = new LinkedHashMap<>();
      timing.put("reps", reps);
      timing.put("planning_us_untraced_median", medianUs(untraced));
      timing.put("planning_us_traced_median", medianUs(traced));
      timing.put("planning_us_untraced_all", toUs(untraced));
      timing.put("planning_us_traced_all", toUs(traced));
      // Viewer: t_shown = t_us * replay_scale, so the replay lasts as long as untraced planning does
      double tr = medianUs(traced), un = medianUs(untraced);
      timing.put("replay_scale", tr > 0 ? un / tr : 1.0);
      last.trace.setTimings(timing);
      last.trace.write("../traces/calcite_" + qname + traceSuffix + ".json");
      System.err.printf("%s: planning %.2f ms untraced, %.2f ms traced (median of runs 2..%d)%n",
          qname, un / 1000, tr / 1000, reps);

      System.out.println("\n### " + sql);
      System.out.println(RelOptUtil.toString(last.best, SqlExplainLevel.ALL_ATTRIBUTES));
    }
  }

  /** Result of one planning run. trace is null for untraced runs. */
  static final class PlanRun {
    final RelNode best; final long nanos; final SearchTrace trace;
    PlanRun(RelNode best, long nanos, SearchTrace trace) { this.best = best; this.nanos = nanos; this.trace = trace; }
  }

  /** Parse, convert and plan sql once with a fresh planner. Only transform() is timed. */
  static PlanRun planOnce(FrameworkConfig cfg, RelMetadataProvider provider, String sql, String qname,
      boolean topDown, boolean withTrace) throws Exception {
    Planner planner = Frameworks.getPlanner(cfg);      // fresh planner per run
    try {
      RelNode logical = planner.rel(planner.validate(planner.parse(sql))).project();
      logical.getCluster().setMetadataProvider(provider); // must be before transform()
      logical.getCluster().invalidateMetadataQuery();

      VolcanoPlanner vp = (VolcanoPlanner) logical.getCluster().getPlanner();
      if (topDown) vp.setTopDownOpt(true);
      SearchTrace trace = null;
      if (withTrace) {
        trace = new SearchTrace(vp, qname, sql);       // its clock starts here
        vp.addListener(trace);
      }
      long t0 = System.nanoTime();
      RelNode best = planner.transform(0,
          logical.getTraitSet().replace(EnumerableConvention.INSTANCE), logical);
      long nanos = System.nanoTime() - t0;
      if (trace != null) trace.finish();               // reads the memo, so before close()
      return new PlanRun(best, nanos, trace);
    } finally {
      planner.close();
    }
  }

  /** Median in microseconds, leaving out the first (warm-up) run when there is more than one. */
  static double medianUs(List<Long> nanos) {
    List<Long> xs = new ArrayList<>(nanos.size() > 1 ? nanos.subList(1, nanos.size()) : nanos);
    Collections.sort(xs);
    int n = xs.size();
    double m = n % 2 == 1 ? xs.get(n / 2) : (xs.get(n / 2 - 1) + xs.get(n / 2)) / 2.0;
    return m / 1000.0;
  }

  static List<Long> toUs(List<Long> nanos) {
    List<Long> out = new ArrayList<>();
    for (long x : nanos) out.add(x / 1000);
    return out;
  }
}
