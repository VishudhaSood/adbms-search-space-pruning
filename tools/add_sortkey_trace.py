#!/usr/bin/env python3
"""T-b (prof's point 7): add the first sort key's column to PostgreSQL's TRACE lines (sortkey=alias.column).

Edits (backups go to /tmp/sortkey_backup/ first; running it twice changes nothing):
  pg_lab/pg-source/src/backend/optimizer/util/pathnode.c  trace_root + trace_sortkey(); sortkey=%s in trace_path
  pg_lab/pg-source/src/backend/optimizer/path/allpaths.c  trace_root = root when the stopwatch starts
  tools/pg_log_to_trace.py                                store "sortkey" per event / survivor
Run from the repo root: python3 tools/add_sortkey_trace.py
"""
import os, shutil, sys

SRC = "pg_lab/pg-source/src/backend/optimizer"
PATHNODE, ALLPATHS, PARSER = f"{SRC}/util/pathnode.c", f"{SRC}/path/allpaths.c", "tools/pg_log_to_trace.py"

HELPER = r'''/* ADBMS trace: first sort key of a path as "alias.column" (prof's point 7) */
#include "parser/parsetree.h"
extern PlannerInfo *trace_root;
PlannerInfo *trace_root = NULL;

static const char *
trace_sortkey(Path *p)
{
	PathKey    *pk;
	ListCell   *lc;

	if (p->pathkeys == NIL || trace_root == NULL || p->parent == NULL)
		return "-";
	pk = (PathKey *) linitial(p->pathkeys);
	foreach(lc, pk->pk_eclass->ec_members)
	{
		EquivalenceMember *em = (EquivalenceMember *) lfirst(lc);
		Expr	   *e = em->em_expr;
		Var		   *v;
		RangeTblEntry *rte;

		while (e && IsA(e, RelabelType))
			e = ((RelabelType *) e)->arg;
		if (e == NULL || !IsA(e, Var) || em->em_is_const ||
			!bms_is_subset(em->em_relids, p->parent->relids))
			continue;
		v = (Var *) e;
		if (v->varlevelsup != 0 || v->varattno <= 0 ||
			v->varno < 1 || (int) v->varno >= trace_root->simple_rel_array_size)
			continue;
		rte = trace_root->simple_rte_array[v->varno];
		if (rte == NULL || rte->eref == NULL)
			continue;
		return psprintf("%s.%s", rte->eref->aliasname,
						get_rte_attribute_name(rte, v->varattno));
	}
	return "-";
}

'''

EDITS = {
    PATHNODE: [
        ("/* One log line per path event: kept / rejected / evict / survivor */",
         HELPER + "/* One log line per path event: kept / rejected / evict / survivor */"),
        ('keys=%d disabled=%d t=%.1f",\n\t\t what, trace_kind_name',
         'keys=%d sortkey=%s disabled=%d t=%.1f",\n\t\t what, trace_kind_name'),
        ("list_length(p->pathkeys), p->disabled_nodes,",
         "list_length(p->pathkeys), trace_sortkey(p), p->disabled_nodes,"),
    ],
    ALLPATHS: [
        ("static void\nset_base_rel_pathlists(PlannerInfo *root)\n{",
         "extern PlannerInfo *trace_root;\n\nstatic void\nset_base_rel_pathlists(PlannerInfo *root)\n{"),
        ("\tINSTR_TIME_SET_CURRENT(trace_clock_start);\n",
         "\tINSTR_TIME_SET_CURRENT(trace_clock_start);\n\ttrace_root = root;\n"),
    ],
    PARSER: [
        ('            "disabled": int(fd.get("disabled", 0)),\n',
         '            "disabled": int(fd.get("disabled", 0)),\n'
         '            "sortkey": fd.get("sortkey") if fd.get("sortkey", "-") != "-" else None,\n'),
    ],
}
MARK = {PATHNODE: "trace_sortkey", ALLPATHS: "trace_root = root;", PARSER: '"sortkey": fd.get'}

os.makedirs("/tmp/sortkey_backup", exist_ok=True)
for path, edits in EDITS.items():
    s = open(path).read()
    if MARK[path] in s:
        print(f"already done: {path}")
        continue
    for old, new in edits:
        if s.count(old) != 1:
            sys.exit(f"STOP: expected 1 match in {path}, found {s.count(old)}: {old[:60]!r} (nothing in this file changed)")
        s = s.replace(old, new)
    shutil.copy(path, "/tmp/sortkey_backup/" + os.path.basename(path))
    open(path, "w").write(s)
    print(f"edited: {path}  (backup in /tmp/sortkey_backup/)")
