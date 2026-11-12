package adbms;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.File;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.apache.calcite.plan.Convention;
import org.apache.calcite.plan.ConventionTraitDef;
import org.apache.calcite.plan.RelOptCost;
import org.apache.calcite.plan.RelOptListener;
import org.apache.calcite.plan.volcano.RelSubset;
import org.apache.calcite.plan.volcano.VolcanoPlanner;
import org.apache.calcite.rel.RelNode;
import org.apache.calcite.rel.metadata.RelMetadataQuery;
import org.apache.calcite.rex.RexTableInputRef.RelTableRef;

/**
 * Records what the Volcano planner does for one query, for the search-space viewer.
 *
 *  - every RelNode added to the memo (relEquivalenceFound), with the rule that made it
 *  - rule firings attempted / that produced something
 *  - a timeline of the root's best plan: a snapshot every time its cost changes
 *  - at the end: every node's RelSet, subset (traits), inputs, cost, rows, and which nodes won
 *
 * Usage in Main, per query, BEFORE planner.transform(...):
 *   VolcanoPlanner vp = (VolcanoPlanner) logical.getCluster().getPlanner();
 *   SearchTrace trace = new SearchTrace(vp, "Q4", sql);
 *   vp.addListener(trace);
 * and AFTER transform:
 *   trace.finish();
 *   trace.write("../traces/calcite_Q4.json");
 */
public class SearchTrace implements RelOptListener {
  private static final Pattern SUBSET = Pattern.compile("RelSubset#(\\d+)\\.(.*)");

  private final VolcanoPlanner planner;
  private final String query, sql;
  private final Map<String, Object> out = new LinkedHashMap<>();
  private final List<Map<String, Object>> events = new ArrayList<>();
  private final Map<Integer, RelNode> nodes = new LinkedHashMap<>();
  private final List<Map<String, Object>> timeline = new ArrayList<>();
  private String currentRule = "initial";
  private int step = 0, rulesAttempted = 0, rulesProduced = 0;
  private double lastBestTotal = Double.NaN;

  public SearchTrace(VolcanoPlanner planner, String query, String sql) {
    this.planner = planner;
    this.query = query;
    this.sql = sql;
  }

  // ---------------- listener events ----------------

  @Override public void relEquivalenceFound(RelEquivalenceEvent e) {
    RelNode rel = e.getRel();
    if (rel == null || rel instanceof RelSubset || nodes.containsKey(rel.getId())) return;
    nodes.put(rel.getId(), rel);
    Map<String, Object> ev = new LinkedHashMap<>();
    ev.put("step", ++step);
    ev.put("node", rel.getId());
    ev.put("op", rel.getRelTypeName());
    ev.put("subset_at_registration", String.valueOf(e.getEquivalenceClass()));
    ev.put("rule", currentRule);
    ev.put("physical", isPhysical(rel));
    ev.put("result", "registered");
    events.add(ev);
  }

  @Override public void ruleAttempted(RuleAttemptedEvent e) {
    if (e.isBefore()) {
      rulesAttempted++;
      currentRule = e.getRuleCall().getRule().toString();
    } else {
      currentRule = "initial";
    }
  }

  @Override public void ruleProductionSucceeded(RuleProductionEvent e) {
    if (e.isBefore()) return;
    rulesProduced++;
    snapshotRootBest();
  }

  @Override public void relDiscarded(RelDiscardedEvent e) { }

  @Override public void relChosen(RelChosenEvent e) { }

  // ---------------- best-plan timeline ----------------

  private void snapshotRootBest() {
    try {
      RelNode root = planner.getRoot();
      if (!(root instanceof RelSubset)) return;
      RelNode best = ((RelSubset) root).getBest();
      if (best == null) return;
      RelMetadataQuery mq = best.getCluster().getMetadataQuery();
      double[] c = cost(planner.getCost(best, mq));
      if (c == null || c[1] == lastBestTotal) return;
      lastBestTotal = c[1];
      Map<String, Object> snap = new LinkedHashMap<>();
      snap.put("step", step);
      snap.put("startup", c[0]);
      snap.put("total", c[1]);
      snap.put("plan", tree(best, mq, 0));
      timeline.add(snap);
    } catch (Throwable t) {
      // metadata can fail half-way through planning; just skip this snapshot
    }
  }

  private Map<String, Object> tree(RelNode rel, RelMetadataQuery mq, int depth) {
    Map<String, Object> n = new LinkedHashMap<>();
    n.put("node", rel.getId());
    n.put("op", rel.getRelTypeName());
    double[] c = null;
    try { c = cost(planner.getCost(rel, mq)); } catch (Throwable ignored) { }
    if (c != null) { n.put("startup", c[0]); n.put("total", c[1]); }
    try { n.put("rows", mq.getRowCount(rel)); } catch (Throwable ignored) { }
    if (rel.getTable() != null) {
      List<String> q = rel.getTable().getQualifiedName();
      n.put("table", q.get(q.size() - 1));
    }
    List<Object> kids = new ArrayList<>();
    if (depth < 30) {
      for (RelNode in : rel.getInputs()) {
        RelNode b = in instanceof RelSubset ? ((RelSubset) in).getBest() : in;
        if (b == null) {
          Map<String, Object> missing = new LinkedHashMap<>();
          missing.put("op", "(no plan yet)");
          kids.add(missing);
        } else {
          kids.add(tree(b, mq, depth + 1));
        }
      }
    }
    n.put("children", kids);
    return n;
  }

  // ---------------- end of planning ----------------

  public void finish() {
    snapshotRootBest();
    RelMetadataQuery mq = planner.getRoot().getCluster().getMetadataQuery();

    Map<Integer, List<String>> setTables = new TreeMap<>();
    Map<String, Integer> subsetWinner = new LinkedHashMap<>();
    List<Map<String, Object>> nodeList = new ArrayList<>();
    for (RelNode rel : nodes.values()) {
      RelSubset s = planner.getSubset(rel);
      Map<String, Object> n = new LinkedHashMap<>();
      n.put("node", rel.getId());
      n.put("op", rel.getRelTypeName());
      n.put("physical", isPhysical(rel));
      if (s == null) {                      // merged away / not in the final memo
        n.put("set", null);
        nodeList.add(n);
        continue;
      }
      String[] st = parseSubset(s);
      int set = Integer.parseInt(st[0]);
      n.put("set", set);
      n.put("traits", st[1]);
      List<Object> ins = new ArrayList<>();
      for (RelNode in : rel.getInputs()) {
        if (in instanceof RelSubset) {
          String[] p = parseSubset((RelSubset) in);
          ins.add(Map.of("set", Integer.parseInt(p[0]), "traits", p[1]));
        }
      }
      n.put("inputs", ins);
      try {
        double[] c = cost(planner.getCost(rel, mq));
        if (c != null) { n.put("startup", c[0]); n.put("total", c[1]); }
      } catch (Throwable ignored) { }
      try { n.put("rows", mq.getRowCount(rel)); } catch (Throwable ignored) { }
      if (!setTables.containsKey(set)) setTables.put(set, tablesOf(rel, mq));
      String key = set + "|" + st[1];
      if (!subsetWinner.containsKey(key)) {
        RelNode best = s.getBest();
        subsetWinner.put(key, best == null ? null : best.getId());
      }
      nodeList.add(n);
    }

    // which nodes are in the chosen plan
    Set<Integer> chosen = new HashSet<>();
    RelNode rootBest = ((RelSubset) planner.getRoot()).getBest();
    collect(rootBest, chosen, 0);
    for (Map<String, Object> n : nodeList) {
      Object id = n.get("node");
      n.put("chosen", chosen.contains(id));
      n.put("winner", subsetWinner.containsValue(id));
    }

    List<Map<String, Object>> sets = new ArrayList<>();
    for (Map.Entry<Integer, List<String>> e : setTables.entrySet()) {
      sets.add(Map.of("id", e.getKey(), "tables", e.getValue()));
    }

    long physical = nodes.values().stream().filter(SearchTrace::isPhysical).count();
    Map<String, Object> summary = new LinkedHashMap<>();
    summary.put("registered", nodes.size());
    summary.put("registered_logical", nodes.size() - physical);
    summary.put("registered_physical", physical);
    summary.put("rules_attempted", rulesAttempted);
    summary.put("rules_produced", rulesProduced);
    summary.put("relsets", setTables.size());
    summary.put("subsets", subsetWinner.size());
    summary.put("winners", subsetWinner.values().stream().filter(Objects::nonNull).distinct().count());
    summary.put("chosen", chosen.size());

    out.put("optimizer", "calcite");
    out.put("query", query);
    out.put("sql", sql);
    out.put("events", events);
    out.put("nodes", nodeList);
    out.put("sets", sets);
    out.put("timeline", timeline);
    out.put("summary", summary);
    out.put("final_plan", rootBest == null ? null : tree(rootBest, mq, 0));
  }

  public void write(String path) throws Exception {
    File f = new File(path);
    if (f.getParentFile() != null) f.getParentFile().mkdirs();
    new ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(f, out);
    System.err.println(query + ": " + out.get("summary"));
  }

  // ---------------- helpers ----------------

  private static boolean isPhysical(RelNode rel) {
    Convention c = rel.getTraitSet().getTrait(ConventionTraitDef.INSTANCE);
    return c != null && c != Convention.NONE;
  }

  private static String[] parseSubset(RelSubset s) {
    Matcher m = SUBSET.matcher(s.toString());   // "RelSubset#12.ENUMERABLE.[]"
    return m.find() ? new String[] {m.group(1), m.group(2)} : new String[] {"-1", s.toString()};
  }

  /** {startup, total} from a PgCost, or null if infinite (e.g. logical nodes). */
  private static double[] cost(RelOptCost c) {
    if (c == null || c.isInfinite()) return null;
    if (c instanceof PgCost) {
      PgCost p = (PgCost) c;
      return new double[] {p.startup, p.total};
    }
    return new double[] {0, c.getCpu()};
  }

  private static List<String> tablesOf(RelNode rel, RelMetadataQuery mq) {
    TreeSet<String> t = new TreeSet<>();
    try {
      Set<RelTableRef> refs = mq.getTableReferences(rel);
      if (refs != null) {
        for (RelTableRef r : refs) {
          List<String> q = r.getQualifiedName();
          t.add(q.get(q.size() - 1));
        }
      }
    } catch (Throwable ignored) { }
    return new ArrayList<>(t);
  }

  private static void collect(RelNode rel, Set<Integer> ids, int depth) {
    if (rel == null || depth > 30) return;
    ids.add(rel.getId());
    for (RelNode in : rel.getInputs()) {
      collect(in instanceof RelSubset ? ((RelSubset) in).getBest() : in, ids, depth + 1);
    }
  }
}
