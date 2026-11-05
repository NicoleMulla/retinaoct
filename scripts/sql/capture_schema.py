#!/usr/bin/env python3
"""Rewrite scripts/sql/schema.sql from the live D1 schema.

    curl -s https://retinaoct.com/api/_schema | python3 scripts/sql/capture_schema.py

Needs no credentials: the endpoint reads sqlite_master inside the Worker.
Run after applying any migration so the repo never falls behind D1 again.
"""
import datetime, json, pathlib, sys

d = json.load(sys.stdin)
if "schema" not in d:
    sys.exit("endpoint returned no schema: %s" % d.get("error", d))

here = pathlib.Path(__file__).resolve().parent
head = (here / "schema.sql").read_text().split("-- tables")[0] if (here / "schema.sql").exists() else ""
import re
head = re.sub(r"Captured \d{4}-\d\d-\d\d", "Captured " + datetime.date.today().isoformat(), head)

parts = [head.rstrip() + "\n\n"]
for kind in ("table", "index"):
    parts.append("-- %ss\n" % kind)
    for r in d["schema"]:
        if r["type"] == kind and r["sql"]:
            sql = r["sql"].strip()
            parts.append(sql if sql.endswith(";") else sql + ";")
    parts.append("")
(here / "schema.sql").write_text("\n".join(parts) + "\n")
print("schema.sql updated: %d tables, %d indexes" % (
    sum(1 for r in d["schema"] if r["type"] == "table"),
    sum(1 for r in d["schema"] if r["type"] == "index")))
