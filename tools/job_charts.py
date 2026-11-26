#!/usr/bin/env python3
"""Task (iv) on JOB: three charts + a band table, from committed data only.

  1. Growth:   per number of tables (median over the JOB queries of that size), log scale:
               whole space (complete bushy plans, no cross products, x 3 join methods), ordered DP join steps,
               PostgreSQL paths considered / retained, Calcite RelNodes bottom-up / top-down.
  2. Planning time vs number of tables (median, log scale): PostgreSQL (untraced), Calcite bottom-up, Calcite top-down
               (top-down stops at the 300 s limit).
  3. Where PostgreSQL prunes, per size band: share of considered paths cut at precheck / rejected on arrival /
               evicted later / retained.

Inputs:  stats/job_counts.json (tools/job_counts.py), stats/search_space_size_job.json (tools/search_space_size.py)
Usage (repo root):  python3 tools/job_charts.py   ->  viz/job_charts.html (self-contained, open in a browser)
"""
import json, math, os, statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
J = lambda *p: os.path.join(ROOT, *p)


def load(p):
    with open(J(p)) as f:
        return json.load(f)


counts = load("stats/job_counts.json")
space = {}
for r in load("stats/search_space_size_job.json"):
    # one row per query; for the few queries counted on two graphs, prefer PostgreSQL's graph
    if r["query"] not in space or r.get("graph") == "pg":
        space[r["query"]] = r

BU, TD = counts["modes"]
by_t = {}
for q in counts["queries"]:
    by_t.setdefault(q["tables"], []).append(q)
TABLES = sorted(by_t)


def med(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def cal(q, mode, key):
    c = (q.get("calcite") or {}).get(mode) or {}
    return c.get(key)


def pg(q, key):
    return (q.get("pg") or {}).get(key)


def sp(q, key):
    return (space.get(q["query"]) or {}).get(key)


def series(fn):
    return [(t, med([fn(q) for q in by_t[t]])) for t in TABLES]


SHORT = {"Whole space: complete plans (no cross, ×3 methods)": "Whole space", "Ordered DP join steps (no cross)": "DP steps",
         "PostgreSQL: paths considered": "PG considered", "PostgreSQL: paths retained": "PG retained",
         "Calcite bottom-up: RelNodes": "Calcite bottom-up", "Calcite top-down: RelNodes": "Calcite top-down"}
GROWTH = [
    ("Whole space: complete plans (no cross, ×3 methods)", "var(--ref)", "6 4", series(lambda q: sp(q, "bushy_nocross_physical"))),
    ("Ordered DP join steps (no cross)", "var(--ref2)", "2 3", series(lambda q: sp(q, "steps_nocross"))),
    ("PostgreSQL: paths considered", "var(--s1)", "", series(lambda q: pg(q, "considered"))),
    ("PostgreSQL: paths retained", "var(--s3)", "", series(lambda q: pg(q, "retained"))),
    ("Calcite bottom-up: RelNodes", "var(--s2)", "", series(lambda q: cal(q, BU, "generated"))),
    ("Calcite top-down: RelNodes", "var(--s7)", "", series(lambda q: cal(q, TD, "generated"))),
]
TIME = [
    ("PostgreSQL (untraced)", "var(--s1)", "", series(lambda q: pg(q, "untraced_plan_ms"))),
    ("Calcite bottom-up", "var(--s2)", "", series(lambda q: cal(q, BU, "plan_ms"))),
    ("Calcite top-down (300 s limit)", "var(--s7)", "", series(lambda q: cal(q, TD, "plan_ms"))),
]

BANDS = [("4–6", 4, 6), ("7–8", 7, 8), ("9–10", 9, 10), ("11–12", 11, 12)]
PARTS = [("precheck", "Cut at precheck (never built)", "var(--precheck)"),
         ("rejected", "Rejected on arrival", "var(--rejected)"),
         ("evicted", "Evicted later", "var(--evicted)"),
         ("retained", "Retained", "var(--kept)")]


def band_rows():
    rows = []
    for name, lo, hi in BANDS:
        qs = [q["pg"] for t in TABLES if lo <= t <= hi for q in by_t[t] if q.get("pg")]
        if not qs:
            continue
        tot = {k: sum(p[k] for p in qs) for k, *_ in PARTS}
        cons = sum(p["considered"] for p in qs)
        # retained is counted as kept - evicted; what is left is (kept - evicted - retained) = 0 by the identities
        rows.append({"band": name, "queries": len(qs), "considered": cons,
                     "share": {k: tot[k] / cons for k in tot},
                     "bu_gen": med([cal(q, BU, "generated") for t in TABLES if lo <= t <= hi for q in by_t[t]]),
                     "td_gen": med([cal(q, TD, "generated") for t in TABLES if lo <= t <= hi for q in by_t[t]])})
    return rows


def fmt(v):
    if v is None:
        return "–"
    if v >= 1e9:
        m, e = f"{v:.2e}".split("e")
        return f"{float(m):.2g}e{int(e)}"
    if v >= 1e6:
        return f"{v/1e6:.3g} M"
    if v >= 1e4:
        return f"{v/1e3:.0f} k"
    if v >= 1e3 and math.log10(v) % 1 == 0:
        return f"{v/1e3:.0f} k"
    if v >= 100:
        return f"{v:,.0f}"
    return f"{v:.3g}"


def fmt_ms(v):
    if v is None:
        return "–"
    if v >= 1000:
        x = v / 1000
        return f"{x:,.0f} s" if x >= 100 else f"{x:.3g} s"
    return f"{v:.3g} ms"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def line_chart(title, sub, ser, unit_fmt, y_label):
    W, H, L, R, T, B = 760, 380, 70, 250, 20, 46
    pw, ph = W - L - R, H - T - B
    vals = [v for *_, s in ser for _, v in s if v]
    lo, hi = math.floor(math.log10(min(vals))), math.ceil(math.log10(max(vals)))
    xs = TABLES
    x = lambda t: L + (t - xs[0]) / (xs[-1] - xs[0]) * pw
    y = lambda v: T + ph - (math.log10(v) - lo) / (hi - lo) * ph
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}">']
    step = max(1, math.ceil((hi - lo) / 8))
    for e in range(lo, hi + 1):
        if (e - lo) % step:
            continue
        yy = y(10 ** e)
        o.append(f'<line x1="{L}" x2="{L+pw}" y1="{yy:.1f}" y2="{yy:.1f}" class="grid"/>'
                 f'<text x="{L-8}" y="{yy+4:.1f}" class="ax" text-anchor="end">{esc(unit_fmt(10**e))}</text>')
    for t in xs:
        o.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{T+ph}" y2="{T+ph+5}" class="tick"/>'
                 f'<text x="{x(t):.1f}" y="{T+ph+19}" class="ax" text-anchor="middle">{t}</text>')
    o.append(f'<line x1="{L}" x2="{L+pw}" y1="{T+ph}" y2="{T+ph}" class="axis"/>')
    o.append(f'<text x="{L+pw/2}" y="{H-6}" class="ax" text-anchor="middle">number of tables in the query</text>')
    o.append(f'<text x="14" y="{T+ph/2}" class="ax" text-anchor="middle" transform="rotate(-90 14 {T+ph/2})">{esc(y_label)} (log scale)</text>')
    labels = []
    for name, col, dash, s in ser:
        pts = [(t, v) for t, v in s if v]
        if not pts:
            continue
        d = " ".join(f"{'M' if i == 0 else 'L'}{x(t):.1f},{y(v):.1f}" for i, (t, v) in enumerate(pts))
        o.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2" stroke-dasharray="{dash}" stroke-linejoin="round"/>')
        for t, v in pts:
            n = len(by_t[t])
            o.append(f'<g class="pt"><circle cx="{x(t):.1f}" cy="{y(v):.1f}" r="11" fill="transparent"/>'
                     f'<circle cx="{x(t):.1f}" cy="{y(v):.1f}" r="4" fill="{col}" stroke="var(--surface)" stroke-width="2"/>'
                     f'<title>{esc(name)}\n{t} tables (median of {n} quer{"y" if n == 1 else "ies"}): {esc(unit_fmt(v))}</title></g>')
        lt, lv = pts[-1]
        labels.append([y(lv), x(lt), name, col, unit_fmt(lv)])
    labels.sort()
    for i in range(1, len(labels)):  # nudge end labels apart
        labels[i][0] = max(labels[i][0], labels[i - 1][0] + 15)
    for yy, xx, name, col, v in labels:
        o.append(f'<rect x="{L+pw+10}" y="{yy-5:.1f}" width="10" height="3" rx="1" fill="{col}"/>'
                 f'<text x="{L+pw+25}" y="{yy:.1f}" class="lab">{esc(SHORT.get(name, name))}</text>')
    o.append("</svg>")
    legend = "".join(f'<span class="key"><i style="background:{c}"></i>{esc(n)}</span>' for n, c, *_ in ser)
    return f'<section><h2>{esc(title)}</h2><p class="sub">{sub}</p><div class="legend">{legend}</div>{"".join(o)}</section>'


def stacked(rows):
    W, L, R, rowh = 760, 70, 20, 44
    H = 30 + rowh * len(rows) + 30
    pw = W - L - R
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Where PostgreSQL prunes">']
    for p in range(0, 101, 25):
        xx = L + pw * p / 100
        o.append(f'<line x1="{xx}" x2="{xx}" y1="20" y2="{H-30}" class="grid"/><text x="{xx}" y="{H-12}" class="ax" text-anchor="middle">{p}%</text>')
    for i, r in enumerate(rows):
        yy = 26 + i * rowh
        o.append(f'<text x="{L-8}" y="{yy+18}" class="ax" text-anchor="end">{r["band"]}</text>')
        xx = L
        for k, name, col in PARTS:
            w = pw * r["share"][k]
            o.append(f'<g><rect x="{xx+1:.1f}" y="{yy}" width="{max(w-2,0):.1f}" height="26" rx="3" fill="{col}"/>'
                     f'<title>{r["band"]} tables, {name}: {r["share"][k]*100:.1f}% of {r["considered"]:,} paths ({r["queries"]} queries)</title></g>')
            if w > 44:
                o.append(f'<text x="{xx+w/2:.1f}" y="{yy+17}" class="in" text-anchor="middle">{r["share"][k]*100:.0f}%</text>')
            xx += w
    o.append("</svg>")
    legend = "".join(f'<span class="key"><i style="background:{c}"></i>{esc(n)}</span>' for _, n, c in PARTS)
    return ('<section><h2>3. Where PostgreSQL prunes, by query size</h2><p class="sub">Share of all paths PostgreSQL considered '
            'in each band (summed over the queries of that band). Calcite bottom-up prunes nothing during the search: every '
            f'RelNode it creates stays in the memo.</p><div class="legend">{legend}</div>{"".join(o)}</section>')


def table(rows):
    h = ["Tables", "Queries", "PG considered (sum)", "precheck", "rejected", "evicted", "retained",
         "Calcite BU RelNodes (median)", "Calcite TD RelNodes (median)"]
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in [
        r["band"], r["queries"], f'{r["considered"]:,}',
        *(f'{r["share"][k]*100:.1f}%' for k, *_ in PARTS), fmt(r["bu_gen"]), fmt(r["td_gen"])]) + "</tr>" for r in rows)
    per = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in [
        t, len(by_t[t]), fmt(med([sp(q, "bushy_nocross_physical") for q in by_t[t]])),
        fmt(med([sp(q, "steps_nocross") for q in by_t[t]])),
        fmt(med([pg(q, "considered") for q in by_t[t]])), fmt(med([pg(q, "retained") for q in by_t[t]])),
        fmt(med([cal(q, BU, "generated") for q in by_t[t]])), fmt(med([cal(q, TD, "generated") for q in by_t[t]])),
        fmt_ms(med([pg(q, "untraced_plan_ms") for q in by_t[t]])), fmt_ms(med([cal(q, BU, "plan_ms") for q in by_t[t]])),
        fmt_ms(med([cal(q, TD, "plan_ms") for q in by_t[t]]))]) + "</tr>" for t in TABLES)
    h2 = ["Tables", "Queries", "Whole space (plans)", "DP steps", "PG considered", "PG retained", "Calcite BU", "Calcite TD",
          "PG planning", "BU planning", "TD planning"]
    th = lambda hs: "<tr>" + "".join(f"<th>{x}</th>" for x in hs) + "</tr>"
    return (f'<section><h2>Table view</h2><p class="sub">Per band (PostgreSQL shares of considered paths):</p>'
            f'<table>{th(h)}{body}</table><p class="sub">Per number of tables (medians; – = not traced / not finished):</p>'
            f'<table>{th(h2)}{per}</table></section>')


rows = band_rows()
html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Task (iv) on JOB: growth, planning time, pruning</title>
<style>
.viz-root{{color-scheme:light;--surface:#fff;--text:#191919;--text2:#666;--grid:#e6e6e6;--ref:#8a8f98;--ref2:#5f6670;
--s1:#257de0;--s2:#f47230;--s3:#00b894;--s7:#6a4ce2;--precheck:#6250d6;--rejected:#d6457a;--evicted:#c98a00;--kept:#1baf7a}}
@media (prefers-color-scheme:dark){{.viz-root{{color-scheme:dark;--surface:#191919;--text:#efefef;--text2:#9c9c9c;--grid:#333;
--ref:#9aa0a8;--ref2:#c3c7cd;--s1:#338ced;--s2:#e76624;--s3:#00a888;--s7:#9887ef}}}}
body{{margin:0;background:var(--surface)}}
.viz-root{{font:14px system-ui,-apple-system,Segoe UI,sans-serif;color:var(--text);background:var(--surface);max-width:820px;margin:0 auto;padding:24px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:17px;margin:28px 0 4px}} .sub{{color:var(--text2);margin:2px 0 8px;line-height:1.4}}
svg{{width:100%;height:auto;display:block}} .grid{{stroke:var(--grid)}} .axis,.tick{{stroke:var(--text2)}}
.ax{{fill:var(--text2);font-size:12px}} .lab{{fill:var(--text);font-size:12px}} .in{{fill:#fff;font-size:12px;font-weight:600}}
.pt:hover circle:last-of-type{{r:6}} .legend{{display:flex;flex-wrap:wrap;gap:6px 16px;margin:6px 0}}
.key{{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--text)}} .key i{{width:14px;height:4px;border-radius:2px;display:inline-block}}
table{{border-collapse:collapse;font-size:12px;width:100%;margin-bottom:10px}} th,td{{border-bottom:1px solid var(--grid);padding:4px 6px;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
</style></head><body><div class="viz-root">
<h1>Task (iv) on JOB: how much each optimizer generates, keeps and spends</h1>
<p class="sub">JOB on imdb_s10 (correlated 10% sample). PostgreSQL: fair mode, geqo off, traced up to 12 tables. Calcite: bottom-up
= <code>{BU}</code>, top-down = <code>{TD}</code>. Points are medians over the queries with that many tables; hover a point for its value.
Units differ (complete plans, join steps, paths, RelNodes): compare slopes, not heights.</p>
{line_chart("1. Growth with the number of tables", "Whole space and DP steps are counted, not searched (tools/search_space_size.py).", GROWTH, fmt, "count")}
{line_chart("2. Planning time", "PostgreSQL time is untraced (EXPLAIN SUMMARY, log_min_messages = fatal). Calcite top-down hits its 300 s limit from 10 tables on.", TIME, fmt_ms, "planning time")}
{stacked(rows)}
{table(rows)}
</div></body></html>"""
os.makedirs(J("viz"), exist_ok=True)
with open(J("viz", "job_charts.html"), "w", encoding="utf-8") as f:
    f.write(html)
print(f"Wrote viz/job_charts.html ({len(html)//1024} KB): {len(counts['queries'])} queries, tables {TABLES[0]}-{TABLES[-1]}")
for r in rows:
    print(f"  {r['band']:>5} tables: {r['queries']:>2} queries, considered {r['considered']:>9,}  " +
          "  ".join(f"{k} {r['share'][k]*100:5.1f}%" for k, *_ in PARTS))
