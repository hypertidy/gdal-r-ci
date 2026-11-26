"""Tests for gdal_ci_history.py. Run: python3 -m unittest discover -s watch"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gdal_ci_history as h  # noqa: E402


IDS = iter(range(1000, 100000))


def job(name, conclusion, start="2026-11-10T10:00:00Z", minutes=30, attempt=1,
        step="Build", sig=None, cat="pytest"):
    end = h.iso(h.ts(start) + h.dt.timedelta(minutes=minutes))
    j = {"id": next(IDS), "name": name, "conclusion": conclusion,
         "started": start, "completed": end, "minutes": float(minutes),
         "step": step, "attempt": attempt}
    if sig:
        j["cat"] = cat
        j["errors"] = [sig] if isinstance(sig, str) else list(sig)
    return j


def run(rid, sha, conclusion, jobs=None, workflow="Linux", event="pull_request",
        start="2026-11-10T10:00:00Z", fork="f1", minutes=60, base=None):
    r = {"id": rid, "workflow": workflow, "workflow_file": "linux.yml",
         "event": event, "sha": sha, "fork": fork, "branch": fork + "-fix",
         "base": base, "conclusion": conclusion,
         "attempts": len(jobs) if jobs else 1, "started": start,
         "created": start,
         "updated": h.iso(h.ts(start) + h.dt.timedelta(minutes=minutes))}
    if jobs:
        r["jobs"] = jobs
    return r


def master(rid, conclusion, start, red=(), cancelled=(), sig=None):
    jobs = [job(n, "failure", start, sig=sig) for n in red]
    jobs += [job(n, "cancelled", start) for n in cancelled]
    return run(rid, "m%d" % rid, conclusion, [jobs] if jobs else None,
               event="push", start=start, fork="upstream")


def data(pr_runs, master_runs=(), until="2026-11-26T00:00:00Z"):
    return {"since": "2026-11-01T00:00:00Z", "until": until,
            "pr_runs": list(pr_runs), "master_runs": list(master_runs)}


class Classify(unittest.TestCase):
    def kinds(self, d):
        return {(f["sha"], f["job"]): f["kind"] for f in h.classify(d)}

    def test_own_when_master_green(self):
        d = data([run(1, "a", "failure", [[job("gcc", "failure")]])],
                 [master(9, "success", "2026-11-10T06:00:00Z")])
        self.assertEqual(self.kinds(d), {("a", "Linux / gcc"): "own"})

    def test_inherited_when_master_red_before(self):
        d = data([run(1, "a", "failure", [[job("gcc", "failure"),
                                           job("clang", "failure")]])],
                 [master(9, "failure", "2026-11-10T06:00:00Z", red=["gcc"])])
        k = self.kinds(d)
        self.assertEqual(k[("a", "Linux / gcc")], "inherited")
        self.assertEqual(k[("a", "Linux / clang")], "own")

    def test_master_fixed_before_the_run(self):
        d = data([run(1, "a", "failure", [[job("gcc", "failure")]])],
                 [master(8, "failure", "2026-11-09T06:00:00Z", red=["gcc"]),
                  master(9, "success", "2026-11-10T06:00:00Z")])
        self.assertEqual(self.kinds(d), {("a", "Linux / gcc"): "own"})

    def test_inherited_when_next_master_run_is_red(self):
        # drift reaches a pull request before master has run again
        d = data([run(1, "a", "failure", [[job("gcc", "failure")]])],
                 [master(8, "success", "2026-11-09T06:00:00Z"),
                  master(9, "failure", "2026-11-10T12:00:00Z", red=["gcc"])])
        f = h.classify(d)[0]
        self.assertEqual((f["kind"], f["master"]), ("inherited", "next"))

    def test_next_master_run_too_late_to_count(self):
        d = data([run(1, "a", "failure", [[job("gcc", "failure")]])],
                 [master(9, "failure", "2026-11-12T12:00:00Z", red=["gcc"])])
        self.assertEqual(self.kinds(d), {("a", "Linux / gcc"): "own"})

    def test_cancelled_master_job_says_nothing(self):
        # the red run cancelled gcc; the earlier red result still stands
        d = data([run(1, "a", "failure", [[job("gcc", "failure")]])],
                 [master(8, "failure", "2026-11-09T06:00:00Z", red=["gcc"]),
                  master(9, "failure", "2026-11-10T06:00:00Z", red=["clang"],
                         cancelled=["gcc"])])
        self.assertEqual(self.kinds(d), {("a", "Linux / gcc"): "inherited"})

    def test_other_workflow_on_master_is_ignored(self):
        m = master(9, "failure", "2026-11-10T06:00:00Z", red=["gcc"])
        m["workflow"] = "Windows"
        d = data([run(1, "a", "failure", [[job("gcc", "failure")]])], [m])
        self.assertEqual(self.kinds(d), {("a", "Linux / gcc"): "own"})

    def test_retried_when_a_rerun_passes(self):
        d = data([run(1, "a", "success",
                      [[job("gcc", "failure"), job("clang", "success")],
                       [job("gcc", "success", attempt=2),
                        job("clang", "success")]])])
        self.assertEqual(self.kinds(d), {("a", "Linux / gcc"): "retried"})

    def test_own_when_the_rerun_fails_too(self):
        d = data([run(1, "a", "failure", [[job("gcc", "failure")],
                                          [job("gcc", "failure", attempt=2)]])])
        self.assertEqual(self.kinds(d), {("a", "Linux / gcc"): "own"})
        self.assertEqual(len(h.classify(d)), 1)

    def test_runs_without_jobs_are_skipped(self):
        self.assertEqual(h.classify(data([run(1, "a", "success")])), [])

    def test_inherited_when_master_failed_with_the_same_error(self):
        # master is green in between, so timing alone would say "own"
        m = [master(7, "failure", "2026-11-08T06:00:00Z", red=["clang"],
                    sig="FAILED x.py::test_flaky"),
             master(8, "success", "2026-11-09T06:00:00Z"),
             master(9, "success", "2026-11-11T06:00:00Z")]
        d = data([run(1, "a", "failure",
                      [[job("gcc", "failure", sig="FAILED x.py::test_flaky")]])], m)
        f = h.classify(d)[0]
        self.assertEqual((f["kind"], f["master"]), ("inherited", "error"))

    def test_same_error_on_master_long_ago_does_not_count(self):
        m = [master(7, "failure", "2026-11-01T06:00:00Z", red=["clang"],
                    sig="FAILED x.py::test_flaky"),
             master(8, "success", "2026-11-09T06:00:00Z")]
        d = data([run(1, "a", "failure",
                      [[job("gcc", "failure", sig="FAILED x.py::test_flaky")]])], m)
        self.assertEqual(self.kinds(d), {("a", "Linux / gcc"): "own"})

    def test_setup_when_the_install_step_failed(self):
        d = data([run(1, "a", "failure",
                      [[job("gcc", "failure", step="Install dependencies")]])])
        self.assertEqual(self.kinds(d), {("a", "Linux / gcc"): "setup"})

    def test_shared_needs_the_error_on_enough_forks(self):
        def pr(rid, sha, fork, sig="FAILED x.py::test_net"):
            return run(rid, sha, "failure", [[job("gcc", "failure", sig=sig)]],
                       fork=fork)
        two = data([pr(1, "a", "f1"), pr(2, "b", "f2"), pr(3, "c", "f2")])
        self.assertEqual(set(self.kinds(two).values()), {"own"})
        three = data([pr(1, "a", "f1"), pr(2, "b", "f2"), pr(3, "c", "f3"),
                      pr(4, "d", "f4", sig="x.cpp:N: error: mine")])
        k = self.kinds(three)
        self.assertEqual(k[("a", "Linux / gcc")], "shared")
        self.assertEqual(k[("d", "Linux / gcc")], "own")

    def test_shared_needs_every_failed_test_to_be_shared(self):
        flaky, mine = "FAILED x.py::test_net", "FAILED y.py::test_mine"

        def pr(rid, sha, fork, sig):
            return run(rid, sha, "failure", [[job("gcc", "failure", sig=sig)]],
                       fork=fork)
        d = data([pr(1, "a", "f1", flaky), pr(2, "b", "f2", flaky),
                  pr(3, "c", "f3", [flaky, mine])])
        k = self.kinds(d)
        self.assertEqual(k[("a", "Linux / gcc")], "shared")
        self.assertEqual(k[("c", "Linux / gcc")], "own")

    def test_inherited_needs_every_failed_test_on_master(self):
        flaky, mine = "FAILED x.py::test_net", "FAILED y.py::test_mine"
        m = [master(7, "failure", "2026-11-09T06:00:00Z", red=["clang"],
                    sig=flaky),
             master(8, "success", "2026-11-09T12:00:00Z"),
             master(9, "success", "2026-11-11T06:00:00Z")]
        d = data([run(1, "a", "failure",
                      [[job("gcc", "failure", sig=[flaky, mine])]])], m)
        self.assertEqual(self.kinds(d), {("a", "Linux / gcc"): "own"})

    def test_vague_errors_are_not_compared(self):
        # the suite name alone does not say two failures are the same
        for cat in ("ctest", "generic", "pytest-E"):
            d = data([run(i, "s%d" % i, "failure",
                          [[job("gcc", "failure", sig="N - autotest_gcore (Failed)",
                                cat=cat)]], fork="f%d" % i) for i in range(4)])
            self.assertEqual(set(self.kinds(d).values()), {"own"}, cat)

    def test_failures_without_an_error_line_are_never_shared(self):
        d = data([run(i, "s%d" % i, "failure", [[job("gcc", "failure")]],
                      fork="f%d" % i) for i in range(4)])
        self.assertEqual(set(self.kinds(d).values()), {"own"})

    def test_backport_base_is_read_from_the_branch_name(self):
        wf = {"name": "Linux", "path": ".github/workflows/linux.yml"}
        r = {"id": 1, "event": "pull_request", "head_sha": "a",
             "conclusion": "failure", "created_at": "2026-11-10T10:00:00Z",
             "updated_at": "2026-11-10T11:00:00Z", "pull_requests": [],
             "head_branch": "backport-15566-to-release/3.13",
             "head_repository": {"full_name": "OSGeo/gdal"}}
        self.assertEqual(h.slim_run(r, wf)["base"], "release/3.13")
        # a fork may name a branch anything
        r["head_repository"] = {"full_name": "someone/gdal"}
        s = h.slim_run(r, wf)
        self.assertIsNone(s["base"])
        self.assertNotIn("someone", h.json.dumps(s))
        r["pull_requests"] = [{"base": {"ref": "release/3.12"}}]
        self.assertEqual(h.slim_run(r, wf)["base"], "release/3.12")

    def test_backports_are_left_out(self):
        d = data([run(1, "a", "failure", [[job("gcc", "failure")]],
                      base="release/3.13"),
                  run(2, "b", "failure", [[job("gcc", "failure")]],
                      base="master")])
        self.assertEqual(self.kinds(d), {("b", "Linux / gcc"): "own"})


class Errors(unittest.TestCase):
    def test_every_failed_test_is_kept(self):
        cat, lines = h.error_lines([
            "collected 9000 items",
            "FAILED gcore/a.py::test_one - RuntimeError: /tmp/x123 not found",
            "FAILED gcore/b.py::test_two[3] - AssertionError",
            "ERROR 1: something GDAL printed on the way",
            "FAILED gcore/a.py::test_one - RuntimeError: /tmp/x123 not found",
        ])
        self.assertEqual(cat, "pytest")
        self.assertEqual(lines, [
            "FAILED gcore/a.py::test_one - RuntimeError: /tmp/xN not found",
            "FAILED gcore/b.py::test_two[N] - AssertionError"])

    def test_one_line_for_other_categories(self):
        cat, lines = h.error_lines([
            "/__w/gdal/gdal/port/cpl_port.h:248:5: error: expected ';'",
            "/__w/gdal/gdal/port/cpl_port.h:300:5: error: something else"])
        self.assertEqual(cat, "compile")
        self.assertEqual(lines, ["port/cpl_port.h:N:N: error: expected ';'"])

    def test_nothing_recognised(self):
        self.assertEqual(h.error_lines(["all fine", ""]), (None, []))


class Cover(unittest.TestCase):
    def test_prefers_catch_per_minute(self):
        pushes = {"a": {"slow", "fast"}, "b": {"slow"}, "c": {"fast"},
                  "d": {"slow"}}
        total, order = h.greedy_cover(pushes, {"slow": 100.0, "fast": 10.0})
        self.assertEqual(total, 4)
        self.assertEqual([o[0] for o in order], ["fast", "slow"])
        self.assertEqual(order[0][1:], (2, 2, 10.0))
        self.assertEqual(order[1][1:], (2, 4, 110.0))

    def test_every_push_ends_up_caught(self):
        pushes = {"a": {"x"}, "b": {"y"}, "c": {"x", "y", "z"}, "d": set()}
        total, order = h.greedy_cover(pushes, {})
        self.assertEqual(total, 3)
        self.assertEqual(order[-1][2], 3)
        self.assertNotIn("z", [o[0] for o in order])

    def test_only_allowed_jobs_are_chosen(self):
        pushes = {"a": {"old"}, "b": {"old", "new"}, "c": {"new"}}
        total, order = h.greedy_cover(pushes, {}, allowed={"new"})
        self.assertEqual(total, 3)
        self.assertEqual(order, [("new", 2, 2, 1.0)])

    def test_unknown_duration_is_charged_the_default(self):
        pushes = {"a": {"known"}, "b": {"unknown"}, "c": {"unknown"}}
        _, order = h.greedy_cover(pushes, {"known": 10.0}, default=40.0)
        self.assertEqual([o[0] for o in order], ["known", "unknown"])
        self.assertEqual(order[-1][3], 50.0)


class Analyse(unittest.TestCase):
    def test_push_counts(self):
        m = [master(9, "failure", "2026-11-10T06:00:00Z", red=["gcc"])]
        prs = [
            run(1, "a", "failure", [[job("gcc", "failure")]]),             # inherited
            run(2, "b", "failure", [[job("clang", "failure")]]),           # own
            run(3, "c", "success", [[job("clang", "failure")],
                                    [job("clang", "success", attempt=2)]]),  # retried
            run(4, "d", "success", [[job("clang", "success", minutes=40),
                                     job("gcc", "success", minutes=20)]]),
            run(5, "e", "cancelled"),
            run(6, "f", "failure", [[job("old", "failure")]], base="release/3.13"),
            # a workflow with path filters: ran on one push in four
            run(7, "d", "success", [[job("image", "success", minutes=100)]],
                workflow="Docker"),
        ]
        # a pull request nobody approved: red, but no job ever existed
        prs.append(run(8, "g", "failure"))
        prs[-1]["jobs"] = [[]]
        a = h.analyse(data(prs, m, until="2026-11-12T00:00:00Z"))
        self.assertEqual(a["pushes"], 4)
        self.assertEqual(a["never_started"], 1)
        self.assertEqual(a["backport_runs"], 1)
        self.assertEqual(a["red_pushes"], 3)  # the re-run one failed first
        self.assertEqual(a["not_own_pushes"], 2)
        self.assertEqual(a["no_job_pushes"], 0)
        self.assertEqual(a["own_pushes"], 1)
        self.assertEqual(a["fails"], {"inherited": 1, "own": 1, "retried": 1})
        self.assertEqual(a["no_error"], 1)
        self.assertEqual(a["jobs"]["Linux / clang"]["sole"], 1)
        self.assertEqual(a["durations"]["Linux / clang"][0], 35.0)
        self.assertNotIn("Linux / old", a["durations"])
        self.assertEqual(a["per_push_minutes"], 35.0 + 20.0 + 100.0 / 4)
        self.assertEqual(a["cover"], [("Linux / clang", 1, 1, 35.0)])
        report = h.render(a)
        self.assertIn("Linux / clang", report)
        self.assertNotIn("## Shared errors", report)

    def test_shared_errors_are_listed_by_message(self):
        prs = [run(i, "s%d" % i, "failure", [[job("gcc", "failure", sig=[
            "ERROR a.py::test_%d - AttributeError: no _nodeid" % t
            for t in range(3)])]], fork="f%d" % i) for i in range(3)]
        a = h.analyse(data(prs))
        self.assertEqual(a["fails"], {"shared": 3})
        self.assertEqual(a["own_pushes"], 0)
        self.assertEqual(a["not_own_pushes"], 3)
        self.assertEqual(a["shared_errors"],
                         [("AttributeError: no _nodeid", 3, 1, 3)])
        self.assertIn("## Shared errors", h.render(a))


class Current(unittest.TestCase):
    def test_a_job_that_changed_workflow_keeps_its_name(self):
        old, new = "2026-10-01T10:00:00Z", "2026-11-20T10:00:00Z"
        runs = [
            run(1, "a", "failure", [[job("win-conda", "failure"),
                                     job("build-mac", "failure")]],
                workflow="CMake", start=old),
            run(2, "b", "success", [[job("win-conda", "success")]],
                workflow="Windows", start=new),
            run(3, "c", "success", [[job("macos-conda", "success")]],
                workflow="MacOS", start=new),
        ]
        current, alias = h.current_jobs(runs, h.ts("2026-11-26T00:00:00Z"))
        self.assertEqual(current, {"Windows / win-conda", "MacOS / macos-conda"})
        self.assertEqual(alias, {"CMake / win-conda": "Windows / win-conda"})

    def test_a_name_used_twice_is_not_matched(self):
        old, new = "2026-10-01T10:00:00Z", "2026-11-20T10:00:00Z"
        runs = [run(1, "a", "success", [[job("build", "success")]],
                    workflow="CMake", start=old),
                run(2, "b", "success", [[job("build", "success")]],
                    workflow="Windows", start=new),
                run(3, "c", "success", [[job("build", "success")]],
                    workflow="MacOS", start=new)]
        self.assertEqual(h.current_jobs(runs, h.ts("2026-11-26T00:00:00Z"))[1], {})

    def test_gone_jobs_cannot_be_chosen(self):
        old, new = "2026-10-01T10:00:00Z", "2026-11-20T10:00:00Z"
        prs = [
            run(1, "a", "failure", [[job("win-conda", "failure", start=old),
                                     job("build-mac", "failure", start=old)]],
                workflow="CMake", start=old),
            run(2, "b", "failure", [[job("build-mac", "failure", start=old)]],
                workflow="CMake", start=old),
            run(3, "c", "failure", [[job("win-conda", "failure", start=new)]],
                workflow="Windows", start=new),
        ]
        d = data(prs)
        d["since"] = "2026-09-27T00:00:00Z"
        a = h.analyse(d)
        self.assertEqual(a["own_pushes"], 3)
        self.assertEqual(a["retired_only"], 1)
        self.assertEqual(a["jobs"]["Windows / win-conda"]["own"], 2)
        self.assertEqual([c[:3] for c in a["cover"]],
                         [("Windows / win-conda", 2, 2)])
        self.assertEqual(a["cover_total"], 3)
        self.assertIn("`CMake / build-mac` (not recent)", h.render(a))

    def test_message(self):
        self.assertEqual(h.message(
            "ERROR a.py::test_x[near-N] - AttributeError: no attribute '_nodeid'"),
            "AttributeError: no attribute '_nodeid'")
        self.assertEqual(h.message("FAILED a.py::test_http_N - Failed"),
                         "FAILED a.py::test_http_N")
        self.assertEqual(h.message("ERROR a.py::test_named[Lambert-Center = N"),
                         "ERROR a.py::test_named")
        self.assertEqual(h.message("CMake Error at CMakeLists.txt:N (x):"),
                         "CMake Error at CMakeLists.txt:N (x):")


class Holdout(unittest.TestCase):
    def fail(self, sha, job, day, kind="own"):
        return {"sha": sha, "job": job, "kind": kind,
                "when": "2026-11-%02dT10:00:00Z" % day}

    def split(self, fails, cost=None):
        return h.holdout(fails, cost or {}, 10.0, h.ts("2026-11-01T00:00:00Z"),
                         h.ts("2026-11-30T00:00:00Z"), 2 / 3)

    def test_set_is_chosen_early_and_scored_late(self):
        fails = [self.fail("a", "gcc", 2), self.fail("b", "gcc", 3),
                 self.fail("c", "docs", 4),
                 # later: gcc still catches one, a new job catches the other
                 self.fail("d", "gcc", 25), self.fail("e", "new", 26),
                 self.fail("f", "gcc", 27, kind="inherited")]
        r = self.split(fails)
        self.assertEqual((r["train"], r["test"]), (3, 2))
        self.assertEqual(r["split"][:10], "2026-11-20")
        self.assertEqual(r["rows"], [("gcc", 2, 1, 10.0), ("docs", 3, 1, 20.0)])
        self.assertEqual(r["best"], [(1, 10.0), (2, 20.0)])

    def test_a_push_belongs_to_the_part_it_started_in(self):
        fails = [self.fail("a", "gcc", 19), self.fail("a", "docs", 21),
                 self.fail("b", "docs", 22)]
        r = self.split(fails)
        self.assertEqual((r["train"], r["test"]), (1, 1))

    def test_nothing_to_score(self):
        self.assertIsNone(self.split([self.fail("a", "gcc", 2)]))
        self.assertIsNone(self.split([self.fail("a", "gcc", 25)]))

    def test_report_has_the_section(self):
        prs = [run(i, "s%d" % i, "failure", [[job("gcc", "failure", start=t)]],
                   start=t)
               for i, t in enumerate(["2026-11-03T10:00:00Z",
                                      "2026-11-24T10:00:00Z"])]
        report = h.render(h.analyse(data(prs)))
        self.assertIn("chosen early and scored later", report)
        self.assertIn("| 1 | `Linux / gcc` | 1 of 1 (100%) | 1 of 1 (100%) "
                      "| 100% |", report)


if __name__ == "__main__":
    unittest.main()
