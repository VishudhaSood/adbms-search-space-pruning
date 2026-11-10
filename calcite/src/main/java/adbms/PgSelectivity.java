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
  private final PgStats stats;

  public PgSelectivity(PgStats stats) {
    this.stats = stats;
  }

  record Origin(String table, String column) {}

  @Override
  public Double getSelectivity(RelNode rel, RelMetadataQuery mq, RexNode predicate) {
    if (predicate == null || predicate.isAlwaysTrue()) return 1.0;
    double sel = 1.0;
    for (RexNode conj : RelOptUtil.conjunctions(predicate)) {   // AND: multiply, like PG
      Double s = conjunctSelectivity(rel, conj);
      sel *= (s != null) ? s : RelMdUtil.guessSelectivity(conj);
    }
    return sel;
  }

  private Double conjunctSelectivity(RelNode rel, RexNode conj) {
    if (conj.getKind() != SqlKind.EQUALS) return null;
    List<RexNode> ops = ((RexCall) conj).getOperands();
    RexNode l = RexUtil.removeCast(ops.get(0));
    RexNode r = RexUtil.removeCast(ops.get(1));

    // Join condition: col = col  ->  (1-nf1)(1-nf2) / max(nd1, nd2)
    if (l instanceof RexInputRef a && r instanceof RexInputRef b) {
      Origin oa = origin(rel, a.getIndex());
      Origin ob = origin(rel, b.getIndex());
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
      Origin o = origin(rel, ref.getIndex());
      if (o == null) return null;
      PgStats.Column c = stats.column(o.table(), o.column());
      if (c == null) return null;

      int i = c.mcvVals.indexOf(literalText(lit));
      if (i >= 0) return c.mcvFreqs.get(i);                       // value is an MCV

      double sumMcv = c.mcvFreqs.stream().mapToDouble(Double::doubleValue).sum();
      double rest = stats.nDistinct(o.table(), o.column()) - c.mcvVals.size();
      if (rest <= 0) return 0.0;                                  // all values are MCVs, this isn't one
      return (1 - sumMcv - c.nullFrac) / rest;                    // spread the rest evenly
    }
    return null;
  }

  /** Follow output field i of rel down to the base-table column it comes from. */
  private Origin origin(RelNode rel, int i) {
    if (rel instanceof RelSubset s) {                             // Volcano's equivalence sets
      RelNode inner = s.getBest() != null ? s.getBest() : s.getOriginal();
      return inner == null ? null : origin(inner, i);
    }
    if (rel instanceof TableScan ts) {
      List<String> name = ts.getTable().getQualifiedName();
      return new Origin(name.get(name.size() - 1),
                        ts.getRowType().getFieldList().get(i).getName());
    }
    if (rel instanceof Filter f) return origin(f.getInput(), i);
    if (rel instanceof Sort s) return origin(s.getInput(), i);
    if (rel instanceof Project p) {
      RexNode e = p.getProjects().get(i);
      return e instanceof RexInputRef ref ? origin(p.getInput(), ref.getIndex()) : null;
    }
    if (rel instanceof Join j) {
      int nLeft = j.getLeft().getRowType().getFieldCount();
      return i < nLeft ? origin(j.getLeft(), i) : origin(j.getRight(), i - nLeft);
    }
    return null;
  }

  private static String literalText(RexLiteral lit) {
    Object v = lit.getValue();
    if (v instanceof NlsString ns) return ns.getValue();
    if (v instanceof BigDecimal bd) return bd.stripTrailingZeros().toPlainString();
    return String.valueOf(v);
  }
}