package adbms;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.File;
import java.io.IOException;
import java.util.*;

/** PostgreSQL statistics loaded from the JSON written by sql/extract_stats.sql. */
public class PgStats {

  public static class Column {
    public double nullFrac;
    public double nDistinctRaw;                 // as stored by PG; negative = fraction of rows
    public List<String> mcvVals = new ArrayList<>();
    public List<Double> mcvFreqs = new ArrayList<>();
  }

  public static class Table {
    public double reltuples;
    public double relpages;
    public final Map<String, Column> columns = new HashMap<>();
  }

  public final Map<String, Table> tables = new HashMap<>();
  public final Map<String, Double> costParams = new HashMap<>();

  public static PgStats load(String path) throws IOException {
    JsonNode root = new ObjectMapper().readTree(new File(path));
    PgStats s = new PgStats();

    root.get("cost_params").fields().forEachRemaining(e ->
        s.costParams.put(e.getKey(), Double.parseDouble(e.getValue().get("value").asText())));

    for (JsonNode t : root.get("tables")) {
      Table tbl = new Table();
      tbl.reltuples = t.get("reltuples").asDouble();
      tbl.relpages = t.get("relpages").asDouble();
      for (JsonNode c : t.get("columns")) {
        Column col = new Column();
        col.nullFrac = c.get("null_frac").asDouble();
        col.nDistinctRaw = c.get("n_distinct").asDouble();
        col.mcvVals = parsePgArray(c.get("most_common_vals"));
        if (c.hasNonNull("most_common_freqs")) {
          for (JsonNode f : c.get("most_common_freqs")) col.mcvFreqs.add(f.asDouble());
        }
        tbl.columns.put(c.get("column").asText().toLowerCase(), col);
      }
      s.tables.put(t.get("table").asText().toLowerCase(), tbl);
    }
    return s;
  }

  /** "{0,1,2}" -> ["0","1","2"]. Fine for numbers; text values with commas would need more care. */
  static List<String> parsePgArray(JsonNode n) {
    List<String> out = new ArrayList<>();
    if (n == null || n.isNull()) return out;
    String s = n.asText().trim();
    if (s.startsWith("{")) s = s.substring(1, s.length() - 1);
    if (s.isEmpty()) return out;
    for (String v : s.split(",")) out.add(v.replace("\"", "").trim());
    return out;
  }

  public Column column(String table, String col) {
    Table t = tables.get(table.toLowerCase());
    return t == null ? null : t.columns.get(col.toLowerCase());
  }

  /** Number of distinct values, converting PG's negative n_distinct (a fraction of rows). */
  public double nDistinct(String table, String col) {
    Column c = column(table, col);
    if (c == null) return -1;
    double rows = tables.get(table.toLowerCase()).reltuples;
    return c.nDistinctRaw < 0 ? -c.nDistinctRaw * rows : c.nDistinctRaw;
  }
}