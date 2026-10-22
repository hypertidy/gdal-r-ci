#!/usr/bin/env python3
"""canary.py OUT.json -- latest completed scheduled-canary run, per cell.

Uses the repository Actions API through `gh` (GH_TOKEN, GITHUB_REPOSITORY).
"""

import json
import os
import subprocess
import sys

REPO = os.environ.get("GITHUB_REPOSITORY", "hypertidy/gdal-r-ci")


def gh(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True,
                         timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return json.loads(out.stdout)


def main(out_path):
    doc = {"run": None, "cells": []}
    try:
        runs = gh("repos/%s/actions/workflows/scheduled-canary.yml/runs"
                  "?status=completed&per_page=1" % REPO)["workflow_runs"]
        if runs:
            r = runs[0]
            doc["run"] = {"id": r["id"], "created": r["created_at"],
                          "conclusion": r["conclusion"], "url": r["html_url"],
                          "event": r["event"]}
            jobs = gh("repos/%s/actions/runs/%d/jobs?per_page=100" % (REPO, r["id"]))
            for j in jobs.get("jobs", []):
                if j["name"] in ("setup", "Summary"):
                    continue
                doc["cells"].append({"name": j["name"],
                                     "conclusion": j["conclusion"],
                                     "url": j["html_url"]})
    except Exception as e:
        doc["error"] = str(e)
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=1)
    print("canary: %s, %d cells" % ((doc["run"] or {}).get("conclusion"), len(doc["cells"])))


if __name__ == "__main__":
    main(sys.argv[1])
