#!/usr/bin/env python3
"""gdal_ci_history.py -- read-only study of OSGeo/gdal pull request CI.

Question: if a pull request ran only some of the CI jobs, and the full
matrix ran less often, which failures would the reduced set still catch?

For every push to a pull request against master in the window it collects
the jobs that failed, then sorts each failure into one of:

  inherited  the same job was red on master at the time, or every error
             in it also failed master within a few days
  retried    the job failed, was re-run on the same commit and passed
  setup      the job failed while installing its dependencies
  shared     every error in it also failed pull requests from other forks
  own        anything else: the failure the full matrix is there to catch

When in doubt a failure is "own": an error is only compared when it names
something specific (a test, a compiler error, a package), and a job with
several failed tests is only excused when all of them are.

It then reports, per job, how often it was the only job to catch an "own"
failure, what it costs in runner minutes, and the order in which jobs would
be added to a reduced set to catch the most failures for the least time.
That order is then chosen again from the earlier part of the window only and
scored on the later part, which it has not seen.

Nothing is written to OSGeo/gdal. Only the Actions API and job logs are
read. Forks and branches are kept as hashes, so no logins are stored.
See docs/gdal-ci-history.md.

  GDAL_READ_TOKEN  token for reading OSGeo/gdal (default: GH_TOKEN, then
                   the ambient gh login)
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gdal_ci_watch import (GDAL, GH, GREEN, INSTALL_STEP_RE, PREFIX_RE,  # noqa: E402
                           RED, SIG_PATTERNS, SKIP_WORKFLOW_FILES,
                           buildkit_step, cell, clean, failed_step,
                           failing_section, log, normalise, signature)

# A master result this long after a pull request run still counts as the
# state the pull request ran against: drift is seen by pull requests first.
NEXT_MASTER_HOURS = 24
LEAD_DAYS = 3  # master history fetched before the window, to know its state
SAME_ERROR_HOURS = 72  # a master failure this close with the same error
SHARED_FORKS = 3       # forks hit by one error before it is called shared
# Error categories specific enough to say two failures are the same one.
# Left out: "ctest" names only the suite, "pytest-E" and "generic" are lines
# that many unrelated failures print.
SPECIFIC = {"cmake", "compile", "resolve", "annotation", "python", "pytest",
            "fetch"}
MAX_ERRORS = 400  # failed tests kept per job
CURRENT_DAYS = 14  # a job seen this recently is part of today's matrix
BACKPORT_RE = re.compile(r"^backport-\d+-to-(.+)$")


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- collection

def get(gh, endpoint, tries=4, **params):
    """gh.get, retried when GitHub answers with a server error."""
    for n in range(tries):
        try:
            return gh.get(endpoint, **params)
        except RuntimeError as e:
            if n == tries - 1 or not any(
                    "HTTP %d" % c in str(e) for c in (500, 502, 503, 504)):
                raise
            log("retrying after: %s" % str(e)[-60:])
            time.sleep(5 * (n + 1))


def list_runs(gh, wf_id, since, **params):
    """All completed runs of one workflow created since a date."""
    runs, page = [], 1
    while True:
        d = get(gh, "repos/%s/actions/workflows/%d/runs" % (GDAL, wf_id),
                status="completed", created=">=" + since, per_page=100,
                page=page, **params)
        runs += d["workflow_runs"]
        if len(d["workflow_runs"]) < 100 or len(runs) >= d["total_count"]:
            return runs
        page += 1


def attempt_jobs(gh, run_id, attempt):
    """Jobs of one attempt of a completed run. Immutable, so cached."""
    name = "jobs-%d-a%d.json" % (run_id, attempt)
    cached = gh._cache(name)
    if cached is not None:
        return json.loads(cached)
    jobs, page = [], 1
    while True:
        d = get(gh, "repos/%s/actions/runs/%d/attempts/%d/jobs"
                % (GDAL, run_id, attempt), per_page=100, page=page)
        jobs += d["jobs"]
        if not d["jobs"] or len(jobs) >= d["total_count"]:
            break
        page += 1
    gh._cache(name, json.dumps(jobs))
    return jobs


def error_lines(section):
    """(category, normalised error lines) of a failed step's output.

    Every failed test when pytest names them, otherwise the one most
    specific line."""
    sig, cat, _ = signature(section)
    if cat == "pytest":
        pat = dict(SIG_PATTERNS)["pytest"]
        lines = sorted({normalise(l) for l in section if pat.search(l)})
        return cat, lines[:MAX_ERRORS]
    return cat, [normalise(sig)] if sig else []


def job_errors(gh, logs, job_id):
    """{"cat", "errors"} of a failed job. Cached; the log itself is not."""
    name = "err-%d.json" % job_id
    cached = gh._cache(name)
    if cached is not None:
        return json.loads(cached)
    text = logs.log(job_id)
    if text is None:  # not cached: the log may only be briefly unavailable
        return {"cat": None, "errors": []}
    raw = clean(text, keep_prefix=True)
    section = buildkit_step(raw) or failing_section(
        [PREFIX_RE.sub("", l) for l in raw])
    cat, lines = error_lines(section)
    out = {"cat": cat, "errors": lines}
    gh._cache(name, json.dumps(out))
    return out


def add_signatures(gh, logs, data):
    """Read the error of every failed job that timing alone does not explain."""
    todo = {}
    for r in data["master_runs"]:
        for j in (r.get("jobs") or [[]])[-1]:
            if j["conclusion"] in RED:
                todo[j["id"]] = j
    ids = {f["id"] for f in classify(data) if f["kind"] != "inherited"}
    for r in for_master(data["pr_runs"]):
        for a in r.get("jobs") or []:
            for j in a:
                if j["id"] in ids:
                    todo[j["id"]] = j
    log("%d failed job logs to read" % len(todo))
    for n, (jid, j) in enumerate(sorted(todo.items()), 1):
        j.update(job_errors(gh, logs, jid))
        if n % 50 == 0:
            log("  %d logs read" % n)


def slim_job(j):
    mins = None
    if j.get("started_at") and j.get("completed_at"):
        mins = (ts(j["completed_at"]) - ts(j["started_at"])).total_seconds() / 60
    return {"id": j["id"], "name": j["name"], "conclusion": j["conclusion"],
            "started": j.get("started_at"), "completed": j.get("completed_at"),
            "minutes": mins, "step": failed_step(j),
            "attempt": j.get("run_attempt", 1)}


def anon(s):
    return hashlib.sha1(s.encode()).hexdigest()[:10]


def slim_run(r, wf):
    repo = (r.get("head_repository") or {}).get("full_name") or "?"
    # The base branch is only listed while a pull request from the repository
    # itself is open. Backports are named after their target, so read that.
    base = next((p["base"]["ref"] for p in r.get("pull_requests") or []
                 if p.get("base")), None)
    m = BACKPORT_RE.match(r.get("head_branch") or "")
    if base is None and m and repo.lower() == GDAL.lower():
        base = m.group(1)
    return {"id": r["id"], "workflow": wf["name"],
            "workflow_file": os.path.basename(wf["path"]),
            "event": r["event"], "sha": r["head_sha"], "base": base,
            "fork": anon(repo),
            # stands in for the pull request: one branch of one fork
            "branch": anon("%s:%s" % (repo, r.get("head_branch") or "?")),
            "conclusion": r["conclusion"], "attempts": r.get("run_attempt", 1),
            "started": r.get("run_started_at") or r["created_at"],
            "updated": r["updated_at"], "created": r["created_at"]}


def collect(gh, days, sample):
    """Runs and jobs needed by analyse(), as plain data."""
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=days)
    wfs = get(gh, "repos/%s/actions/workflows" % GDAL, per_page=100)["workflows"]
    wfs = [w for w in wfs if w["state"] == "active"
           and not w["path"].startswith("dynamic/")
           and os.path.basename(w["path"]) not in SKIP_WORKFLOW_FILES]
    data = {"since": iso(since), "until": iso(now), "pr_runs": [],
            "master_runs": []}
    for wf in wfs:
        prs = list_runs(gh, wf["id"], iso(since)[:10], event="pull_request")
        if not prs:
            continue
        log("%s: %d pull request runs" % (wf["name"], len(prs)))
        greens = [r for r in prs if r["conclusion"] in GREEN
                  and r.get("run_attempt", 1) == 1]
        step = max(1, len(greens) // sample) if sample else 0
        sampled = {r["id"] for r in greens[::step][:sample]} if step else set()
        for r in prs:
            run = slim_run(r, wf)
            n = run["attempts"]
            if r["conclusion"] in RED or n > 1 or r["id"] in sampled:
                # every attempt: an earlier one shows what a re-run fixed
                run["jobs"] = [[slim_job(j) for j in attempt_jobs(gh, r["id"], a)]
                               for a in range(1, n + 1)]
            data["pr_runs"].append(run)
        lead = iso(since - dt.timedelta(days=LEAD_DAYS))[:10]
        for r in list_runs(gh, wf["id"], lead, branch="master", event="push"):
            run = slim_run(r, wf)
            if r["conclusion"] in RED:
                run["jobs"] = [[slim_job(j) for j in
                                attempt_jobs(gh, r["id"], run["attempts"])]]
            data["master_runs"].append(run)
    return data


# ------------------------------------------------------------------ analysis

def job_key(run, job):
    return "%s / %s" % (run["workflow"], job["name"])


def master_timeline(master_runs):
    """Per workflow, the master results in time order.

    Each entry is (completed time, set of red job keys, set of job keys with
    no result). A green run has both sets empty: every job passed.
    """
    tl = defaultdict(list)
    for r in master_runs:
        if r["conclusion"] not in RED | GREEN:
            continue
        red, unknown = set(), set()
        for j in (r.get("jobs") or [[]])[-1]:
            if j["conclusion"] in RED:
                red.add(job_key(r, j))
            elif j["conclusion"] not in GREEN:
                unknown.add(job_key(r, j))
        tl[r["workflow"]].append((ts(r["updated"]), red, unknown))
    for v in tl.values():
        v.sort(key=lambda e: e[0])
    return tl


def master_state(tl, workflow, key, when):
    """'before', 'next' or '' : how master's result for a job was red."""
    entries = [e for e in tl.get(workflow, ()) if key not in e[2]]
    before = [e for e in entries if e[0] <= when]
    if before and key in before[-1][1]:
        return "before"
    after = [e for e in entries if e[0] > when]
    if (after and key in after[0][1]
            and after[0][0] - when <= dt.timedelta(hours=NEXT_MASTER_HOURS)):
        return "next"
    return ""


def for_master(pr_runs):
    """Runs of pull requests against master. Unknown base means a fork,
    and backports to release branches are opened from the repository."""
    return [r for r in pr_runs if r.get("base") in (None, "master")]


def specific(job):
    """Error lines of a job that are fit to compare, or ()."""
    return job.get("errors") or () if job.get("cat") in SPECIFIC else ()


def master_errors(master_runs):
    """(workflow, error) -> times it failed a master run."""
    seen = defaultdict(list)
    for r in master_runs:
        for j in (r.get("jobs") or [[]])[-1]:
            if j["conclusion"] in RED:
                for e in specific(j):
                    seen[(r["workflow"], e)].append(ts(r["updated"]))
    return seen


def classify(data):
    """One record per failed job per pull request run, with its class."""
    tl = master_timeline(data["master_runs"])
    errors = master_errors(data["master_runs"])
    near = dt.timedelta(hours=SAME_ERROR_HOURS)
    out = []
    for r in for_master(data["pr_runs"]):
        attempts = r.get("jobs") or []
        if not attempts:
            continue
        final = {j["name"]: j for j in attempts[-1]}
        seen = set()
        for a in attempts:
            for j in a:
                if j["conclusion"] not in RED or j["name"] in seen:
                    continue
                seen.add(j["name"])
                key = job_key(r, j)
                when = ts(j["started"] or r["started"])
                m = master_state(tl, r["workflow"], key, when)
                last = final.get(j["name"], j)
                errs = list(specific(j))
                if not m and errs and all(
                        any(abs(t - when) <= near
                            for t in errors.get((r["workflow"], e), ()))
                        for e in errs):
                    m = "error"
                if m:
                    kind = "inherited"
                elif last["conclusion"] in GREEN:
                    kind = "retried"
                elif INSTALL_STEP_RE.search(j["step"] or ""):
                    kind = "setup"
                else:
                    kind = "own"
                out.append({"id": j["id"], "run": r["id"], "sha": r["sha"],
                            "branch": r["branch"], "fork": r["fork"],
                            "workflow": r["workflow"], "job": key,
                            "step": j["step"], "kind": kind, "master": m,
                            "errors": errs, "when": iso(when)})
    forks = defaultdict(set)
    for f in out:
        for e in f["errors"]:
            forks[e].add(f["fork"])
    for f in out:
        f["forks"] = min((len(forks[e]) for e in f["errors"]), default=0)
        if f["kind"] == "own" and f["forks"] >= SHARED_FORKS:
            f["kind"] = "shared"
    return out


def message(error):
    """The part of an error line shared by every test it failed: the text
    after the test name, or the test without its parameters."""
    head, sep, msg = error.partition(" - ")
    if sep and len(msg) >= 15:
        return msg
    return head.split("[", 1)[0] if "::" in head else error


def started(run):
    """False for a run that failed before any job existed. These look like
    pull requests that were never approved to run."""
    jobs = run.get("jobs")
    return not (run["conclusion"] in RED and jobs is not None and not jobs[-1])


def current_jobs(runs, until):
    """Jobs seen in the last CURRENT_DAYS of the window, and the names that
    older jobs now go by.

    A job that moved to another workflow keeps its own name, so an old job
    whose name matches exactly one current job is that job."""
    recent = iso(until - dt.timedelta(days=CURRENT_DAYS))
    current, older = set(), set()
    for r in runs:
        for a in r.get("jobs") or []:
            for j in a:
                (current if r["started"] >= recent else older).add(job_key(r, j))
    by_name = defaultdict(list)
    for k in current:
        by_name[k.split(" / ", 1)[1]].append(k)
    alias = {}
    for k in older - current:
        same = by_name.get(k.split(" / ", 1)[1], ())
        if len(same) == 1:
            alias[k] = same[0]
    return current, alias


def durations(pr_runs, alias=None):
    """Median minutes of each job when it passed, and how many samples."""
    alias = alias or {}
    mins = defaultdict(list)
    for r in pr_runs:
        for j in (r.get("jobs") or [[]])[-1]:
            if j["conclusion"] in GREEN and j["minutes"] is not None:
                k = job_key(r, j)
                mins[alias.get(k, k)].append(j["minutes"])
    return {k: (statistics.median(v), len(v)) for k, v in mins.items()}


def greedy_cover(pushes, cost, default=1.0, allowed=None):
    """Order jobs by own-failing pushes newly caught per runner minute.

    pushes maps a push to the set of jobs that failed on it. Returns the
    number of pushes and (job, newly caught, cumulative caught, cumulative
    minutes) per step. A job with no known duration is charged the default.
    With allowed, only those jobs can be chosen, and a push that failed in
    none of them is counted but never caught.
    """
    total = sum(1 for j in pushes.values() if j)
    left = {p: set(j) if allowed is None else set(j) & allowed
            for p, j in pushes.items()}
    left = {p: j for p, j in left.items() if j}
    caught, minutes, order = 0, 0.0, []
    while left:
        gain = Counter(j for jobs in left.values() for j in jobs)
        best = max(gain, key=lambda j: (
            gain[j] / max(cost.get(j, default), 1.0), gain[j], j))
        caught += gain[best]
        minutes += cost.get(best, default)
        order.append((best, gain[best], caught, minutes))
        left = {p: jobs for p, jobs in left.items() if best not in jobs}
    return total, order


def holdout(fails, cost, default, since, until, train_share, allowed=None):
    """Choose the reduced set on the early part of the window, score it on
    the rest. Returns None when either part has no own failure."""
    split = since + (until - since) * train_share
    first = {}
    for f in fails:
        t = ts(f["when"])
        first[f["sha"]] = min(first.get(f["sha"], t), t)
    train, test = defaultdict(set), defaultdict(set)
    for f in fails:
        if f["kind"] == "own":
            (train if first[f["sha"]] < split else test)[f["sha"]].add(f["job"])
    if not train or not test:
        return None
    _, order = greedy_cover(train, cost, default, allowed)
    rows, chosen = [], set()
    for job, _, caught, minutes in order:
        chosen.add(job)
        hit = sum(1 for jobs in test.values() if jobs & chosen)
        rows.append((job, caught, hit, minutes))
    # the best any set of the same runner minutes could have done, knowing
    # the later part in advance
    _, best = greedy_cover(test, cost, default, allowed)
    return {"split": iso(split), "train": len(train), "test": len(test),
            "rows": rows, "best": [(c, m) for _, _, c, m in best]}


def analyse(data, train_share=2 / 3):
    since, until = ts(data["since"]), ts(data["until"])
    done = [r for r in for_master(data["pr_runs"])
            if r["conclusion"] in RED | GREEN]
    runs = [r for r in done if started(r)]
    current, alias = current_jobs(runs, until)
    fails = classify(data)
    for f in fails:
        f["job"] = alias.get(f["job"], f["job"])
    dur = durations(runs, alias)
    cost = {k: v[0] for k, v in dur.items()}
    typical = statistics.median(cost.values()) if cost else 1.0
    pushes = {r["sha"] for r in runs}
    red_pushes = {r["sha"] for r in runs if r["conclusion"] in RED}
    failing = defaultdict(set)   # push -> classes of its failed jobs
    own = defaultdict(set)       # push -> jobs with an own failure
    jobs = defaultdict(Counter)
    branches = defaultdict(set)
    for f in fails:
        failing[f["sha"]].add(f["kind"])
        jobs[f["job"]][f["kind"]] += 1
        if f["kind"] == "own":
            own[f["sha"]].add(f["job"])
            branches[f["job"]].add(f["branch"])
    for js in own.values():
        if len(js) == 1:
            jobs[next(iter(js))]["sole"] += 1
    # a failed job that passed on a re-run leaves the run green
    red_pushes |= set(failing)
    # What a push costs now: current jobs, each charged by the share of
    # recent pushes its workflow ran on (path filters skip some workflows).
    recent = iso(until - dt.timedelta(days=CURRENT_DAYS))
    late = {(r["sha"], r["workflow"]) for r in runs if r["started"] >= recent}
    n_late = len({sha for sha, _ in late})
    share = {wf: n / n_late for wf, n in Counter(wf for _, wf in late).items()}
    per_push = sum(m * share.get(k.split(" / ")[0], 0)
                   for k, m in cost.items() if k in current)
    wall = defaultdict(list)
    for r in runs:
        if (r["conclusion"] in GREEN and r["attempts"] == 1
                and share.get(r["workflow"], 0) >= 0.5):
            wall[r["workflow"]].append(
                (ts(r["updated"]) - ts(r["started"])).total_seconds() / 60)
    # shown by message: one breakage can fail hundreds of tests the same way
    errors = defaultdict(lambda: {"forks": set(), "jobs": set(), "n": set()})
    for f in fails:
        for msg in {message(e) for e in f["errors"]}:
            e = errors[msg]
            e["forks"].add(f["fork"])  # every failure counts, as in classify()
            if f["kind"] == "shared":
                e["jobs"].add(f["job"])
                e["n"].add(f["id"])
    errors = {m: e for m, e in errors.items() if e["n"]}
    # a message cut short by a long test name repeats a longer one
    errors = {m: e for m, e in errors.items() if not any(
        o != m and o.startswith(m) and errors[o]["n"] == e["n"] for o in errors)}
    total, order = greedy_cover(own, cost, typical, current)
    return {
        "since": data["since"], "until": data["until"],
        "backport_runs": len(data["pr_runs"]) - len(for_master(data["pr_runs"])),
        "never_started": len({r["sha"] for r in done} - pushes),
        "pushes": len(pushes), "red_pushes": len(red_pushes),
        "branches": len({r["branch"] for r in runs}),
        "own_pushes": len(own),
        "not_own_pushes": len([p for p in failing if p not in own]),
        "no_job_pushes": len(red_pushes - set(failing)),
        "retired_only": sum(1 for js in own.values() if not js & current),
        "fails": Counter(f["kind"] for f in fails),
        "inherited_how": Counter(f["master"] for f in fails if f["master"]),
        "no_error": sum(1 for f in fails
                        if f["kind"] == "own" and not f["errors"]),
        "jobs": {k: dict(v, branches=len(branches[k])) for k, v in jobs.items()},
        "current": current, "renamed": len(alias),
        "durations": dur, "cover_total": total, "cover": order,
        "per_push_minutes": per_push,
        "wall": {k: statistics.median(v) for k, v in wall.items()},
        "shared_errors": sorted(
            ((msg, len(e["forks"]), len(e["jobs"]), len(e["n"]))
             for msg, e in errors.items()),
            key=lambda x: (-x[3], -x[1], x[0])),
        "holdout": holdout(fails, cost, typical, since, until, train_share,
                           current),
    }


# -------------------------------------------------------------------- report

def pct(a, b):
    return "%d%%" % round(100.0 * a / b) if b else "-"


def render(a):
    L = []
    add = L.append
    n, f, how = a["pushes"], a["fails"], a["inherited_how"]
    add("# GDAL pull request CI: what each job catches")
    add("")
    add("Window %s to %s. Read-only study of `OSGeo/gdal` Actions history, "
        "pull requests against master only. Left out: %d runs of backports, "
        "and %d pushes whose runs failed before any job started."
        % (a["since"][:10], a["until"][:10], a["backport_runs"],
           a["never_started"]))
    add("")
    add("## Pushes")
    add("")
    add("| | Count | Share |")
    add("|---|---|---|")
    add("| Pull request pushes with a completed run | %d | |" % n)
    add("| ... from distinct branches | %d | |" % a["branches"])
    add("| ... with a failed job or run | %d | %s |"
        % (a["red_pushes"], pct(a["red_pushes"], n)))
    add("| ... failed, but with no failure of its own | %d | %s |"
        % (a["not_own_pushes"], pct(a["not_own_pushes"], n)))
    if a["no_job_pushes"]:
        add("| ... a run failed with no failed job on record | %d | %s |"
            % (a["no_job_pushes"], pct(a["no_job_pushes"], n)))
    add("| ... with a failure of its own | %d | %s |"
        % (a["own_pushes"], pct(a["own_pushes"], n)))
    add("")
    add("## Failed jobs")
    add("")
    total = sum(f.values())
    add("| Class | Failed jobs | Share |")
    add("|---|---|---|")
    for kind, what in (
            ("inherited", "Inherited: red on master too"),
            ("shared", "Shared: every error also seen on %d or more forks"
             % SHARED_FORKS),
            ("setup", "Setup: failed installing dependencies"),
            ("retried", "Retried: passed when re-run"),
            ("own", "Own: none of the above")):
        add("| %s | %d | %s |" % (what, f[kind], pct(f[kind], total)))
    add("")
    add("Inherited splits into %d where the job was red on master before the "
        "run, %d where it was red in the next master run, and %d matched by "
        "error text." % (how["before"], how["next"], how["error"]))
    add("%d own failures had no specific error to compare, so they could not "
        "be tested for being shared." % a["no_error"])
    add("")
    add("## Reduced set, in the order worth adding")
    add("")
    add("Each row adds the job that catches the most not-yet-caught pushes per "
        "runner minute. A push to a pull request now costs about %.0f runner "
        "minutes." % a["per_push_minutes"])
    if a["wall"]:
        slow = max(a["wall"], key=a["wall"].get)
        add("The slowest workflow that runs on most pushes, %s, takes a median "
            "%.0f minutes from start to finish." % (cell(slow), a["wall"][slow]))
    add("Only jobs seen in the last %d days can be chosen. %d pushes failed "
        "only in jobs not seen in that time, so no set catches them."
        % (CURRENT_DAYS, a["retired_only"]))
    add("")
    add("| # | Job | Newly caught | Caught so far | Runner minutes so far |")
    add("|---|---|---|---|---|")
    for i, (job, gain, caught, minutes) in enumerate(a["cover"], 1):
        add("| %d | %s | %d | %d of %d (%s) | %.0f |"
            % (i, cell(job), gain, caught, a["cover_total"],
               pct(caught, a["cover_total"]), minutes))
    add("")
    h = a.get("holdout")
    if h:
        add("## The same, chosen early and scored later")
        add("")
        add("The order is chosen from the %d own-failing pushes before %s and "
            "scored on the %d after it. \"Best possible\" is what a set of "
            "the same runner minutes could have caught with the later pushes "
            "known in advance."
            % (h["train"], h["split"][:10], h["test"]))
        add("")
        add("| # | Job | Earlier pushes caught | Later pushes caught | "
            "Best possible | Runner minutes so far |")
        add("|---|---|---|---|---|---|")
        for i, (job, caught, hit, minutes) in enumerate(h["rows"], 1):
            best = max([c for c, m in h["best"] if m <= minutes + 1e-9] or [0])
            add("| %d | %s | %d of %d (%s) | %d of %d (%s) | %s | %.0f |"
                % (i, cell(job), caught, h["train"], pct(caught, h["train"]),
                   hit, h["test"], pct(hit, h["test"]), pct(best, h["test"]),
                   minutes))
        add("")
    add("## Jobs")
    add("")
    add("Sole: pushes where it was the only job with an own failure. Branches: "
        "distinct pull request branches behind its own failures. A job marked "
        "\"not recent\" was not seen in the last %d days: it was renamed or "
        "removed, or its workflow only runs when certain files change."
        % CURRENT_DAYS)
    add("")
    add("| Job | Own | Sole | Branches | Inherited | Shared | Setup | Retried "
        "| Median min |")
    add("|---|---|---|---|---|---|---|---|---|")
    names = set(a["jobs"]) | set(a["durations"])
    for k in sorted(names, key=lambda k: (-a["jobs"].get(k, {}).get("own", 0), k)):
        j = a["jobs"].get(k, {})
        d = a["durations"].get(k)
        add("| %s%s | %d | %d | %d | %d | %d | %d | %d | %s |"
            % (cell(k), "" if k in a["current"] else " (not recent)", j.get("own", 0), j.get("sole", 0), j.get("branches", 0),
               j.get("inherited", 0), j.get("shared", 0), j.get("setup", 0),
               j.get("retried", 0), "%.0f" % d[0] if d else "-"))
    add("")
    if a["shared_errors"]:
        add("## Shared errors")
        add("")
        add("Errors behind the shared failures, most failed jobs first.")
        add("")
        add("| Error | Failed jobs | Forks | Jobs |")
        add("|---|---|---|---|")
        for msg, forks, njobs, count in a["shared_errors"][:20]:
            add("| %s | %d | %d | %d |" % (cell(msg[:140]), count, forks, njobs))
        add("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--sample", type=int, default=8,
                    help="green runs per workflow read for job durations")
    ap.add_argument("--cache", default=os.path.expanduser(
        "~/.cache/gdal-ci-history"))
    ap.add_argument("--out", default="history-out")
    ap.add_argument("--data", help="analyse this saved data.json, fetch nothing")
    ap.add_argument("--train-share", type=float, default=2 / 3,
                    help="early share of the window the held-out check "
                         "chooses its set from")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    if args.data:
        with open(args.data) as f:
            data = json.load(f)
    else:
        token = os.environ.get("GDAL_READ_TOKEN") or os.environ.get("GH_TOKEN")
        gh = GH(token, None, True, cache_dir=args.cache)
        logs = GH(token, None, True)  # no cache: logs are large, errors small
        data = collect(gh, args.days, args.sample)
        add_signatures(gh, logs, data)
        log("%d API calls, %d logs unavailable"
            % (gh.calls + logs.calls, logs.log_failures))
        with open(os.path.join(args.out, "data.json"), "w") as f:
            json.dump(data, f)
    report = render(analyse(data, args.train_share))
    with open(os.path.join(args.out, "report.md"), "w") as f:
        f.write(report)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
