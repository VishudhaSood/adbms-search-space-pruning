#!/usr/bin/env python3
"""Workstream B, step 2: one funnel per query, log scale, from the whole search space down to what each optimizer kept.

Rows, top to bottom (each row is its own bar, so the log scale never stacks):
  whole space   complete plans with / without cross products (x 3 join methods), bushy join trees, left-deep trees,
                ordered DP join steps                                      <- tools/search_space_size.py
  PostgreSQL    paths considered -> pruned at precheck (its own band) / built -> rejected on arrival / evicted later
                -> retained                                                <- traces/pg_<Q>.json (fair mode)
  Calcite       RelNodes registered, per search mode (bottom-up, bottom-up + sorts, top-down)  <- traces/calcite_<Q>*.json

Usage (repo root):  python3 tools/funnel_plot.py        -> viz/funnel.html (open in a browser; hover a bar for details)
"""
import json, math, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
J = lambda *p: os.path.join(ROOT, *p)

# Same colours as the viewer: grey = the whole space (math), PG status colours, Calcite orange.
GROUPS = {"space": "#8a8f98", "steps": "#5f6670", "pg": "#2a78d6", "precheck": "#6250d6", "rejected": "#d6457a",
          "evicted": "#c98a00", "kept": "#1baf7a", "cal": "#eb6834"}
CAL_MODES = [("_nosort", "Calcite bottom-up: RelNodes"), ("", "Calcite bottom-up + sorts: RelNodes"),
             ("_nosort_topdown", "Calcite top-down: RelNodes")]


def load(p):
    with open(p) as f:
        return json.load(f)


def rows_for(q, size):
    s = size.get(q)
    r = []
    if s:
        r += [("space", "Complete plans, with cross products (× 3 methods)", s["bushy_cross_physical"], True),
              ("space", "Complete plans, no cross products (× 3 methods)", s["bushy_nocross_physical"], False),
              ("space", "Join trees, any shape (bushy), no cross products", s["bushy_nocross"], False),
              ("space", "Join trees, left-deep only (the System R space)", s["leftdeep_nocross"], False),
              ("steps", "Ordered DP join steps (pairs of joinable sets)", s["steps_nocross"], False)]
    pgp = J("traces", f"pg_{q}.json")
    if os.path.exists(pgp):
        m = load(pgp)["summary"]
        r += [("pg", "PostgreSQL: paths considered", m["considered"], False),
              ("precheck", "  pruned at precheck (never built)", m["pruned_precheck"], False),
              ("pg", "  built", m["built"], False),
              ("rejected", "    rejected on arrival", m["pruned_on_arrival"], False),
              ("evicted", "    evicted later", m["evicted_later"], False),
              ("kept", "    retained", m["retained"], False)]
    for mode, label in CAL_MODES:
        p = J("traces", f"calcite_{q}{mode}.json")
        if os.path.exists(p):
            r.append(("cal", label, load(p)["summary"]["registered"], False))
    return r


def svg_for(q, rows, xmax):
    LW, BW, RH, PAD = 360, 500, 24, 26
    W, H = LW + BW + 90, PAD + RH * len(rows) + 22
    lg = lambda v: 0 if v <= 1 else math.log10(v) / math.log10(xmax) * BW
    out = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Search-space funnel for {q}">']
    k = 0
    while 10 ** k <= xmax:                                   # recessive grid at powers of ten
        x = LW + lg(10 ** k)
        out.append(f'<line x1="{x:.1f}" y1="{PAD - 6}" x2="{x:.1f}" y2="{H - 18}" class="grid"/>'
                   f'<text x="{x:.1f}" y="{H - 4}" class="tick" text-anchor="middle">10<tspan dy="-5" font-size="8">{k}</tspan></text>')
        k += 1
    for i, (g, label, v, light) in enumerate(rows):
        y = PAD + i * RH
        w = max(lg(v), 2 if v else 0)
        out.append(f'<g class="row"><title>{label.strip()}: {v:,}</title>'
                   f'<rect x="0" y="{y}" width="{W}" height="{RH}" class="hit"/>'
                   f'<text x="{6 + 9 * (len(label) - len(label.lstrip()))}" y="{y + 16}" class="lab">{("└ " if label.startswith(" ") else "") + label.strip()}</text>'
                   f'<rect x="{LW}" y="{y + 5}" width="{w:.1f}" height="{RH - 10}" rx="3" fill="{GROUPS[g]}" opacity="{0.45 if light else 1}"/>'
                   f'<text x="{LW + w + 6:.1f}" y="{y + 16}" class="val">{v:,}</text></g>')
    out.append("</svg>")
    return "".join(out)


def main():
    size = {}
    for s in load(J("stats", "search_space_size.json")):
        if s["query"] not in size or s.get("graph") == "pg":    # Q7: PostgreSQL's graph (with the implied b-e join)
            size[s["query"]] = s
    queries = [l.split("|", 1)[0] for l in open(J("tools", "queries.txt")) if "|" in l]
    allrows = {q: rows_for(q, size) for q in queries}
    xmax = 10 ** math.ceil(math.log10(max(v for r in allrows.values() for *_, v, _ in r if v) or 10))
    panels = []
    for q in queries:
        if not allrows[q]:
            continue
        s = size.get(q, {})
        note = " · whole-space numbers use PostgreSQL's join graph (it derives b–e from a.id = b.a_id = e.a_id)" if s.get("graph") == "pg" else ""
        panels.append(f'<section><h2>{q} <span>{s.get("tables", "?")} tables{note}</span></h2>{svg_for(q, allrows[q], xmax)}</section>')
    legend = "".join(f'<span><i style="background:{c}"></i>{t}</span>' for t, c in
                     [("whole search space (counted)", GROUPS["space"]), ("DP join steps", GROUPS["steps"]),
                      ("PostgreSQL", GROUPS["pg"]), ("pruned at precheck", GROUPS["precheck"]),
                      ("rejected on arrival", GROUPS["rejected"]), ("evicted later", GROUPS["evicted"]),
                      ("retained", GROUPS["kept"]), ("Calcite", GROUPS["cal"])])
    html = f"""<!DOCTYPE html><meta charset="utf-8"><title>Search-space funnel</title>
<style>
:root {{ --bg:#f7f8fa; --panel:#fff; --ink:#1d2430; --ink2:#4a5361; --ink3:#8a93a1; --line:#e3e6eb; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14171c; --panel:#1c2027; --ink:#e7eaee; --ink2:#b5bcc6; --ink3:#7d8693; --line:#2c323b; }} }}
body {{ margin:0; padding:24px; background:var(--bg); color:var(--ink); font:14px/1.45 system-ui, sans-serif; }}
h1 {{ font-size:20px; margin:0 0 4px; }} p {{ color:var(--ink2); max-width:95ch; margin:0 0 12px; }}
.legend {{ display:flex; flex-wrap:wrap; gap:4px 14px; font-size:12px; color:var(--ink2); margin-bottom:16px; }}
.legend i {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:-1px; }}
section {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 16px 8px; margin-bottom:14px; overflow-x:auto; }}
h2 {{ font-size:15px; margin:0 0 4px; }} h2 span {{ font-weight:400; color:var(--ink3); font-size:12px; }}
svg .grid {{ stroke:var(--line); stroke-width:1; }} svg .tick {{ fill:var(--ink3); font-size:10px; }}
svg .lab {{ fill:var(--ink2); font-size:12px; }} svg .val {{ fill:var(--ink); font-size:11.5px; font-family:ui-monospace, monospace; }}
svg .hit {{ fill:transparent; }} svg .row:hover .hit {{ fill:var(--line); opacity:.5; }}
</style>
<h1>How much of the search space each optimizer touches</h1>
<p>Log scale. Grey: the whole space of the query, counted exactly (tools/search_space_size.py). Then what PostgreSQL's dynamic programming
actually did (fair mode): every path it considered, split into the ones cut at the <b>precheck</b> (a cheap lower-bound cost test, before
the path is even built) and the ones built, which are then rejected on arrival, evicted later, or retained. Orange: the RelNodes Calcite
registered in its memo, per search mode. Units differ (plans, join steps, paths, RelNodes), so read each row against the scale, not as a
fraction of the row above. Hover a bar for the exact number.</p>
<div class="legend">{legend}</div>
{''.join(panels)}
"""
    open(J("viz", "funnel.html"), "w", encoding="utf-8").write(html)
    print(f"wrote viz/funnel.html ({len(panels)} queries, log scale up to 10^{int(math.log10(xmax))})")


if __name__ == "__main__":
    main()
