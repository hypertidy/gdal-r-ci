#!/usr/bin/env python3
"""gdal-tags.py [--write] [IMAGE ...] -- GDAL version tags on GHCR.

Every published image carries a moving :latest (and :dev). This adds tags
named for the GDAL release inside each build:

  gdal-X.Y.Z   newest build of IMAGE that contains GDAL X.Y.Z
  gdal-X.Y     newest build of IMAGE that contains any GDAL X.Y.x

Tags are derived from the whole registry, not from one build: every run lists
all versions of each package (untagged ones included, back to the first
push), reads the GDAL version each one was built with, and points each tag
at the newest match. A run is idempotent and repairs anything an earlier run
missed, so the backfill and the ongoing process are the same command.

"Final" needs no extra machinery. Once GDAL X.(Y+1) ships, release builds stop
containing X.Y, so gdal-X.Y stops moving: it is the final X.Y build. The plan
table marks those tags "final".

Where the GDAL version comes from (read from the image, never guessed):
  Docker chain  the GDAL_VERSION build arg in the image history (inherited by
                every image built on gdal-system); master (dev) is skipped.
  gdal-conda    release environment only: libgdal-core in conda/pixi.lock at
                the image's org.opencontainers.image.revision (the release
                environment installs that lock exactly). Needs the git history.

Without --write it only prints the plan. With --write it re-points tags by
copying the manifest bytes under the new tag (same digest, verified), using
GH_TOKEN (packages: write). It only ever writes tags matching gdal-X.Y[.Z].

Package versions are listed with `gh api` (needs packages: read); registry
reads use an anonymous pull token unless GH_TOKEN is set.
"""

import argparse
import concurrent.futures as cf
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ORG = os.environ.get("GHCR_ORG", "hypertidy")
REGISTRY = "ghcr.io"
IMAGES = [
    "gdal-system", "gdal-r", "gdal-r-full", "gdal-r-python",
    "gdal-r-python-extras", "gdal-r-python-extras-rust", "gdal-r-esmf",
    "gdal-r-mesh", "gdal-conda",
]
RELEASE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
MANAGED_TAG = re.compile(r"gdal-\d+\.\d+(\.\d+)?")
INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
ACCEPT = ", ".join(sorted(INDEX_TYPES | {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}))


class Registry:
    """Minimal OCI distribution client for one ghcr.io repository."""

    def __init__(self, image, push=False):
        self.repo = "%s/%s" % (ORG, image)
        self.push = push
        self.token = None

    def _auth(self):
        scope = "repository:%s:%s" % (self.repo, "pull,push" if self.push else "pull")
        req = urllib.request.Request(
            "https://%s/token?service=%s&scope=%s" % (REGISTRY, REGISTRY, scope))
        secret = os.environ.get("GH_TOKEN")
        if secret:
            user = os.environ.get("GITHUB_ACTOR", "token")
            req.add_header("Authorization", "Basic " + base64.b64encode(
                ("%s:%s" % (user, secret)).encode()).decode())
        elif self.push:
            raise SystemExit("--write needs GH_TOKEN with packages: write")
        with urllib.request.urlopen(req, timeout=60) as r:
            self.token = json.load(r)["token"]

    def request(self, method, path, data=None, headers=None):
        """Return (status, headers, body), re-authenticating once on 401."""
        for attempt in (0, 1):
            if self.token is None:
                self._auth()
            h = {"Authorization": "Bearer " + self.token}
            h.update(headers or {})
            req = urllib.request.Request(
                "https://%s/v2/%s/%s" % (REGISTRY, self.repo, path),
                data=data, headers=h, method=method)
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.status, r.headers, r.read()
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self.token = None
                    continue
                raise

    def manifest(self, ref):
        """Return (raw bytes, content type, parsed) for a digest or tag."""
        _, h, body = self.request("GET", "manifests/" + ref, headers={"Accept": ACCEPT})
        return body, h.get("Content-Type"), json.loads(body)

    def blob(self, digest):
        return json.loads(self.request("GET", "blobs/" + digest)[2])

    def tag(self, digest, tag):
        """Point tag at digest by re-putting the identical manifest bytes."""
        if not MANAGED_TAG.fullmatch(tag):
            raise ValueError("refusing to write unmanaged tag %r" % tag)
        body, ctype, _ = self.manifest(digest)
        self.request("PUT", "manifests/" + tag, data=body,
                     headers={"Content-Type": ctype})
        _, h, _ = self.request("HEAD", "manifests/" + tag, headers={"Accept": ACCEPT})
        got = h.get("Docker-Content-Digest")
        if got != digest:
            raise RuntimeError("%s:%s is %s after tagging, expected %s"
                               % (self.repo, tag, got, digest))


def list_versions(image):
    """All package versions: [{digest, created, tags}], via the GitHub API."""
    out = subprocess.run(
        ["gh", "api", "--paginate",
         "/orgs/%s/packages/container/%s/versions?per_page=100" % (ORG, image),
         "--jq", ".[] | {digest: .name, created: .created_at, "
                 "tags: (.metadata.container.tags // [])}"],
        capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError("listing %s failed: %s" % (image, out.stderr.strip()[:300]))
    return [json.loads(l) for l in out.stdout.splitlines() if l.strip()]


_conda_cache = {}


def conda_gdal(rev):
    """libgdal-core version of the release environment in pixi.lock at rev."""
    if rev not in _conda_cache:
        out = subprocess.run(["git", "show", "%s:conda/pixi.lock" % rev],
                             capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError("pixi.lock at %s unavailable (shallow clone?): %s"
                               % (rev[:12], out.stderr.strip()[:200]))
        env = re.search(r"^  release:\n(.*?)(?=^  \S|^\S)", out.stdout, re.S | re.M)
        # platform keys sit at 6 spaces; package lines there start with "- "
        linux = env and re.search(r"^      linux-64:\n(.*?)(?=^      [\w-]+:\s*$|\Z)",
                                  env.group(1), re.S | re.M)
        m = linux and re.search(r"/libgdal-core-(\d+\.\d+\.\d+)-", linux.group(1))
        _conda_cache[rev] = m.group(1) if m else None
    return _conda_cache[rev]


def gdal_version(image, cfg):
    """GDAL release X.Y.Z a build contains, or None (dev or unknown)."""
    if image == "gdal-conda":
        conf = cfg.get("config") or {}
        if "PIXI_ENVIRONMENT_NAME=release" not in (conf.get("Env") or []):
            return None
        rev = (conf.get("Labels") or {}).get("org.opencontainers.image.revision")
        return conda_gdal(rev) if rev else None
    hist = " ".join(h.get("created_by") or "" for h in cfg.get("history", []))
    found = set(re.findall(r"GDAL_VERSION=(\S+)", hist))
    if len(found) != 1:
        return None
    v = found.pop()
    return v if RELEASE.fullmatch(v) else None


def is_attestation(m):
    layers = m.get("layers", [])
    return bool(layers) and all("in-toto" in (l.get("mediaType") or "") for l in layers)


def builds(image, versions):
    """Top-level pushes of image: [{digest, created, tags, gdal}].

    GHCR lists an index, its platform manifest and its attestation manifest
    as three versions; only the index (what :latest pointed at) is a build.
    """
    reg = Registry(image)

    def fetch(v):
        _, _, m = reg.manifest(v["digest"])
        return v["digest"], m

    with cf.ThreadPoolExecutor(8) as ex:
        manifests = dict(ex.map(fetch, versions))
    children = {c["digest"] for m in manifests.values()
                for c in m.get("manifests", [])}

    def describe(v):
        m = manifests[v["digest"]]
        if m.get("mediaType") in INDEX_TYPES or "manifests" in m:
            plat = [c for c in m.get("manifests", [])
                    if (c.get("platform") or {}).get("os") != "unknown"]
            if not plat:
                return None
            m = reg.manifest(plat[0]["digest"])[2]
        elif is_attestation(m):
            return None
        cfg = reg.blob(m["config"]["digest"])
        return dict(v, created=v.get("created") or cfg.get("created"),
                    gdal=gdal_version(image, cfg))

    tops = [v for v in versions if v["digest"] not in children]
    with cf.ThreadPoolExecutor(8) as ex:
        return [b for b in ex.map(describe, tops) if b]


def plan(image, versions):
    """[(tag, digest, created, gdal, current_digest, final)] for one image."""
    bs = [b for b in builds(image, versions) if b["gdal"]]
    want = {}
    for b in sorted(bs, key=lambda b: (b["created"], b["digest"])):
        x, y, _ = RELEASE.fullmatch(b["gdal"]).groups()
        for t in ("gdal-%s" % b["gdal"], "gdal-%s.%s" % (x, y)):
            want[t] = b                      # later builds overwrite earlier
    have = {t: v["digest"] for v in versions for t in v["tags"]}
    newest = max((b["created"], b["gdal"]) for b in bs)[1] if bs else None
    rows = []
    for t, b in sorted(want.items(), key=lambda kv: vkey(kv[0])):
        # final: this image has a newer build on a different GDAL release
        final = t not in ("gdal-%s" % newest, "gdal-%s" % minor(newest))
        rows.append((t, b["digest"], b["created"], b["gdal"], have.get(t), final))
    return rows


def minor(v):
    return ".".join(v.split(".")[:2]) if v else None


def vkey(tag):
    return tuple(int(p) for p in tag[len("gdal-"):].split("."))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("images", nargs="*", help="default: all")
    ap.add_argument("--write", action="store_true", help="apply (default: plan only)")
    args = ap.parse_args()
    images = args.images or IMAGES
    bad = sorted(set(images) - set(IMAGES))
    if bad:
        raise SystemExit("unknown image(s): %s" % " ".join(bad))

    lines = ["| image | tag | digest | built | status | action |",
             "|---|---|---|---|---|---|"]
    failed = []
    for image in images:
        try:
            rows = plan(image, list_versions(image))
            reg = Registry(image, push=True) if args.write else None
            for t, digest, created, gdal, cur, final in rows:
                action = "ok" if cur == digest else ("move" if cur else "create")
                if action != "ok" and reg:
                    reg.tag(digest, t)
                    action += "d"
                lines.append("| %s | `%s` | `%s` | %s | %s | %s |" % (
                    image, t, digest[7:19], (created or "")[:10],
                    "final" if final else "current", action))
            print("%s: %d tags" % (image, len(rows)), file=sys.stderr)
        except Exception as e:
            failed.append(image)
            print("%s: FAILED %s" % (image, e), file=sys.stderr)
            lines.append("| %s | | | | | **failed**: %s |" % (image, str(e)[:120]))

    mode = "applied" if args.write else "plan only (pass --write to apply)"
    report = "## GDAL version tags: %s\n\n%s\n" % (mode, "\n".join(lines))
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(report)
    if failed:
        raise SystemExit("failed: %s" % " ".join(failed))


if __name__ == "__main__":
    main()
