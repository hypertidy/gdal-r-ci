#!/usr/bin/env python3
"""build-site.py MEASURE_DIR DATA_DIR SITE_DIR -- assemble the Pages site.

MEASURE_DIR  per-image JSON from inspect-image.py (this run)
DATA_DIR     persistent data branch checkout: history.jsonl is appended here;
             ghcr.json (backfill.py) and canary.json are read if present
SITE_DIR     output: index.html + data/*.json

The page is one self-contained HTML file (no external scripts or fonts);
the data is embedded, and also published alongside as JSON.
"""

import datetime
import glob
import json
import os
import shutil
import sys

ORDER = ["gdal-system", "gdal-r", "gdal-r-full", "gdal-r-python",
         "gdal-r-python-extras", "gdal-r-python-extras-rust"]


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def dup_families(census_side):
    if not census_side:
        return None
    fams = census_side.get("families") or {}
    return {k: v for k, v in fams.items() if len(v) > 1}


def compact(doc, run_meta):
    rep = doc.get("report") or {}
    cen = rep.get("census") or {}
    return {
        "date": doc.get("measured_at"),
        "run_id": run_meta.get("run_id"),
        "image": doc["image"],
        "tag": doc["tag"],
        "digest": doc.get("digest"),
        "size_bytes": doc.get("size_bytes"),
        "compressed_bytes": doc.get("compressed_bytes"),
        "layer_count": doc.get("layer_count"),
        "versions": rep.get("versions"),
        "du": rep.get("du"),
        "dup_py": sorted((dup_families(cen.get("python")) or {}).keys()),
        "dup_r": sorted((dup_families(cen.get("r")) or {}).keys()),
    }


def main(measure_dir, data_dir, site_dir):
    run_meta = {
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_url": "%s/%s/actions/runs/%s" % (
            os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
            os.environ.get("GITHUB_REPOSITORY", "hypertidy/gdal-r-ci"),
            os.environ.get("GITHUB_RUN_ID", "")),
        "repo": os.environ.get("GITHUB_REPOSITORY", "hypertidy/gdal-r-ci"),
        "generated": datetime.datetime.now(datetime.timezone.utc)
                     .isoformat(timespec="seconds"),
    }

    docs = []
    for path in sorted(glob.glob(os.path.join(measure_dir, "*.json"))):
        d = load_json(path, None)
        if d and "image" in d:
            docs.append(d)
    docs.sort(key=lambda d: (ORDER.index(d["image"]) if d["image"] in ORDER
                             else 99, d["tag"] != "latest"))

    os.makedirs(data_dir, exist_ok=True)
    hist_path = os.path.join(data_dir, "history.jsonl")
    with open(hist_path, "a") as f:
        for d in docs:
            f.write(json.dumps(compact(d, run_meta), sort_keys=True) + "\n")
    history = []
    with open(hist_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    history.append(json.loads(line))
                except ValueError:
                    pass

    ghcr = load_json(os.path.join(data_dir, "ghcr.json"), {})
    canary = load_json(os.path.join(data_dir, "canary.json"), {})

    os.makedirs(os.path.join(site_dir, "data"), exist_ok=True)
    for name, obj in (("latest.json", docs), ("ghcr.json", ghcr),
                      ("canary.json", canary)):
        with open(os.path.join(site_dir, "data", name), "w") as f:
            json.dump(obj, f, indent=1)
    shutil.copy(hist_path, os.path.join(site_dir, "data", "history.jsonl"))

    payload = {"meta": run_meta, "images": docs, "ghcr": ghcr,
               "history": history, "canary": canary, "order": ORDER}
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "template.html")) as f:
        html = f.read()
    html = html.replace("/*__DATA__*/null", blob)
    with open(os.path.join(site_dir, "index.html"), "w") as f:
        f.write(html)
    print("site: %d images, %d history rows, %d ghcr series" % (
        len(docs), len(history), len(ghcr)))


if __name__ == "__main__":
    main(*sys.argv[1:4])
