#!/usr/bin/env python3
"""Build viz/search_space_all.html: the search-space viewer with Q1-Q14 and a few JOB queries.

Reuses viz/build_viewer.py unchanged. Q1-Q14 come in exactly as build_viewer.py reads them (traces/,
stats/exec_times.json, stats/forced/run_forced.json, untraced PG planning times). The JOB queries are added
from traces/job/ (unzipping .json.gz), job/<q>.sql and stats/forced/job/run_forced.json. Everything is staged
in a temporary folder laid out the way build_viewer.py expects, then its main() runs on that folder.
JOB queries show no untraced PostgreSQL planning time.

  python3 tools/build_viewer_all.py                     # Q1-Q14 + 3a,4a,10a,15c
  JOB=3a,4a,8a python3 tools/build_viewer_all.py
  OUT=viz/search_space.html python3 tools/build_viewer_all.py   # replace the main viewer
"""
import gzip, importlib.util, json, os, shutil, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QS = [q.strip() for q in os.environ.get("JOB", "3a,4a,10a,15c").split(",") if q.strip()]
JOB_DIR = os.path.join(ROOT, os.environ.get("JOB_DIR", "job"))
JOB_TRACES = os.path.join(ROOT, "traces", "job")
OUT = os.path.join(ROOT, os.environ.get("OUT", os.path.join("viz", "search_space_all.html")))
MODES = ("_nosort_nocross_exchange", "_nosort_topdown_nocross_exchange")


def copy_json(src_base, dst):
    """Copy <src_base>.json, or unzip <src_base>.json.gz, to dst. False if neither exists."""
    if os.path.exists(src_base + ".json"):
        shutil.copy(src_base + ".json", dst)
        return True
    if os.path.exists(src_base + ".json.gz"):
        with gzip.open(src_base + ".json.gz", "rb") as f, open(dst, "wb") as g:
            shutil.copyfileobj(f, g)
        return True
    return False


spec = importlib.util.spec_from_file_location("build_viewer", os.path.join(ROOT, "viz", "build_viewer.py"))
bv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bv)
pg_ms = bv.pg_untraced_ms()  # Q1-Q14, read from the real repo before the module is re-pointed

with tempfile.TemporaryDirectory() as tmp:
    for d in ("traces", os.path.join("stats", "forced"), "tools"):
        os.makedirs(os.path.join(tmp, d))

    # Q1-Q14, as build_viewer.py would read them
    for name in os.listdir(bv.TRACES):
        p = os.path.join(bv.TRACES, name)
        if os.path.isfile(p):
            os.symlink(p, os.path.join(tmp, "traces", name))
    lines = [l.strip() for l in open(os.path.join(ROOT, "tools", "queries.txt")) if "|" in l]
    p = os.path.join(bv.STATS, "exec_times.json")
    if os.path.exists(p):
        os.symlink(p, os.path.join(tmp, "stats", "exec_times.json"))
    p = os.path.join(bv.STATS, "forced", "run_forced.json")
    forced = json.load(open(p)) if os.path.exists(p) else []

    # JOB queries
    known = {l.split("|", 1)[0] for l in lines}
    for q in QS:
        if q in known:
            sys.exit(f"{q} is already in tools/queries.txt")
        sql_path = os.path.join(JOB_DIR, f"{q}.sql")
        if not os.path.exists(sql_path):
            sys.exit(f"missing {sql_path}")
        lines.append(f"{q}|" + " ".join(open(sql_path).read().split()).rstrip(";"))
        if not copy_json(os.path.join(JOB_TRACES, f"pg_{q}"), os.path.join(tmp, "traces", f"pg_{q}.json")):
            print(f"note: no PostgreSQL trace for {q}")
        for m in MODES:
            if not copy_json(os.path.join(JOB_TRACES, f"calcite_{q}{m}"), os.path.join(tmp, "traces", f"calcite_{q}{m}.json")):
                print(f"note: no Calcite trace calcite_{q}{m}")
    p = os.path.join(ROOT, "stats", "forced", "job", "run_forced.json")
    if os.path.exists(p):
        forced += [r for r in json.load(open(p)) if r.get("query") in QS]

    with open(os.path.join(tmp, "tools", "queries.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(tmp, "stats", "forced", "run_forced.json"), "w") as f:
        json.dump(forced, f)
    bv.ROOT, bv.TRACES, bv.STATS, bv.OUT = tmp, os.path.join(tmp, "traces"), os.path.join(tmp, "stats"), OUT
    bv.pg_untraced_ms = lambda: pg_ms
    bv.main()
