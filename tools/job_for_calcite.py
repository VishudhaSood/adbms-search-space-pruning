#!/usr/bin/env python3
"""Rewrite the JOB queries into the form Calcite plans (task ii, step 2). Original files are not changed.

For every job/<name>.sql it writes job_calcite/<name>.sql with four changes:
  1. FROM order: tables are reordered so that each one has a join predicate to an earlier one. Calcite's
     starting join tree follows the FROM list; with a table that links to nothing before it, the start would
     contain a cross product, which our `nocross` rules never remove. The order changes as little as possible:
     the first table stays first, and each step takes the earliest remaining table (in JOB's order) that
     connects. PostgreSQL ignores FROM order for plain FROM lists, so its plans are not affected.
  2. Aliases in table names: `title AS t` becomes `"title__t" AS "t"`. Calcite's scans don't keep FROM-list
     aliases, so self-joins (title AS t1, title AS t2) would be indistinguishable in the plan. Main.java
     registers one table per `<table>__<alias>` name; PgStats maps it back to `<table>` for statistics.
     The alias is what pg_lab hints need (task iii).
  3. Quoting: every alias, column and output name is double-quoted, because some JOB names (role, name, link,
     the alias "at", ...) clash with Calcite's keywords. PostgreSQL names are lower case, which is what we quote.
  4. `!=` becomes `<>` (Calcite's default parser rejects `!=`; 20 JOB queries use it).
String literals are never touched. It also writes job_calcite/manifest.json: per query, the tables, the old and
new FROM order, and whether the order changed.

Run from the repo root:   python3 tools/job_for_calcite.py [job_dir] [out_dir]      (defaults: job, job_calcite)
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_space_size import parse, join_graph

LITERAL = re.compile(r"'(?:[^']|'')*'")


def split_literals(sql):
    """-> list of (is_literal, text) pieces."""
    out, pos = [], 0
    for m in LITERAL.finditer(sql):
        out.append((False, sql[pos:m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    out.append((False, sql[pos:]))
    return out


def from_items(sql):
    """-> list of (table, alias) in FROM order, read from a JOB query (FROM t1 AS a, t2 AS b ... WHERE)."""
    code = LITERAL.sub("''", sql)
    m = re.search(r"\bFROM\b(.*?)\bWHERE\b", code, re.I | re.S)
    items = []
    for part in m.group(1).split(","):
        w = re.findall(r"\w+", part)
        if len(w) == 3 and w[1].upper() == "AS":
            items.append((w[0].lower(), w[2].lower()))
        elif len(w) == 2:
            items.append((w[0].lower(), w[1].lower()))
        elif len(w) == 1:
            items.append((w[0].lower(), w[0].lower()))
        else:
            raise ValueError(f"can't read FROM item {part.strip()!r}")
    return items


def connected_order(aliases, adj):
    """Earliest-connecting order: keep the first table, then repeatedly the first remaining table (in the
    original order) with a predicate to a table already placed."""
    n = len(aliases)
    order, placed = [0], 1
    remaining = list(range(1, n))
    while remaining:
        for k, i in enumerate(remaining):
            if adj[i] & placed:
                order.append(i)
                placed |= 1 << i
                remaining.pop(k)
                break
        else:                                   # graph not connected: keep JOB's order for the rest
            order += remaining
            break
    return order


def rewrite(sql):
    items = from_items(sql)
    aliases = [a for _, a in items]
    names, preds = parse(sql)                   # same parser and graph as search_space_size.py
    assert names == aliases, (names, aliases)
    adj = join_graph(aliases, preds, implied=False)   # Calcite only sees the written predicates
    order = connected_order(aliases, adj)
    new_from = ",\n     ".join(f'"{items[i][0]}__{items[i][1]}" AS "{items[i][1]}"' for i in order)
    alias_set = set(aliases)

    out = []
    for is_lit, text in split_literals(sql):
        if is_lit:
            out.append(text)
            continue
        text = re.sub(r"\bFROM\b.*?(?=\bWHERE\b)", lambda _: "FROM " + new_from + "\n", text, flags=re.I | re.S)
        text = re.sub(r"\b(\w+)\.(\w+)\b",
                      lambda m: f'"{m.group(1).lower()}"."{m.group(2).lower()}"' if m.group(1).lower() in alias_set
                      else m.group(0), text)
        text = re.sub(r"\bAS\s+(\w+)\b", lambda m: f'AS "{m.group(1).lower()}"', text, flags=re.I)
        text = text.replace("!=", "<>")
        out.append(text)
    new_sql = "".join(out).strip().rstrip(";") + ";\n"
    info = {
        "tables": len(items),
        "from_original": [f"{t} AS {a}" for t, a in items],
        "from_calcite": [f"{items[i][0]} AS {items[i][1]}" for i in order],
        "reordered": order != list(range(len(items))),
        "self_join_tables": sorted({t for t, _ in items if sum(1 for x, _ in items if x == t) > 1}),
    }
    return new_sql, info


def main(argv):
    src = argv[0] if len(argv) > 0 else "job"
    dst = argv[1] if len(argv) > 1 else "job_calcite"
    os.makedirs(dst, exist_ok=True)
    files = sorted((f for f in os.listdir(src) if re.match(r"\d+[a-z]\.sql$", f)),
                   key=lambda f: (int(re.match(r"\d+", f).group()), f))
    manifest = {}
    for f in files:
        name = f[:-4]
        new_sql, info = rewrite(open(os.path.join(src, f)).read())
        open(os.path.join(dst, f), "w").write(new_sql)
        manifest[name] = info
    json.dump(manifest, open(os.path.join(dst, "manifest.json"), "w"), indent=1)
    re_n = sum(1 for v in manifest.values() if v["reordered"])
    sj = sorted(k for k, v in manifest.items() if v["self_join_tables"])
    print(f"{len(files)} queries -> {dst}/ ; FROM order changed in {re_n}; self-joins in {len(sj)}: {' '.join(sj)}")


if __name__ == "__main__":
    main(sys.argv[1:])
