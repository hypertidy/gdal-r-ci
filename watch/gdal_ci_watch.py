#!/usr/bin/env python3
"""gdal_ci_watch.py -- read-only watcher for OSGeo/gdal master CI.

For each GDAL workflow whose latest master run is red, find the failing
jobs and walk back to the last green run of each. Then build a context
bundle: error signature and sites, package versions that changed between
the last green and first red job logs, where GDAL's CI installs those
packages, commits in between, open GDAL PRs/issues that may already cover
it, and recent CI commits on the same files.

One issue per failure signature is kept in this repository (label
gdal-ci-watch): created, updated in place, closed when the jobs are green.

Nothing is written to OSGeo/gdal. Text posted here puts every GDAL
issue/PR/user reference in a code span, and check_quiet() refuses to post
anything that would link to or mention something on the GDAL side.

  GDAL_READ_TOKEN  token for reading OSGeo/gdal (default: GH_TOKEN)
  GH_TOKEN         token for issues in GITHUB_REPOSITORY

See docs/gdal-ci-watch.md.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

GDAL = "OSGeo/gdal"
GDAL_URL = "https://github.com/" + GDAL
REPO = os.environ.get("GITHUB_REPOSITORY", "hypertidy/gdal-r-ci")
LABEL = "gdal-ci-watch"

# Workflows that don't build or test GDAL.
SKIP_WORKFLOW_FILES = {
    "auto_tag_stable.yml", "backport.yml", "labeler.yml", "stale.yml",
    "delete_untagged_containers.yml", "scorecard.yml", "release.yml",
    "docker-workshop.yml", "coverity_scan.yml",
}
MASTER_EVENTS = {"push", "schedule", "workflow_dispatch"}
RED = {"failure", "timed_out", "startup_failure"}
GREEN = {"success"}

CI_PATH_RE = re.compile(
    r"^(?:\.github/|ci/|cmake/|.*CMakeLists\.txt$|.*\.cmake$|"
    r"autotest/requirements|doc/requirements|\.pre-commit-config|"
    r"swig/python/(?:pyproject|setup|requirements))")
INSTALL_STEP_RE = re.compile(
    r"(?i)^(?:install|set ?up|update build environment|.*dependenc|.*requirements)")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- quiet text

FENCE_BLOCK_RE = re.compile(r"(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$")
INLINE_CODE_RE = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)", re.S)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
LOUD = [
    ("GDAL issue reference", re.compile(r"(?i)\bosgeo/gdal#\d+")),
    ("GDAL issue/PR URL", re.compile(
        r"(?i)github\.com/osgeo/gdal/(?:pull|issues|discussions)/\d+")),
    ("@mention", re.compile(r"(?<![\w.`/+-])@[A-Za-z0-9][A-Za-z0-9-]{0,38}\b")),
    ("#number reference", re.compile(r"(?<![\w&/#])#\d+\b")),
    ("GH- reference", re.compile(r"(?i)\bGH-\d+\b")),
]


class LoudText(ValueError):
    pass


def strip_code(md):
    md = HTML_COMMENT_RE.sub("", md)
    md = FENCE_BLOCK_RE.sub("", md)
    return INLINE_CODE_RE.sub("", md)


def check_quiet(md):
    """Raise LoudText if md would mention a user or cross-reference an issue."""
    bare = strip_code(md)
    for what, pat in LOUD:
        m = pat.search(bare)
        if m:
            raise LoudText("%s outside a code span: %r" % (what, m.group(0)))
    return md


def code(s):
    """Inline code span that survives any backticks in s."""
    s = str(s).replace("\r", " ").replace("\n", " ")
    if not s:
        return ""
    n = 1
    while "`" * n in s:
        n += 1
    pad = " " if s.startswith("`") or s.endswith("`") else ""
    return "`" * n + pad + s + pad + "`" * n


def cell(s):
    return code(s).replace("|", "\\|")


def fenced(text):
    n = 4
    while "~" * n in text:
        n += 1
    return "%s\n%s\n%s" % ("~" * n, text, "~" * n)


def plain_title(s):
    s = re.sub(r"[`#@]", "", s)
    s = re.sub(r"(?i)osgeo/gdal", "gdal", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:117] + "..." if len(s) > 120 else s


# ------------------------------------------------------------------- GitHub

class GH:
    def __init__(self, read_token, write_token, dry_run, cache_dir=None):
        self.read_token = read_token
        self.write_token = write_token
        self.dry_run = dry_run
        self.cache_dir = cache_dir
        self.calls = 0
        self.log_failures = 0
        self.escape_flag = False  # newer gh refuses raw logs without it
        self._jobs = {}
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def _run(self, args, token, stdin=None):
        env = dict(os.environ)
        if token:
            env["GH_TOKEN"] = token
        self.calls += 1
        p = subprocess.run(["gh"] + args, input=stdin, capture_output=True,
                           text=True, errors="replace", env=env, timeout=600)
        if p.returncode != 0:
            raise RuntimeError("gh %s: %s" % (" ".join(args[:4]),
                                              p.stderr.strip()[:400]))
        return p.stdout

    def get(self, endpoint, token=None, **params):
        args = ["api", "-X", "GET", endpoint]
        for k, v in params.items():
            args += ["-f", "%s=%s" % (k, v)]
        out = self._run(args, token or self.read_token)
        return json.loads(out) if out.strip() else None

    def own(self, endpoint, **params):
        return self.get(endpoint, token=self.write_token, **params)

    def _cache(self, name, value=None):
        if not self.cache_dir:
            return None
        path = os.path.join(self.cache_dir, name)
        if value is None:
            if os.path.exists(path):
                with open(path, errors="replace") as f:
                    return f.read()
            return None
        with open(path, "w") as f:
            f.write(value)
        return value

    def jobs(self, run):
        rid = run["id"]
        if rid in self._jobs:
            return self._jobs[rid]
        cached = self._cache("jobs-%d.json" % rid)
        if cached is not None:
            jobs = json.loads(cached)
        else:
            jobs, page = [], 1
            while True:
                d = self.get("repos/%s/actions/runs/%d/jobs" % (GDAL, rid),
                             filter="latest", per_page=100, page=page)
                jobs += d["jobs"]
                if not d["jobs"] or len(jobs) >= d["total_count"]:
                    break
                page += 1
            if run.get("status") == "completed":
                self._cache("jobs-%d.json" % rid, json.dumps(jobs))
        self._jobs[rid] = jobs
        return jobs

    def log(self, job_id):
        cached = self._cache("log-%d.txt" % job_id)
        if cached is not None:
            return cached
        args = ["api", "repos/%s/actions/jobs/%d/logs" % (GDAL, job_id)]
        if self.escape_flag:
            args.append("--allow-escape-sequences")
        try:
            text = self._run(args, self.read_token)
        except RuntimeError as e:
            if not self.escape_flag and "--allow-escape-sequences" in str(e):
                self.escape_flag = True
                return self.log(job_id)
            log("log %d unavailable: %s" % (job_id, e))
            self.log_failures += 1
            return None
        return self._cache("log-%d.txt" % job_id, text) or text

    def write(self, method, path, payload):
        if REPO.lower() == GDAL.lower() or not path.startswith("repos/%s/" % REPO):
            raise RuntimeError("refusing to write outside %s: %s" % (REPO, path))
        for k in ("title", "body"):
            if k in payload:
                check_quiet(payload[k])
        if self.dry_run:
            log("[dry-run] %s %s" % (method, path))
            return {"number": 0, "html_url": ""}
        out = self._run(["api", "-X", method, path, "--input", "-"],
                        self.write_token, stdin=json.dumps(payload))
        return json.loads(out) if out.strip() else None


# ------------------------------------------------------------- log analysis

TS_RE = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ?")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# BuildKit step prefix ("#12 3.4 ") and ctest -V test number ("41: ")
PREFIX_RE = re.compile(r"^(?:#\d+ \d+(?:\.\d+)?(?: |$)|\d{1,4}:(?: |$))")
WORKSPACE_RE = re.compile(
    r"(?:[A-Za-z]:)?(?:/[^\s/:()'\"]+)*?/gdal/gdal/|"
    r"(?:[A-Za-z]:)?/(?:__w|home/runner/work|Users/runner/work|a)/[^/\s]+/[^/\s]+/")


BK_ERR_RE = re.compile(r"^#(\d+) ERROR: ")
BK_PREFIX_RE = re.compile(r"^#\d+ (?:\d+(?:\.\d+)?(?: |$))?")


def clean(text, keep_prefix=False):
    lines = [ANSI_RE.sub("", TS_RE.sub("", l)).rstrip() for l in text.splitlines()]
    return lines if keep_prefix else [PREFIX_RE.sub("", l) for l in lines]


def buildkit_step(lines):
    """Output of the first BuildKit step that failed, or None. Takes lines
    from clean(keep_prefix=True): parallel steps interleave, so only the
    '#N ' prefix tells them apart."""
    n = next((m.group(1) for m in map(BK_ERR_RE.match, lines) if m), None)
    if n is None:
        return None
    tag = "#%s " % n
    return [BK_PREFIX_RE.sub("", l) for l in lines if l.startswith(tag)]


def strip_paths(s):
    return WORKSPACE_RE.sub("", s.replace("\\", "/"))


def failing_section(lines):
    """Output of the step that failed: after the echoed command of the last
    '##[group]Run' before the first '##[error]', up to that error."""
    err = next((i for i, l in enumerate(lines) if l.startswith("##[error]")), None)
    if err is None:
        return lines[-300:]
    start = max([i for i in range(err) if lines[i].startswith("##[group]Run ")]
                or [max(0, err - 2000)])
    end_echo = next((i for i in range(start, err)
                     if lines[i].startswith("##[endgroup]")), start)
    return lines[end_echo + 1:err + 1]


# (category, pattern), most specific first
SIG_PATTERNS = [
    ("cmake", re.compile(r"^CMake Error\b")),
    ("compile", re.compile(
        r"(?:^|\s)\S+?(?::\d+:(?:\d+:)?|\(\d+(?:,\d+)?\)\s*:) (?:fatal )?error\b")),
    ("resolve", re.compile(
        r"Unable to locate package|has no installation candidate|^E: |"
        r"LibMambaUnsatisfiableError|PackagesNotFoundError|ResolvePackageNotFound|"
        r"No matching distribution found|Could not find a version that satisfies|"
        r"nothing provides |ResolutionImpossible|^ERROR: (?:Could not|Cannot|No matching)")),
    ("annotation", re.compile(r"^##\[error\](?!Process completed with exit code)\S")),
    ("python", re.compile(r"^(?:ModuleNotFoundError|ImportError|SyntaxError): ")),
    ("pytest", re.compile(r"^(?:FAILED|ERROR) \S+::")),
    ("ctest", re.compile(
        r"^\s*\d+ - \S+ \((?:Failed|Timeout|SEGFAULT|Subprocess aborted|Exception|Not Run)\)")),
    ("pytest-E", re.compile(r"^E\s{2,}\S")),
    ("fetch", re.compile(r"^curl: \(\d+\) ")),
    # not inside names such as libgpg-error-dev or strerror_r
    ("generic", re.compile(r"(?i)\bfatal error\b|(?<![\w-])error(?![\w-])")),
]
# Failures a re-run may clear: (label, phrase to look for on GDAL or None, pattern)
TRANSIENT = [
    ("rate limit", "rate limit",
     re.compile(r"(?i)API rate limit exceeded|secondary rate limit")),
    ("DNS", "resolve host",
     re.compile(r"(?i)Could not resolve host|Temporary failure in name resolution")),
    ("network", None, re.compile(r"(?i)Connection (?:timed out|reset by peer)")),
    ("server", None, re.compile(r"\b50[234] (?:Bad Gateway|Service Unavailable|Gateway Time-?out)")),
    ("runner lost", None,
     re.compile(r"runner has received a shutdown signal|lost communication with the server")),
]
IGNORE_SIG_RE = re.compile(
    r"^##\[(?!error\])|Process completed with exit code|-W(?:no-)?error|WERROR|"
    r"error(?:s)? occurred!$|^\s*$")


def signature(section):
    """(line, category, index) of the most specific error line, or Nones."""
    for cat, pat in SIG_PATTERNS:
        for i, l in enumerate(section):
            if pat.search(l) and not IGNORE_SIG_RE.search(l):
                return re.sub(r"^##\[error\]", "", l).strip(), cat, i
    return None, None, None


def transient(lines):
    """(label, phrase or None, line) for the first transient-failure marker, or None."""
    for l in lines:
        for label, phrase, pat in TRANSIENT:
            if pat.search(l):
                return label, phrase, strip_paths(l).strip()[:160]
    return None


def normalise(line):
    s = strip_paths(line)
    s = re.sub(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b", "H", s)
    s = re.sub(r"\d+", "N", s)
    return re.sub(r"\s+", " ", s).strip()[:200]


def fingerprint(norm):
    return hashlib.sha1(norm.encode()).hexdigest()[:12]


SITE_PATTERNS = [
    re.compile(r"^CMake Error(?: \([^)]*\))? at (?P<f>\S+?):(?P<l>\d+)"),
    re.compile(r"^(?P<f>[^\s:]+?):(?P<l>\d+):(?:\d+:)? (?:fatal )?error\b"),
    re.compile(r"^(?P<f>[^\s(]+?)\((?P<l>\d+)(?:,\d+)?\)\s*: (?:fatal )?error\b"),
    re.compile(r"^(?:FAILED|ERROR) (?P<f>\S+?::\S+)"),
    re.compile(r"^\s*\d+ - (?P<f>\S+) \((?:Failed|Timeout|SEGFAULT|Subprocess aborted|Exception)\)"),
]


def error_sites(section):
    sites = Counter()
    for l in section:
        for p in SITE_PATTERNS:
            m = p.search(l)
            if m:
                key = strip_paths(m.group("f"))
                if m.groupdict().get("l"):
                    key += ":" + m.group("l")
                sites[key] += 1
                break
    return sites


def excerpt(section, idx, before=3, after=25, tail=15):
    keep = set(range(max(0, len(section) - tail), len(section)))
    if idx is not None:
        keep.update(range(max(0, idx - before), min(len(section), idx + after)))
    out, last = [], None
    for i in sorted(keep):
        if last is not None and i != last + 1:
            out.append("...")
        out.append(strip_paths(section[i])[:300])
        last = i
    return "\n".join(out)


# --------------------------------------------------------- resolved packages

ENV_PATTERNS = [
    ("conda", re.compile(
        r"^\s+(?P<n>[A-Za-z0-9_.+-]+)\s+[\w.-]+/[\w-]+::(?P=n)-(?P<v>\d[^\s-]*)-\S+\s*$")),
    ("conda", re.compile(
        r"^\s+(?P<n>[A-Za-z0-9_.+-]+?)-(?P<v>\d[^\s|-]*)\s+\|\s+\S+\s+[\d.]+ [KMG]?B\b")),
    ("conda", re.compile(
        r"^\s*\+\s+(?P<n>[A-Za-z0-9_.+-]+)\s+(?P<v>\d\S*)\s+\S+\s+(?:conda-forge|[\w.-]+/[\w-]+)\b")),
    ("apt", re.compile(r"^Setting up (?P<n>[A-Za-z0-9.+-]+)(?::\w+)? \((?P<v>[^)]+)\) \.\.\.")),
    ("apk", re.compile(
        r"^\(\s*\d+/\d+\) (?:Installing|Upgrading) (?P<n>\S+) \((?:[^)]*? -> )?(?P<v>[^)\s]+)\)")),
    ("brew", re.compile(
        r"^==> Pouring (?P<n>[A-Za-z0-9_.+@-]+?)--(?P<v>\d[\w.+-]*?)\.(?:arm64_|x86_64_|all\.)")),
    ("pip", re.compile(r"^\s*\+ (?P<n>[A-Za-z0-9_.-]+)==(?P<v>\S+)$")),
    ("tool", re.compile(r"^(?P<n>cmake|ctest|ninja|swig|SWIG) [Vv]ersion (?P<v>\d\S*)")),
]
PIP_OK_RE = re.compile(r"^Successfully installed (?P<pkgs>.+)$")
PYTEST_RE = re.compile(r"^platform \S+ -- Python (?P<py>[^,\s]+), pytest-(?P<pt>[^,\s]+)")
PLUGINS_RE = re.compile(r"^plugins: (?P<p>.+)$")
IMAGE_RE = re.compile(r"^Image: (?P<n>\S+)$")
VERSION_RE = re.compile(r"^Version: (?P<v>\S+)$")


def norm_name(n):
    return re.sub(r"[_.]+", "-", n.lower())


def env_versions(lines):
    """{(manager, name): version}; the last occurrence wins."""
    env = {}
    image = None
    for l in lines:
        if image is not None:
            m = VERSION_RE.match(l)
            if m:
                env[("runner", image)] = m.group("v")
            image = None
        m = IMAGE_RE.match(l)
        if m:
            image = m.group("n")
            continue
        m = PIP_OK_RE.match(l)
        if m:
            for tok in m.group("pkgs").split():
                if "-" in tok:
                    n, v = tok.rsplit("-", 1)
                    env[("pip", norm_name(n))] = v
            continue
        m = PYTEST_RE.match(l)
        if m:
            env[("pip", "pytest")] = m.group("pt")
            env[("tool", "python")] = m.group("py")
            continue
        m = PLUGINS_RE.match(l)
        if m:
            for tok in m.group("p").split(", "):
                if "-" in tok:
                    n, v = tok.rsplit("-", 1)
                    env[("pytest-plugin", norm_name(n))] = v
            continue
        for mgr, pat in ENV_PATTERNS:
            m = pat.match(l)
            if m:
                env[(mgr, norm_name(m.group("n")))] = m.group("v")
                break
    return env


def env_diff(green, red):
    """[(manager, name, green_version_or_None, red_version)] for changes."""
    out = []
    for (mgr, name), v in red.items():
        g = green.get((mgr, name))
        if g != v:
            out.append((mgr, name, g, v))
    return out


# ------------------------------------------------- where GDAL CI installs it

INSTALL_CMD_RE = re.compile(
    r"\b(?:apt-get|apt|conda|mamba|micromamba|pip3?|uv|brew|apk|dnf|yum|"
    r"choco|vcpkg|pixi|port)\b[^#\n]*?\b(?:install|add|upgrade|create)\b")
REQ_FILE_RE = re.compile(
    r"(?:^|/)(?:[\w.-]*requirements[\w.-]*\.txt|environment[\w.-]*\.ya?ml)$")
TOKEN_RE = re.compile(
    r"^['\"]?(?P<n>[A-Za-z][A-Za-z0-9_.+-]*?)(?:\[[^\]]*\])?"
    r"(?P<spec>(?:==|>=|<=|!=|~=|=|<|>|@)[^\s'\"]*)?['\"]?,?$")
CMD_SPLIT_RE = re.compile(r"&&|;|\|\|?")


class CIIndex:
    """Package names on install lines in a (sparse) checkout of GDAL's CI files."""

    def __init__(self, root):
        self.root = root
        self.sha = "master"
        self.hits = defaultdict(list)
        self.present = bool(root) and os.path.isdir(os.path.join(root, ".github"))
        if not self.present:
            return
        try:
            self.sha = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                                      capture_output=True, text=True,
                                      check=True).stdout.strip()
        except (subprocess.CalledProcessError, OSError):
            pass
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                try:
                    with open(path, encoding="utf-8") as f:
                        lines = f.read().splitlines()
                except (UnicodeDecodeError, OSError):
                    continue
                self._index(rel, lines)

    def _index(self, rel, lines):
        is_req = bool(REQ_FILE_RE.search(rel))
        cont = False
        for i, line in enumerate(lines):
            code_part = re.sub(r"(?:^|\s)#.*$", "", line)
            if is_req:
                text = code_part.strip()
                if text.startswith("- "):
                    text = text[2:]
                if not text or text.endswith(":"):
                    continue
                toks = [text.replace(" ", "")]
            else:
                m = INSTALL_CMD_RE.search(code_part)
                if not m and not cont:
                    continue
                text = code_part[m.end():] if m else code_part
                parts = CMD_SPLIT_RE.split(text)
                cont = code_part.rstrip().endswith("\\") and len(parts) == 1
                toks = parts[0].split()
            for tok in toks:
                if tok.startswith(("-", "$", "/", ".")):
                    continue
                m = TOKEN_RE.match(tok)
                if m:
                    self.hits[norm_name(m.group("n"))].append(
                        (rel, i + 1, bool(m.group("spec")), line.strip()))

    def has(self, rel):
        return os.path.exists(os.path.join(self.root, rel))

    def find(self, name, workflow_file=None):
        """Hits for a package, the failing workflow's own file first and
        legacy ci/travis scripts last."""
        def rank(h):
            return (h[0] != workflow_file, not h[0].startswith(".github/"),
                    h[0].startswith("ci/travis/"), h[2], h[0], h[1])
        return sorted(self.hits.get(norm_name(name), []), key=rank)

    def blob(self, rel, line):
        return "%s/blob/%s/%s#L%d" % (GDAL_URL, self.sha, rel, line)


# ------------------------------------------------------------------ scanning

def point(run, job):
    return {"run_id": run["id"], "job_id": job["id"], "sha": run["head_sha"],
            "created": run["created_at"], "url": job["html_url"],
            "event": run["event"]}


def failed_step(job):
    return next((s["name"] for s in job.get("steps") or []
                 if s.get("conclusion") in RED), "")


def walk(gh, wf, runs, latest, job):
    """History of one job on master, newest first, back to its last green."""
    rec = {"workflow": wf["name"], "workflow_file": wf["path"],
           "wf_id": wf["id"], "job": job["name"], "step": failed_step(job),
           "latest": point(latest, job), "red_runs": 0, "red_shas": [],
           "first_red": None, "last_green": None}
    for r in runs:
        if r["created_at"] > latest["created_at"]:
            continue
        if r["conclusion"] not in RED | GREEN:
            continue
        j = next((x for x in gh.jobs(r) if x["name"] == job["name"]), None)
        if j is None or j["conclusion"] not in RED | GREEN:
            continue
        if j["conclusion"] in RED:
            rec["red_runs"] += 1
            rec["red_shas"].append(r["head_sha"])
            rec["first_red"] = point(r, j)
        else:
            rec["last_green"] = point(r, j)
            break
    return rec


def scan(gh, history, ci, stale_days):
    wfs = gh.get("repos/%s/actions/workflows" % GDAL, per_page=100)["workflows"]
    wfs = [w for w in wfs if w["state"] == "active"
           and not w["path"].startswith("dynamic/")
           and os.path.basename(w["path"]) not in SKIP_WORKFLOW_FILES]
    if ci.present:
        gone = [w["name"] for w in wfs if not ci.has(w["path"])]
        if gone:
            log("not on master any more: %s" % ", ".join(gone))
        wfs = [w for w in wfs if ci.has(w["path"])]
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=stale_days)
              ).strftime("%Y-%m-%dT%H:%M:%SZ")
    red, latest_by_wf = [], {}
    for wf in wfs:
        runs = gh.get("repos/%s/actions/workflows/%d/runs" % (GDAL, wf["id"]),
                      branch="master", status="completed",
                      per_page=history)["workflow_runs"]
        runs = [r for r in runs if r["event"] in MASTER_EVENTS]
        latest = next((r for r in runs if r["conclusion"] in RED | GREEN), None)
        latest_by_wf[wf["name"]] = (wf, runs, latest)
        if not latest or latest["conclusion"] not in RED:
            continue
        if latest["created_at"] < cutoff:
            log("%s: latest master run is from %s, skipping as stale"
                % (wf["name"], latest["created_at"][:10]))
            continue
        reds = [j for j in gh.jobs(latest) if j["conclusion"] in RED]
        if not reds:
            log("%s: run %d is %s with no red job" % (wf["name"], latest["id"],
                                                     latest["conclusion"]))
            continue
        for j in reds:
            red.append(walk(gh, wf, runs, latest, j))
        log("%s: %d red job(s)" % (wf["name"], len(reds)))
    return red, latest_by_wf


def pr_signal(gh, red, hours, cap):
    """Distinct PR authors whose runs of the same job were red recently."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
             ).strftime("%Y-%m-%dT%H:%M:%SZ")
    by_wf = defaultdict(list)
    for rec in red:
        by_wf[rec["wf_id"]].append(rec)
    for wf_id, recs in by_wf.items():
        names = {r["job"] for r in recs}
        authors = defaultdict(set)
        runs = gh.get("repos/%s/actions/workflows/%d/runs" % (GDAL, wf_id),
                      event="pull_request", status="failure",
                      created=">=" + since, per_page=100)["workflow_runs"]
        for r in runs[:cap]:
            for j in gh.jobs(r):
                if j["name"] in names and j["conclusion"] in RED:
                    authors[j["name"]].add((r.get("actor") or {}).get("login", "?"))
        for rec in recs:
            rec["pr_authors"] = sorted(authors.get(rec["job"], ()))


def analyse_log(gh, rec, key="latest"):
    text = gh.log(rec[key]["job_id"])
    if text is None:
        return None
    raw = clean(text, keep_prefix=True)
    step_out = failing_section([PREFIX_RE.sub("", l) for l in raw])
    section = buildkit_step(raw) or step_out
    sig, cat, idx = signature(section)
    return {"signature": sig, "category": cat, "transient": transient(step_out),
            "sites": error_sites(section), "excerpt": excerpt(section, idx)}


def group(gh, red, max_logs):
    groups = {}
    for n, rec in enumerate(red):
        a = analyse_log(gh, rec) if n < max_logs else None
        rec["analysis"] = a
        sig = a and a["signature"]
        norm = normalise(sig) if sig else "%s / %s / %s" % (
            rec["workflow"], rec["job"], rec["step"] or "?")
        fp = fingerprint(norm)
        g = groups.setdefault(fp, {"fp": fp, "norm": norm, "signature": sig,
                                   "category": a and a["category"], "jobs": []})
        g["jobs"].append(rec)
    return list(groups.values())


# ------------------------------------------------------------------- context

WORD_RE = re.compile(r"[a-z0-9][a-z0-9.+_-]*")


def words(text):
    return {t.rstrip(".-_") for t in WORD_RE.findall(text.lower())}


def term_label(term):
    kind, val = term
    if kind == "words":
        return " ".join(val)
    if kind == "phrase":
        return '"%s"' % val
    return "CI/CMake/build PR opened since %s" % val


def term_matches(term, item):
    kind, val = term
    title = item.get("title") or ""
    text = "%s\n%s" % (title, item.get("body") or "")
    if kind == "words":
        ws = words(text)
        return all(any(t == w or t.startswith(w + ".") for t in ws) for w in val)
    if kind == "phrase":
        return val.lower() in text.lower()
    if kind == "ci-pr-since":
        return ("pull_request" in item and item["created_at"][:10] >= val
                and bool(re.match(r"(?i)(?:ci|cmake|build)\b", title)))
    return False


def open_on_gdal(gh, terms, since, pages=3):
    """Open GDAL issues and PRs updated since `since` that match any term.

    Listed through the REST issues endpoint and matched here, which avoids
    the search API's rate limit. A workflow token needs `pull-requests: read`
    or PRs are left out of the listing."""
    items, notes = [], []
    for page in range(1, pages + 1):
        try:
            d = gh.get("repos/%s/issues" % GDAL, state="open", sort="updated",
                       direction="desc", since=since, per_page=100, page=page)
        except RuntimeError as e:
            notes.append("listing open GDAL issues failed: %s" % str(e)[:120])
            break
        items += d
        if len(d) < 100:
            break
    found = []
    for it in items:
        hit = [term_label(t) for t in terms if term_matches(t, it)]
        if hit:
            found.append({"number": it["number"], "title": it["title"],
                          "user": (it.get("user") or {}).get("login", "?"),
                          "created": it["created_at"][:10],
                          "kind": "PR" if "pull_request" in it else "issue",
                          "url": it["html_url"], "query": ", ".join(hit)})
    return sorted(found, key=lambda x: -x["number"]), notes, len(items)


def precedent(gh, files, packages):
    seen, out = set(), []
    for f in files[:3]:
        try:
            commits = gh.get("repos/%s/commits" % GDAL, path=f, per_page=15)
        except RuntimeError:
            continue
        for c in commits:
            subj = c["commit"]["message"].splitlines()[0]
            if c["sha"] in seen or not re.match(r"(?i)ci\b", subj):
                continue
            seen.add(c["sha"])
            out.append({"sha": c["sha"], "date": c["commit"]["committer"]["date"][:10],
                        "subject": subj, "file": f})
    for p in packages[:2]:
        try:
            d = gh.get("search/commits", q="repo:%s %s" % (GDAL, p),
                       sort="committer-date", order="desc", per_page=5)
        except RuntimeError:
            continue
        for it in d.get("items", []):
            subj = it["commit"]["message"].splitlines()[0]
            if it["sha"] in seen or p.lower() not in subj.lower():
                continue
            seen.add(it["sha"])
            out.append({"sha": it["sha"], "date": it["commit"]["committer"]["date"][:10],
                        "subject": subj, "file": "mentions " + p})
    return sorted(out, key=lambda x: x["date"], reverse=True)[:8]


def distinctive_tokens(sig):
    if not sig:
        return []
    toks = re.findall(r"[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+|[A-Z][a-z]+(?:[A-Z][a-z]+){2,}", sig)
    toks = [t for t in toks if len(t) >= 8 and "/" not in t]
    return list(dict.fromkeys(toks))[:2]


def mm(v):
    m = re.match(r"(\d+)\.(\d+)", v or "")
    return "%s.%s" % m.groups() if m else (v or "")


def build_context(gh, g, ci):
    jobs = g["jobs"]
    primary = next((j for j in jobs if j["last_green"]), jobs[0])
    g["primary"] = primary
    ctx = {"env": [], "env_job": None, "compare": None, "gdal_open": [],
           "notes": [], "precedent": []}
    lg, fr = primary["last_green"], primary["first_red"]

    if lg and fr:
        green, red_text = gh.log(lg["job_id"]), gh.log(fr["job_id"])
        if green is not None and red_text is not None:
            changes = env_diff(env_versions(clean(green)), env_versions(clean(red_text)))
            merged = {}
            for mgr, name, gv, rv in changes:
                r = merged.get((name, gv, rv))
                if r:
                    r["mgr"] += ", " + mgr
                    continue
                hits = ci.find(name, primary["workflow_file"])
                merged[(name, gv, rv)] = {
                    "mgr": mgr, "name": name, "green": gv, "red": rv,
                    "hits": hits, "unpinned": [h for h in hits if not h[2]]}
            rows = list(merged.values())
            rows.sort(key=lambda r: (not r["unpinned"], not r["hits"],
                                     r["green"] is None, r["mgr"], r["name"]))
            ctx["env"] = rows
            ctx["env_job"] = primary
        else:
            ctx["notes"].append("job logs unavailable for the package diff")
        if lg["sha"] != fr["sha"]:
            try:
                d = gh.get("repos/%s/compare/%s...%s" % (GDAL, lg["sha"], fr["sha"]))
                files = [f["filename"] for f in d.get("files", [])]
                ctx["compare"] = {
                    "url": "%s/compare/%s...%s" % (GDAL_URL, lg["sha"][:12], fr["sha"][:12]),
                    "n": d.get("total_commits", len(d.get("commits", []))),
                    "subjects": [c["commit"]["message"].splitlines()[0]
                                 for c in d.get("commits", [])][-30:],
                    "ci_files": [f for f in files if CI_PATH_RE.match(f)],
                    "n_files": len(files)}
            except RuntimeError as e:
                ctx["notes"].append("compare failed: %s" % str(e)[:120])

    direct = [r for r in ctx["env"] if r["hits"]]
    terms = [("words", (r["name"], mm(r["red"]))) for r in direct[:2] if mm(r["red"])]
    terms += [("phrase", t) for t in distinctive_tokens(g["signature"])]
    tr = (primary.get("analysis") or {}).get("transient")
    if tr and tr[1]:
        terms.append(("phrase", tr[1]))
    red_since = (fr or primary["latest"])["created"]
    terms.append(("ci-pr-since", red_since[:10]))
    terms = list(dict.fromkeys(terms))
    since = (dt.datetime.strptime(red_since[:10], "%Y-%m-%d")
             - dt.timedelta(days=14)).strftime("%Y-%m-%dT00:00:00Z")
    ctx["gdal_open"], notes, ctx["gdal_checked"] = open_on_gdal(gh, terms, since)
    ctx["notes"] += notes
    ctx["queries"] = [term_label(t) for t in terms]
    ctx["gdal_since"] = since[:10]

    files = [primary["workflow_file"]]
    for r in direct[:3]:
        h = (r["unpinned"] or r["hits"])[0]
        if h[0] not in files:
            files.append(h[0])
    ctx["precedent"] = precedent(gh, files, [r["name"] for r in direct])
    return ctx


def verdict(g, ctx):
    p = g["primary"]
    lg, fr = p["last_green"], p["first_red"]
    cmp_ = ctx["compare"]
    n_env = len(ctx["env"])
    n_direct = sum(1 for r in ctx["env"] if r["hits"])
    tr = (p.get("analysis") or {}).get("transient")
    if tr:
        return ("likely transient (%s): the failing step logged %s; a re-run may pass"
                % (tr[0], code(tr[2])))
    if not lg:
        return "no green run of this job in the lookback window; nothing to compare against"
    if fr and lg["sha"] == fr["sha"]:
        return ("environment: the same commit was green on %s and red on %s"
                % (lg["created"][:10], fr["created"][:10]))
    if g["category"] == "resolve" or INSTALL_STEP_RE.search(p["step"] or ""):
        return "environment: failed while installing or resolving dependencies (step %s)" % code(p["step"] or "?")
    if cmp_ and cmp_["ci_files"]:
        return "CI/build files changed between last green and first red; check those first"
    if n_env and cmp_ is not None:
        return ("likely environment drift: no CI/build files changed between last green "
                "and first red; %d package version(s) changed, %d of them named in GDAL CI"
                % (n_env, n_direct))
    if cmp_ is None:
        return "could not compare last green and first red"
    return "only source files changed between last green and first red; possibly a code regression"


def should_alert(g, args):
    for j in g["jobs"]:
        if j["red_runs"] >= args.min_red_runs:
            return True
        if len(j.get("pr_authors", ())) >= args.min_pr_authors:
            return True
        lg, fr = j["last_green"], j["first_red"]
        if lg and fr and lg["sha"] == fr["sha"]:
            return True
    return False


# ----------------------------------------------------------------- rendering

def short(sha):
    return code(sha[:7])


def commit_link(sha):
    return "[%s](%s/commit/%s)" % (short(sha), GDAL_URL, sha)


def render(g, ctx, run_url, now):
    p = g["primary"]
    meta = {"fp": g["fp"], "jobs": sorted({(j["workflow"], j["job"]) for j in g["jobs"]}),
            "first_red": min((j["first_red"] or j["latest"])["created"] for j in g["jobs"])}
    out = ["<!-- gdal-ci-watch %s -->" % json.dumps(meta)]
    out.append("**Signature:** %s" % (code(g["signature"]) if g["signature"]
                                      else "no error line found; " + code(g["norm"])))
    out.append("")
    out.append("**Likely:** " + verdict(g, ctx))
    out.append("")
    out.append("| workflow | job | failing step | red since | master runs red | PR authors red (48 h) | last green |")
    out.append("|---|---|---|---|---|---|---|")
    for j in g["jobs"]:
        fr, lg = j["first_red"] or j["latest"], j["last_green"]
        out.append("| %s | [%s](%s) | %s | %s %s | %d | %d | %s |" % (
            cell(j["workflow"]), cell(j["job"]), j["latest"]["url"],
            cell(j["step"] or "?"), fr["created"][:10], commit_link(fr["sha"]),
            j["red_runs"], len(j.get("pr_authors", ())),
            ("[%s](%s) %s" % (lg["created"][:10], lg["url"], commit_link(lg["sha"]))
             if lg else "none in window")))
    out.append("")

    a = p.get("analysis")
    if a and a["sites"]:
        out.append("### Error sites")
        out.append("")
        for site, n in list(a["sites"].items())[:15]:
            out.append("- %s%s" % (code(site), " (x%d)" % n if n > 1 else ""))
        if len(a["sites"]) > 15:
            out.append("- ... %d more" % (len(a["sites"]) - 15))
        out.append("")

    if ctx["env_job"]:
        lg, fr = p["last_green"], p["first_red"]
        out.append("### Package versions, last green to first red")
        out.append("")
        out.append("From %s: [green log](%s), [red log](%s)." % (
            code(p["job"]), lg["url"], fr["url"]))
        out.append("")
        changed = [r for r in ctx["env"] if r["green"] is not None]
        new = [r for r in ctx["env"] if r["green"] is None]

        def row(r):
            where = ", ".join("[%s %s](%s)" % ("pinned" if h[2] else "unpinned",
                                               code("%s:%d" % (os.path.basename(h[0]), h[1])),
                                               ci_blob(h))
                              for h in (r["unpinned"] or r["hits"])[:3])
            return "| %s | %s | %s | %s | %s |" % (
                r["mgr"], cell(r["name"]), cell(r["green"] or "-"), cell(r["red"]), where)

        head = ["| manager | package | last green | first red | in GDAL CI |",
                "|---|---|---|---|---|"]
        top = [r for r in changed if r["hits"]] + [r for r in changed if not r["hits"]][:15]
        if top:
            out += head + [row(r) for r in top]
            rest = len(changed) - len(top)
            if rest > 0:
                out.append("")
                out.append("%d more changed package(s) not named in GDAL CI are omitted." % rest)
        else:
            out.append("No resolved package versions differ.")
        if new:
            out.append("")
            out.append("<details><summary>%d package(s) seen only in the red log</summary>" % len(new))
            out.append("")
            out += head + [row(r) for r in new[:40]]
            out.append("")
            out.append("</details>")
        out.append("")

    if ctx["compare"]:
        c = ctx["compare"]
        out.append("### Commits between last green and first red")
        out.append("")
        out.append("[%d commit(s), %d file(s)](%s). CI/build files touched: %s." % (
            c["n"], c["n_files"], c["url"],
            ", ".join(code(f) for f in c["ci_files"][:10]) or "none"))
        if c["subjects"]:
            out.append("")
            out.append("<details><summary>subjects</summary>")
            out.append("")
            out += ["- " + code(s) for s in c["subjects"]]
            out.append("")
            out.append("</details>")
        out.append("")

    out.append("### Open on GDAL that may already cover this")
    out.append("")
    if ctx["gdal_open"]:
        for it in ctx["gdal_open"][:8]:
            out.append("- %s %s %s by %s, opened %s, matched %s: %s" % (
                it["kind"], code(it["number"]), code(it["title"]), code(it["user"]),
                it["created"], code(it["query"]), code(it["url"])))
    else:
        out.append("Nothing open matched.")
    out.append("")
    out.append("Checked %s open GDAL issues/PRs updated since %s for: %s" % (
        ctx.get("gdal_checked", "?"), ctx.get("gdal_since", "?"),
        ", ".join(code(q) for q in ctx.get("queries", []))))
    out.append("")

    if ctx["precedent"]:
        out.append("### Precedent: recent CI commits on these files")
        out.append("")
        for c in ctx["precedent"]:
            out.append("- %s %s %s (%s)" % (commit_link(c["sha"]), c["date"],
                                            code(c["subject"]), code(c["file"])))
        out.append("")

    if a and a["excerpt"]:
        out.append("### Log excerpt (%s, latest red)" % code(p["job"]))
        out.append("")
        out.append(fenced(a["excerpt"]))
        out.append("")

    for n in ctx["notes"]:
        out.append("> " + code(n))
    out.append("<sub>gdal-ci-watch, [run](%s), updated %s. Read-only on GDAL; "
               "references to it are kept in code spans.</sub>" % (run_url, now))
    body = "\n".join(out)
    if len(body) > 60000:
        body = body[:60000] + "\n\n(truncated)"
    return body, meta


CI_SHA = {"sha": "master"}


def ci_blob(hit):
    return "%s/blob/%s/%s#L%d" % (GDAL_URL, CI_SHA["sha"], hit[0], hit[1])


def title_for(g):
    wfs = list(dict.fromkeys(j["workflow"] for j in g["jobs"]))
    head = wfs[0] + (" +%d" % (len(wfs) - 1) if len(wfs) > 1 else "")
    what = g["signature"] or "%s failing at %s" % (g["jobs"][0]["job"], g["jobs"][0]["step"])
    return plain_title("GDAL CI: %s: %s" % (head, strip_paths(what).rstrip(":. ")))


# ------------------------------------------------------------------- issues

def own_issues(gh):
    items = gh.own("repos/%s/issues" % REPO, labels=LABEL, state="all",
                   per_page=100, sort="updated")
    out = []
    for it in items or []:
        if it.get("pull_request"):
            continue
        m = re.search(r"<!-- gdal-ci-watch (\{.*?\}) -->", it.get("body") or "", re.S)
        if m:
            it["meta"] = json.loads(m.group(1))
            out.append(it)
    return out


def ensure_label(gh):
    if gh.dry_run:
        return
    try:
        gh.write("POST", "repos/%s/labels" % REPO, {
            "name": LABEL, "color": "b60205",
            "description": "OSGeo/gdal master CI breakage seen by gdal-ci-watch"})
    except RuntimeError:
        pass  # exists


def job_now(gh, latest_by_wf, wf_name, job_name):
    """Latest red/green conclusion of a job on master, or None."""
    entry = latest_by_wf.get(wf_name)
    if not entry:
        return None
    _, runs, _ = entry
    for r in runs:
        if r["conclusion"] not in RED | GREEN:
            continue
        j = next((x for x in gh.jobs(r) if x["name"] == job_name), None)
        if j and j["conclusion"] in RED | GREEN:
            return j["conclusion"], r["head_sha"]
    return None


def core(body):
    return re.sub(r"<sub>gdal-ci-watch.*?</sub>", "", body or "", flags=re.S).strip()


def sync_issues(gh, issues, alerts, latest_by_wf, red_keys):
    actions = []
    by_fp = defaultdict(list)
    for it in issues:
        by_fp[it["meta"]["fp"]].append(it)
    ensure_label(gh)
    current = {}
    for g, title, body, meta in alerts:
        existing = sorted(by_fp.get(g["fp"], []),
                          key=lambda i: (i["state"] != "open", -i["number"]))
        if existing:
            it = existing[0]
            n = it["number"]
            old_jobs = {tuple(x) for x in it["meta"].get("jobs", [])}
            new_jobs = [j for j in meta["jobs"] if tuple(j) not in old_jobs]
            patch = {}
            if core(it.get("body")) != core(body):
                patch["body"] = body
            if it["title"] != title:
                patch["title"] = title
            if it["state"] != "open":
                patch["state"] = "open"
            if patch:
                gh.write("PATCH", "repos/%s/issues/%d" % (REPO, n), patch)
            if it["state"] != "open":
                gh.write("POST", "repos/%s/issues/%d/comments" % (REPO, n),
                         {"body": "Red again on master."})
                actions.append(("reopened", n, title))
            elif new_jobs:
                gh.write("POST", "repos/%s/issues/%d/comments" % (REPO, n), {
                    "body": "Now also red: " + ", ".join(
                        code("%s / %s" % tuple(j)) for j in new_jobs)})
                actions.append(("updated+", n, title))
            else:
                actions.append(("updated" if patch else "unchanged", n, title))
            current[g["fp"]] = n
        else:
            res = gh.write("POST", "repos/%s/issues" % REPO,
                           {"title": title, "body": body, "labels": [LABEL]})
            current[g["fp"]] = res.get("number", 0)
            actions.append(("opened", res.get("number", 0), title))

    for it in issues:
        if it["state"] != "open" or it["meta"]["fp"] in current:
            continue
        jobs = [tuple(j) for j in it["meta"].get("jobs", [])]
        states = [job_now(gh, latest_by_wf, wf, job) for wf, job in jobs]
        if states and all(s and s[0] in GREEN for s in states):
            shas = ", ".join(sorted({short(s[1]) for s in states}))
            gh.write("POST", "repos/%s/issues/%d/comments" % (REPO, it["number"]),
                     {"body": "Green again on master (%s). Closing." % shas})
            gh.write("PATCH", "repos/%s/issues/%d" % (REPO, it["number"]),
                     {"state": "closed", "state_reason": "completed"})
            actions.append(("closed", it["number"], it["title"]))
        elif jobs and all(j in red_keys and red_keys[j] in current for j in jobs):
            others = sorted({red_keys[j] for j in jobs})
            gh.write("POST", "repos/%s/issues/%d/comments" % (REPO, it["number"]), {
                "body": "These jobs now fail with a different signature, see %s. Closing."
                        % ", ".join("issue %d" % current[fp] for fp in others)})
            gh.write("PATCH", "repos/%s/issues/%d" % (REPO, it["number"]),
                     {"state": "closed", "state_reason": "not_planned"})
            actions.append(("superseded", it["number"], it["title"]))
    return actions


# --------------------------------------------------------------------- main

def summary_md(red, groups, alerted, actions, gh):
    out = ["## GDAL CI watch, %s" % dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           ""]
    if not red:
        out.append("All watched GDAL workflows are green on master.")
    else:
        out.append("| workflow | job | step | master runs red | PR authors red | signature | alert |")
        out.append("|---|---|---|---|---|---|---|")
        for g in groups:
            for j in g["jobs"]:
                out.append("| %s | %s | %s | %d | %d | %s | %s |" % (
                    cell(j["workflow"]), cell(j["job"]), cell(j["step"]), j["red_runs"],
                    len(j.get("pr_authors", ())), cell((g["signature"] or g["norm"])[:90]),
                    "yes" if g["fp"] in alerted else "watching"))
    if actions:
        out.append("")
        out += ["- %s issue %s: %s" % (a, n, code(t)) for a, n, t in actions]
    out.append("")
    out.append("%d GitHub API calls." % gh.calls)
    if gh.log_failures:
        out.append("")
        out.append("**%d job log(s) could not be read**; the reason is in the run log. "
                   "If it is a permissions error, add a `GDAL_READ_TOKEN` secret "
                   "(see docs/gdal-ci-watch.md)." % gh.log_failures)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="write nothing to GitHub")
    ap.add_argument("--out", default="watch-out", help="directory for bodies and plan.json")
    ap.add_argument("--gdal-ci-dir", help="sparse checkout of GDAL's .github/ and ci/")
    ap.add_argument("--cache-dir", help="cache job logs and job lists here (local runs)")
    ap.add_argument("--history", type=int, default=30, help="master runs per workflow")
    ap.add_argument("--min-red-runs", type=int, default=2)
    ap.add_argument("--min-pr-authors", type=int, default=2)
    ap.add_argument("--pr-hours", type=int, default=48)
    ap.add_argument("--pr-runs", type=int, default=25, help="PR runs inspected per workflow")
    ap.add_argument("--max-logs", type=int, default=25)
    ap.add_argument("--stale-days", type=int, default=10,
                    help="ignore workflows with no master run this recent")
    args = ap.parse_args(argv)

    write_token = os.environ.get("GH_TOKEN")
    read_token = os.environ.get("GDAL_READ_TOKEN") or write_token
    gh = GH(read_token, write_token, args.dry_run, args.cache_dir)
    ci = CIIndex(args.gdal_ci_dir)
    CI_SHA["sha"] = ci.sha
    os.makedirs(args.out, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    run_url = "%s/%s/actions/runs/%s" % (
        os.environ.get("GITHUB_SERVER_URL", "https://github.com"), REPO,
        os.environ.get("GITHUB_RUN_ID", "0"))

    red, latest_by_wf = scan(gh, args.history, ci, args.stale_days)
    if red:
        pr_signal(gh, red, args.pr_hours, args.pr_runs)
    groups = group(gh, red, args.max_logs)
    red_keys = {(j["workflow"], j["job"]): g["fp"] for g in groups for j in g["jobs"]}
    issues = own_issues(gh)
    tracked = {it["meta"]["fp"] for it in issues if it["state"] == "open"}

    alerts, plan = [], []
    for g in groups:
        alert = should_alert(g, args) or g["fp"] in tracked
        entry = {"fp": g["fp"], "signature": g["signature"], "alert": alert,
                 "jobs": [{k: j[k] for k in ("workflow", "job", "step", "red_runs",
                                             "first_red", "last_green", "latest")}
                          | {"pr_authors": len(j.get("pr_authors", ()))}
                          for j in g["jobs"]]}
        plan.append(entry)
        if not alert:
            continue
        try:
            ctx = build_context(gh, g, ci)
        except RuntimeError as e:
            g["primary"] = g["jobs"][0]
            ctx = {"env": [], "env_job": None, "compare": None, "gdal_open": [],
                   "precedent": [], "queries": [], "notes": ["context failed: %s" % str(e)[:200]]}
        body, meta = render(g, ctx, run_url, now)
        title = title_for(g)
        check_quiet(title)
        check_quiet(body)
        entry["title"] = title
        with open(os.path.join(args.out, "issue-%s.md" % g["fp"]), "w") as f:
            f.write("# %s\n\n%s\n" % (title, body))
        alerts.append((g, title, body, meta))

    actions = sync_issues(gh, issues, alerts, latest_by_wf, red_keys)
    with open(os.path.join(args.out, "plan.json"), "w") as f:
        json.dump({"plan": plan, "actions": actions}, f, indent=1, default=str)
    md = summary_md(red, groups, {g["fp"] for g, *_ in alerts}, actions, gh)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
