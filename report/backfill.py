#!/usr/bin/env python3
"""backfill.py CACHE.json OUT.json -- compressed-size history from GHCR.

Lists recent versions of each image package (GitHub Packages API, needs a
token with packages:read in GH_TOKEN), resolves each to a compressed size
and a release/dev variant, and caches results by digest so each version is
only fetched once. Untagged versions still have their digests, which is how
history from before this report existed is recovered.

Writes OUT.json: {image: [{digest, created, tags, variant, compressed}]}.
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "inspect_image", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "inspect-image.py"))
ii = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ii)

ORG = os.environ.get("GHCR_ORG", "hypertidy")
IMAGES = os.environ.get(
    "REPORT_IMAGES",
    "gdal-system gdal-r gdal-r-full gdal-r-python gdal-r-python-extras "
    "gdal-r-python-extras-rust gdal-r-mesh gdal-conda").split()
PER_IMAGE = int(os.environ.get("BACKFILL_VERSIONS", "40"))


def gh_versions(image):
    out = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json",
         "/orgs/%s/packages/container/%s/versions?per_page=%d" % (ORG, image, PER_IMAGE)],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        print("versions for %s unavailable: %s" % (image, out.stderr.strip()[:200]))
        return []
    return json.loads(out.stdout)


def variant_of(ref):
    """Read the image config history to tell release from dev."""
    out = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", ref,
         "--format", "{{json .Image}}"],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return None
    try:
        img = json.loads(out.stdout)
    except ValueError:
        return None
    if isinstance(img, dict) and "history" not in img:
        img = next((v for v in img.values() if isinstance(v, dict)
                    and "history" in v), {})
    created_by = [h.get("created_by", "") for h in img.get("history", [])]
    return ii.variant_from_history(created_by) if created_by else None


def main(cache_path, out_path):
    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    result = {}
    for image in IMAGES:
        rows = []
        for v in gh_versions(image):
            digest = v.get("name")
            if not digest or not digest.startswith("sha256:"):
                continue
            key = "%s@%s" % (image, digest)
            if key not in cache:
                ref = "ghcr.io/%s/%s@%s" % (ORG, image, digest)
                try:
                    info = ii.resolve(ref)
                except Exception as e:
                    info = {"kind": None, "compressed": None, "error": str(e)[:200]}
                if info.get("kind") in ("index", "image"):
                    info["variant"] = variant_of(ref)
                cache[key] = info
            info = cache[key]
            rows.append({
                "digest": digest,
                "created": v.get("created_at"),
                "tags": (v.get("metadata", {}).get("container", {}) or {}).get("tags", []),
                "kind": info.get("kind"),
                "children": info.get("children", []),
                "variant": info.get("variant"),
                "compressed": info.get("compressed"),
            })
        # Drop attestation manifests and image manifests that are children of
        # an index we already counted, so each push is one point.
        child_digests = {c for r in rows for c in r["children"]}
        result[image] = [
            {k: r[k] for k in ("digest", "created", "tags", "variant", "compressed")}
            for r in rows
            if r["kind"] in ("index", "image") and r["compressed"]
            and r["digest"] not in child_digests
        ]
        print("%s: %d points" % (image, len(result[image])))
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=1, sort_keys=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
