package adbms;

import java.math.BigDecimal;
import java.util.List;
import org.apache.calcite.plan.RelOptUtil;
import org.apache.calcite.plan.volcano.RelSubset;
import org.apache.calcite.rel.RelNode;
import org.apache.calcite.rel.core.Filter;
import org.apache.calcite.rel.core.Join;
import org.apache.calcite.rel.core.Project;
import org.apache.calcite.rel.core.Sort;
import org.apache.calcite.rel.core.TableScan;
import org.apache.calcite.rel.metadata.BuiltInMetadata;
import org.apache.calcite.rel.metadata.RelColumnOrigin;
import org.apache.calcite.rel.metadata.RelMdUtil;
import org.apache.calcite.rel.metadata.RelMetadataQuery;
import org.apache.calcite.rex.RexCall;
import org.apache.calcite.rex.RexInputRef;
import org.apache.calcite.rex.RexLiteral;
import org.apache.calcite.rex.RexNode;
import org.apache.calcite.rex.RexUtil;
import org.apache.calcite.sql.SqlKind;
import org.apache.calcite.util.NlsString;

/** PostgreSQL-style selectivity for col = const and col = col. Everything else: Calcite's guess. */
public class PgSelectivity implements BuiltInMetadata.Selectivity.Handler {
  private static final boolean DEBUG = true;   // delete the debug lines before pushing

  private final PgStats stats;

  public PgSelectivity(PgStats stats) {
    this.stats = stats;
  }

  record Origin(String table, String column) {}

  // Calcite's RelMdSelectivity has type-specific methods and the most specific one wins,
  // so without these overloads our generic method below is skipped for these node types.
  public Double getSelectivity(Join rel, RelMetadataQuery mq, RexNode predicate) {
    return getSelectivity((RelNode) rel, mq, predicate);
  }
  public Double getSelectivity(Filter rel, RelMetadataQuery mq, RexNode predicate) {
    return getSelectivity((RelNode) rel, mq, predicate);
  }
  public Double getSelectivity(TableScan rel, RelMetadataQuery mq, RexNode predicate) {
    return getSelectivity((RelNode) rel, mq, predicate);
  }
  public Double getSelectivity(Project rel, RelMetadataQuery mq, RexNode predicate) {
    return getSelectivity((RelNode) rel, mq, predicate);
  }
  public Double getSelectivity(Sort rel, RelMetadataQuery mq, RexNode predicate) {
    return getSelectivity((RelNode) rel, mq, predicate);
  }

  @Override
  public Double getSelectivity(RelNode rel, RelMetadataQuery mq, RexNode predicate) {
    if (predicate == null || predicate.isAlwaysTrue()) return 1.0;
    double sel = 1.0;
    for (RexNode conj : RelOptUtil.conjunctions(predicate)) {   // AND: multiply, like PG
      Double s = conjunctSelectivity(rel, mq, conj);
      sel *= (s != null) ? s : RelMdUtil.guessSelectivity(conj);
    }
    if (DEBUG) System.err.println("sel " + rel.getClass().getSimpleName()
        + " " + predicate + " -> " + sel);
    return sel;
  }

  private Double conjunctSelectivity(RelNode rel, RelMetadataQuery mq, RexNode conj) {
    if (conj.getKind() == SqlKind.SEARCH) {                       // Calcite may rewrite x = 3 as SEARCH
      conj = RexUtil.expandSearch(rel.getCluster().getRexBuilder(), null, conj);
    }
    if (conj.getKind() != SqlKind.EQUALS) return null;
    List<RexNode> ops = ((RexCall) conj).getOperands();
    RexNode l = RexUtil.removeCast(ops.get(0));
    RexNode r = RexUtil.removeCast(ops.get(1));

    // Join condition: col = col  ->  (1-nf1)(1-nf2) / max(nd1, nd2)
    if (l instanceof RexInputRef a && r instanceof RexInputRef b) {
      Origin oa = origin(rel, mq, a.getIndex());
      Origin ob = origin(rel, mq, b.getIndex());
      if (DEBUG) System.err.println("  join " + conj + " left=" + oa + " right=" + ob);
      if (oa == null || ob == null) return null;
      PgStats.Column ca = stats.column(oa.table(), oa.column());
      PgStats.Column cb = stats.column(ob.table(), ob.column());
      if (ca == null || cb == null) return null;
      double nd = Math.max(stats.nDistinct(oa.table(), oa.column()),
                           stats.nDistinct(ob.table(), ob.column()));
      return (1 - ca.nullFrac) * (1 - cb.nullFrac) / nd;
    }

    // Filter: col = const (either side)
    if (l instanceof RexLiteral && r instanceof RexInputRef) { RexNode t = l; l = r; r = t; }
    if (l instanceof RexInputRef ref && r instanceof RexLiteral lit) {
      Origin o = origin(rel, mq, ref.getIndex());
      PgStats.Column c = (o == null) ? null : stats.column(o.table(), o.column());
      String v = literalText(lit);
      if (DEBUG) System.err.println("  filter " + conj + " origin=" + o + " literal=" + v
          + " mcv=" + (c == null ? "no stats" : c.mcvVals));
      if (c == null) return null;

      int i = indexOfValue(c.mcvVals, v);
      if (i >= 0) return c.mcvFreqs.get(i);                       // value is an MCV

      double sumMcv = c.mcvFreqs.stream().mapToDouble(Double::doubleValue).sum();
      double rest = stats.nDistinct(o.table(), o.column()) - c.mcvVals.size();
      if (rest <= 0) return 0.0;                                  // all values are MCVs, this isn't one
      return (1 - sumMcv - c.nullFrac) / rest;                    // spread the rest evenly
    }
    return null;
  }

  /** Base-table column behind output field i of rel. Our own walk first, then Calcite's lookup. */
  private Origin origin(RelNode rel, RelMetadataQuery mq, int i) {
    Origin o = walk(rel, i, 0);
    if (o == null && !(rel instanceof RelSubset)) {
      RelColumnOrigin co = mq.getColumnOrigin(rel, i);
      if (co != null) {
        List<String> name = co.getOriginTable().getQualifiedName();
        String col = co.getOriginTable().getRowType().getFieldList()
            .get(co.getOriginColumnOrdinal()).getName();
        o = new Origin(name.get(name.size() - 1), col);
      }
    }
    return o;
  }

  private Origin walk(RelNode rel, int i, int depth) {
    if (rel == null || depth > 25) return null;                   // guard against cycles in Volcano
    if (rel instanceof RelSubset s) {                             // try every equivalent plan in the set
      Origin o = walk(s.getOriginal(), i, depth + 1);
      if (o != null) return o;
      for (RelNode alt : s.getRelList()) {
        o = walk(alt, i, depth + 1);
        if (o != null) return o;
      }
      return null;
    }
    if (rel instanceof TableScan ts) {
      List<String> name = ts.getTable().getQualifiedName();
      return new Origin(name.get(name.size() - 1),
                        ts.getRowType().getFieldList().get(i).getName());
    }
    if (rel instanceof Filter f) return walk(f.getInput(), i, depth + 1);
    if (rel instanceof Sort s) return walk(s.getInput(), i, depth + 1);
    if (rel instanceof Project p) {
      RexNode e = p.getProjects().get(i);
      return e instanceof RexInputRef ref ? walk(p.getInput(), ref.getIndex(), depth + 1) : null;
    }
    if (rel instanceof Join j) {
      int nLeft = j.getLeft().getRowType().getFieldCount();
      return i < nLeft ? walk(j.getLeft(), i, depth + 1)
                       : walk(j.getRight(), i - nLeft, depth + 1);
    }
    return null;
  }

  private static String literalText(RexLiteral lit) {
    Object v = lit.getValue();
    if (v instanceof NlsString ns) return ns.getValue();
    if (v instanceof BigDecimal bd) return bd.stripTrailingZeros().toPlainString();
    return String.valueOf(v);
  }

  /** Match "3" against "3", "3.0", etc. */
  private static int indexOfValue(List<String> mcvs, String v) {
    for (int k = 0; k < mcvs.size(); k++) {
      String m = mcvs.get(k);
      if (m.equals(v)) return k;
      try {
        if (new BigDecimal(m).compareTo(new BigDecimal(v)) == 0) return k;
      } catch (NumberFormatException ignored) { }
    }
    return -1;
  }
}