#!/usr/bin/env python3
"""inspect-image.py IMAGE:TAG OUT.json -- runner-side measurement of one image.

Pulls the image, records registry (compressed) and local (uncompressed)
sizes plus per-layer history, then runs report/image-report.py inside it.
Also importable for its manifest helpers (used by backfill.py).
"""

import datetime
import json
import re
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}


def sh(cmd, timeout=3600, check=True):
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and out.returncode != 0:
        raise RuntimeError("%s failed: %s" % (" ".join(cmd), out.stderr[-2000:]))
    return out.stdout


def raw_manifest(ref):
    return json.loads(sh(["docker", "buildx", "imagetools", "inspect", "--raw", ref],
                         timeout=120))


def is_attestation(manifest):
    layers = manifest.get("layers", [])
    return bool(layers) and all(
        "in-toto" in (l.get("mediaType") or "") for l in layers)


def resolve(ref):
    """Return dict(kind, compressed, children) for a ref (tag or @digest).

    kind: 'index' | 'image' | 'attestation'. For an index, the linux/amd64
    image manifest is followed and its size reported; children lists the
    digests the index points at (used to de-duplicate GHCR versions).
    """
    m = raw_manifest(ref)
    # repository part of the ref, without tag or digest
    base = ref.split("@")[0] if "@" in ref else ref.rsplit(":", 1)[0]
    if m.get("mediaType") in INDEX_TYPES or "manifests" in m:
        children = [c["digest"] for c in m.get("manifests", [])]
        pick = None
        for c in m.get("manifests", []):
            p = c.get("platform") or {}
            if p.get("os") == "linux" and p.get("architecture") == "amd64":
                pick = c["digest"]
                break
        if pick is None:
            return {"kind": "index", "compressed": None, "children": children}
        im = raw_manifest("%s@%s" % (base, pick))
        return {"kind": "index", "compressed": manifest_size(im),
                "children": children, "image_digest": pick}
    if is_attestation(m):
        return {"kind": "attestation", "compressed": None, "children": []}
    return {"kind": "image", "compressed": manifest_size(m), "children": []}


def manifest_size(m):
    total = sum(int(l.get("size", 0)) for l in m.get("layers", []))
    total += int((m.get("config") or {}).get("size", 0))
    return total


def variant_from_history(history_created_by):
    """Tell :dev from :latest by build args recorded in the image history.

    Docker chain: GDAL_VERSION=master appears in a RUN line of every dev
    image (inherited from gdal-system). gdal-conda: the ENV=dev build arg.
    """
    for c in history_created_by:
        c = c or ""
        if "GDAL_VERSION=master" in c or re.search(r"(^|\s)ENV=dev(\s|$)", c):
            return "dev"
    return "latest"


def main(ref, out_path):
    started = datetime.datetime.now(datetime.timezone.utc)
    sh(["docker", "pull", "-q", ref])
    inspect = json.loads(sh(["docker", "image", "inspect", ref]))[0]
    hist_lines = sh(["docker", "history", "--human=false", "--no-trunc",
                     "--format", "{{json .}}", ref]).splitlines()
    layers = []
    for line in hist_lines:
        h = json.loads(line)
        size = int(h.get("Size") or 0)
        layers.append({"size": size,
                       "created_by": (h.get("CreatedBy") or "")[:400],
                       "created": h.get("CreatedAt")})
    try:
        man = resolve(ref)
    except Exception as e:  # registry quirks must not sink the report
        man = {"kind": None, "compressed": None, "error": str(e)[:300]}

    probe = subprocess.run(
        # The image's own Python on PATH: /opt/gdal-py in the Docker chain,
        # the environment's python in the conda images.
        ["docker", "run", "--rm", "-v", "%s:/report:ro" % HERE,
         "--entrypoint", "", ref, "sh", "-c",
         'exec "$(command -v python3 || command -v python)" /report/image-report.py'],
        capture_output=True, text=True, timeout=3600)
    try:
        report = json.loads(probe.stdout)
    except ValueError:
        report = {"error": (probe.stderr or "")[-2000:]}

    name, tag = ref.rsplit(":", 1)
    doc = {
        "image": name.rsplit("/", 1)[-1],
        "tag": tag,
        "ref": ref,
        "digest": (inspect.get("RepoDigests") or [None])[0],
        "created": inspect.get("Created"),
        "measured_at": started.isoformat(timespec="seconds"),
        "size_bytes": int(inspect.get("Size") or 0),
        "compressed_bytes": man.get("compressed"),
        "layer_count": len([l for l in layers if l["size"] > 0]),
        "layers": layers,
        "report": report,
    }
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=1)
    print("%s: %.2f GB uncompressed, %s compressed, %d non-empty layers" % (
        ref, doc["size_bytes"] / 1e9,
        "%.2f GB" % (doc["compressed_bytes"] / 1e9) if doc["compressed_bytes"] else "?",
        doc["layer_count"]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
