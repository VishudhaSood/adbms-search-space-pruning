package adbms;

import java.util.List;
import org.apache.calcite.DataContext;
import org.apache.calcite.linq4j.Enumerable;
import org.apache.calcite.linq4j.Linq4j;
import org.apache.calcite.rel.type.RelDataType;
import org.apache.calcite.rel.type.RelDataTypeFactory;
import org.apache.calcite.schema.ScannableTable;
import org.apache.calcite.schema.Statistic;
import org.apache.calcite.schema.Statistics;
import org.apache.calcite.schema.Table;
import org.apache.calcite.schema.impl.AbstractTable;
import org.apache.calcite.util.ImmutableBitSet;

/** Columns come from PostgreSQL; row count comes from our JSON. Used for planning only. */
public class StatTable extends AbstractTable implements ScannableTable {
  private final Table pgTable;
  private final Statistic statistic;

  public StatTable(Table pgTable, double rowCount, List<ImmutableBitSet> keys) {
    this.pgTable = pgTable;
    this.statistic = Statistics.of(rowCount, keys);
  }

  @Override public RelDataType getRowType(RelDataTypeFactory typeFactory) {
    return pgTable.getRowType(typeFactory);
  }

  @Override public Statistic getStatistic() {
    return statistic;
  }

  @Override public Enumerable<Object[]> scan(DataContext root) {
    return Linq4j.emptyEnumerable();   // we only plan; executing on PG comes later (task iii)
  }
}