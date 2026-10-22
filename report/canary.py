#!/usr/bin/env python3
"""canary.py OUT.json -- latest completed scheduled-canary runs, per cell.

Uses the repository Actions API through `gh` (GH_TOKEN, GITHUB_REPOSITORY).
Records the latest full run (schedule/dispatch) and the latest conda-only
run (triggered by a gdal-conda build) separately, since they cover
different cells. For failed cells the run's artifacts are downloaded and the
failure reason plus the tail of the failing check output are kept, so a
diagnosis is readable without opening job logs.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.environ.get("GITHUB_REPOSITORY", "hypertidy/gdal-r-ci")
TAIL = 40


def gh(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True,
                         timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return json.loads(out.stdout)


def tail(path, n=TAIL):
    try:
        with open(path, errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    return "\n".join(lines[-n:])


def diagnose(run_id, cell_name, workdir):
    """Download this cell's Rcheck artifact and pull out the useful bits."""
    # job name: "pkg (source) / image:variant"
    try:
        pkg, rest = cell_name.split(" (", 1)
        source, rest = rest.split(") / ", 1)
        image, variant = rest.rsplit(":", 1)
    except ValueError:
        return None
    out = {}
    status_dir = os.path.join(workdir, "status")
    status_file = os.path.join(status_dir, "%s__%s__%s__%s.txt" % (pkg, source, variant, image))
    if not os.path.exists(status_file):  # pre-image-axis naming
        status_file = os.path.join(status_dir, "%s__%s__%s.txt" % (pkg, source, variant))
    if os.path.exists(status_file):
        with open(status_file) as f:
            out["reason"] = f.read().strip().split("|", 1)[-1]
    art = "%s-%s-%s-%s-%s" % (pkg, source, variant, image, run_id)
    d = os.path.join(workdir, art)
    subprocess.run(["gh", "run", "download", str(run_id), "-R", REPO, "-n", art,
                    "-D", d], capture_output=True, text=True, timeout=300)
    if not os.path.isdir(d):
        return out or None
    snippets = {}
    for pattern in ("*00check.log", "*00install.out", "*.Rout.fail", "*-Ex.Rout"):
        for path in sorted(glob.glob(os.path.join(d, "**", pattern), recursive=True)):
            if pattern == "*-Ex.Rout" and "Execution halted" not in (tail(path, 5) or ""):
                continue
            if pattern == "*00install.out" and "ERROR" not in (tail(path, 400) or ""):
                continue
            snippets[os.path.relpath(path, d)] = tail(path)
    if snippets:
        out["snippets"] = snippets
    return out


def summarize(run, with_diagnosis=True):
    doc = {"id": run["id"], "created": run["created_at"],
           "conclusion": run["conclusion"], "url": run["html_url"],
           "event": run["event"], "cells": []}
    jobs = gh("repos/%s/actions/runs/%d/jobs?per_page=100" % (REPO, run["id"]))
    failed = []
    for j in jobs.get("jobs", []):
        if j["name"] in ("setup", "Summary"):
            continue
        cell = {"name": j["name"], "conclusion": j["conclusion"], "url": j["html_url"]}
        doc["cells"].append(cell)
        if j["conclusion"] == "failure":
            failed.append(cell)
    if with_diagnosis and failed:
        work = tempfile.mkdtemp()
        try:
            subprocess.run(["gh", "run", "download", str(run["id"]), "-R", REPO,
                            "-p", "status-*", "-D", os.path.join(work, "status")],
                           capture_output=True, text=True, timeout=300)
            # merge per-artifact subdirectories into one status dir
            sd = os.path.join(work, "status")
            for sub in glob.glob(os.path.join(sd, "*", "*.txt")):
                shutil.move(sub, os.path.join(sd, os.path.basename(sub)))
            for cell in failed:
                try:
                    cell["diagnosis"] = diagnose(run["id"], cell["name"], work)
                except Exception as e:
                    cell["diagnosis"] = {"error": str(e)[:200]}
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return doc


def main(out_path):
    doc = {"run": None, "cells": [], "conda_run": None}
    try:
        runs = gh("repos/%s/actions/workflows/scheduled-canary.yml/runs"
                  "?status=completed&per_page=20" % REPO)["workflow_runs"]
        full = next((r for r in runs if r["event"] != "workflow_run"), None)
        conda = next((r for r in runs if r["event"] == "workflow_run"), None)
        if full:
            s = summarize(full)
            doc["run"] = {k: s[k] for k in ("id", "created", "conclusion", "url", "event")}
            doc["cells"] = s["cells"]
        if conda:
            doc["conda_run"] = summarize(conda)
    except Exception as e:
        doc["error"] = str(e)
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=1)
    print("canary: full=%s (%d cells), conda=%s" % (
        (doc["run"] or {}).get("conclusion"), len(doc["cells"]),
        (doc["conda_run"] or {}).get("conclusion")))


if __name__ == "__main__":
    main(sys.argv[1])
