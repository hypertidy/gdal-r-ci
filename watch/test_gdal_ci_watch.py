"""Tests for gdal_ci_watch.py. Run: python3 -m unittest discover -s watch"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gdal_ci_watch as w  # noqa: E402

TS = "2026-11-13T16:55:33.8011722Z "

CMAKE_LOG = "\n".join(TS + l for l in [
    "Current runner version: '2.338.2'",
    "##[group]Runner Image",
    "Image: windows-2025-vs2026",
    "Version: 20261103.298.1",
    "##[endgroup]",
    "##[group]Run conda install --yes cmake",
    "conda install --yes cmake -Werror=dev",
    "shell: bash -e {0}",
    "##[endgroup]",
    "    cmake-4.5.0                |       hde52c71_0        17.8 MB  conda-forge",
    "  cmake              conda-forge/win-64::cmake-4.5.0-hde52c71_0 ",
    "##[group]Run cmake -S . -B build -Werror=dev",
    "cmake -S . -B build -Werror=dev",
    "##[endgroup]",
    "cmake version 4.5.0",
    "-- Detecting CXX compile features - done",
    "CMake Error (non-target-directive) at CMakeLists.txt:56 (add_definitions):",
    "  Use of non-target directives is not recommended.",
    "This error is for project developers.  Use -Wno-error=author to suppress it.",
    r"CMake Error (non-target-directive) at D:\a\gdal\gdal\cmake\helpers\GdalCompilationFlags.cmake:39 (add_compile_options):",
    "-- Configuring incomplete, errors occurred!",
    "##[error]Process completed with exit code 1.",
    "##[group]Run actions/upload-artifact@v4",
])


class Quiet(unittest.TestCase):
    loud = [
        "see OSGeo/gdal#15528",
        "see https://github.com/OSGeo/gdal/pull/15528",
        "see https://github.com/osgeo/gdal/issues/1",
        "thanks @dbaston",
        "fixed in #15516",
        "GH-12",
    ]
    quiet = [
        "see `OSGeo/gdal#15528` and `https://github.com/OSGeo/gdal/pull/15528`",
        "by `dbaston`, ``a`b @x``",
        "~~~~\nthanks @dbaston, fixes #12\n~~~~",
        "<!-- gdal-ci-watch {\"x\": \"#1 @y\"} -->",
        "[log](https://github.com/OSGeo/gdal/actions/runs/1/job/2#step:7:12)",
        "[x](https://github.com/OSGeo/gdal/blob/abc/.github/workflows/w.yml#L458)",
        "[c](https://github.com/OSGeo/gdal/compare/a...b) mail a@b.com python@3.13",
        "### Heading",
    ]

    def test_loud(self):
        for t in self.loud:
            with self.assertRaises(w.LoudText, msg=t):
                w.check_quiet(t)

    def test_quiet(self):
        for t in self.quiet:
            w.check_quiet(t)

    def test_code_span_survives_backticks(self):
        for s in ["a`b", "``x``", "`", "plain"]:
            w.check_quiet(w.code(s + " @someone #12"))

    def test_fenced_survives_tildes(self):
        w.check_quiet(w.fenced("~~~~\n@someone #12\n~~~~~"))

    def test_plain_title(self):
        t = w.plain_title("GDAL CI: x: fix for OSGeo/gdal#12 by @me")
        w.check_quiet(t)
        self.assertNotIn("#", t)
        self.assertNotIn("@", t)


class Logs(unittest.TestCase):
    def setUp(self):
        self.lines = w.clean(CMAKE_LOG)

    def test_clean(self):
        self.assertEqual(w.clean(TS + "\x1b[32m==>\x1b[0m Pouring x")[0], "==> Pouring x")
        self.assertEqual(w.clean(TS + "41: platform win32 -- Python 3.12")[0],
                         "platform win32 -- Python 3.12")
        self.assertEqual(w.clean("#12 3.45 E: Unable to locate package foo")[0],
                         "E: Unable to locate package foo")

    def test_section_skips_echoed_command(self):
        sec = w.failing_section(self.lines)
        self.assertEqual(sec[0], "cmake version 4.5.0")
        self.assertEqual(sec[-1], "##[error]Process completed with exit code 1.")

    def test_signature_and_sites(self):
        sec = w.failing_section(self.lines)
        sig, cat, _ = w.signature(sec)
        self.assertEqual(cat, "cmake")
        self.assertTrue(sig.startswith("CMake Error (non-target-directive) at CMakeLists.txt:56"))
        self.assertEqual(list(w.error_sites(sec)),
                         ["CMakeLists.txt:56", "cmake/helpers/GdalCompilationFlags.cmake:39"])

    def test_signature_annotation(self):
        sec = ["Fetching readline", '##[error]Failed to download resource "readline83-001"']
        sig, cat, _ = w.signature(sec)
        self.assertEqual((sig, cat), ('Failed to download resource "readline83-001"', "annotation"))

    def test_signature_resolve(self):
        sec = ["Reading package lists...", "E: Unable to locate package libpcre3-dev",
               "##[error]Process completed with exit code 100."]
        self.assertEqual(w.signature(sec)[1], "resolve")

    def test_signature_none(self):
        self.assertEqual(w.signature(["ok", "##[error]Process completed with exit code 1."]),
                         (None, None, None))

    def test_normalise_is_stable_across_paths_and_numbers(self):
        a = w.normalise(r"D:\a\gdal\gdal\port\x.cpp(12): error C2065: 'y'")
        b = w.normalise("/home/runner/work/gdal/gdal/port/x.cpp(345): error C2065: 'y'")
        self.assertEqual(a, b)
        self.assertEqual(w.fingerprint(a), w.fingerprint(b))


class Env(unittest.TestCase):
    def test_versions(self):
        lines = w.clean(CMAKE_LOG) + [
            "Successfully installed Jinja2-3.1.6 pytest-9.2.0 typing_extensions-4.15.0",
            "platform linux -- Python 3.12.3, pytest-9.1.1, pluggy-1.6.0",
            "plugins: env-1.1.5, benchmark-5.1.0",
            "Setting up libpcre2-dev:amd64 (10.42-4ubuntu2) ...",
            "(12/80) Installing swig (4.3.0-r0)",
            "==> Pouring cmake--4.5.0.arm64_sequoia.bottle.tar.gz",
            "==> Pouring python@3.13--3.13.9_1.arm64_sequoia.bottle.tar.gz",
            "  + ruff    0.7.1  h123  conda-forge  10MB",
        ]
        env = w.env_versions(lines)
        self.assertEqual(env[("conda", "cmake")], "4.5.0")
        self.assertEqual(env[("tool", "cmake")], "4.5.0")
        self.assertEqual(env[("runner", "windows-2025-vs2026")], "20261103.298.1")
        self.assertEqual(env[("pip", "jinja2")], "3.1.6")
        self.assertEqual(env[("pip", "typing-extensions")], "4.15.0")
        self.assertEqual(env[("pip", "pytest")], "9.1.1")  # header seen last wins
        self.assertEqual(env[("pytest-plugin", "benchmark")], "5.1.0")
        self.assertEqual(env[("apt", "libpcre2-dev")], "10.42-4ubuntu2")
        self.assertEqual(env[("apk", "swig")], "4.3.0-r0")
        self.assertEqual(env[("brew", "cmake")], "4.5.0")
        self.assertEqual(env[("brew", "python@3-13")], "3.13.9_1")
        self.assertEqual(env[("conda", "ruff")], "0.7.1")

    def test_diff(self):
        d = w.env_diff({("conda", "cmake"): "4.4.5", ("conda", "x"): "1"},
                       {("conda", "cmake"): "4.5.0", ("conda", "x"): "1",
                        ("conda", "y"): "2"})
        self.assertEqual(sorted(d), [("conda", "cmake", "4.4.5", "4.5.0"),
                                     ("conda", "y", None, "2")])


class Index(unittest.TestCase):
    def test_install_lines(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".github/workflows/u"))
            os.makedirs(os.path.join(d, "autotest"))
            with open(os.path.join(d, ".github/workflows/win.yml"), "w") as f:
                f.write("    run: |\n"
                        "        conda install --yes proj python=3.12 pytest=9.1.1 \\\n"
                        "            libheif cmake fsspec\n"
                        "        pip install -r doc/requirements.txt\n"
                        "        cmake -S . -B build\n")
            with open(os.path.join(d, ".github/workflows/u/Dockerfile.ci"), "w") as f:
                f.write("RUN apt-get update && apt-get install -y \\\n"
                        "    cmake \\\n"
                        "    && rm -rf /var/lib/apt/lists/*\n"
                        "RUN echo rm\n")
            with open(os.path.join(d, "autotest/requirements.txt"), "w") as f:
                f.write("pytest>=6.0.0,!=9.1.0,<9.2.0\npytest-env\n# comment\n")
            ci = w.CIIndex(d)
            self.assertTrue(ci.present)
            cm = ci.find("cmake", ".github/workflows/win.yml")
            self.assertEqual([(h[0], h[1], h[2]) for h in cm],
                             [(".github/workflows/win.yml", 3, False),
                              (".github/workflows/u/Dockerfile.ci", 2, False)])
            py = {(h[0], h[2]) for h in ci.find("pytest")}
            self.assertEqual(py, {(".github/workflows/win.yml", True),
                                  ("autotest/requirements.txt", True)})
            self.assertEqual(ci.find("rm"), [])
            self.assertEqual(ci.find("pytest_env")[0][0], "autotest/requirements.txt")


class Render(unittest.TestCase):
    def test_hostile_inputs_render_quiet(self):
        pt = {"run_id": 1, "job_id": 2, "sha": "a" * 40, "created": "2026-11-13T00:00:00Z",
              "url": "https://github.com/OSGeo/gdal/actions/runs/1/job/2", "event": "push"}
        job = {"workflow": "Win #1 @x", "workflow_file": ".github/workflows/w.yml",
               "wf_id": 1, "job": "build | @someone", "step": "Configure #2",
               "latest": pt, "red_runs": 2, "red_shas": [], "first_red": pt,
               "last_green": dict(pt, sha="b" * 40), "pr_authors": ["u1", "u2"],
               "analysis": {"signature": "error at #12 by @me", "category": "generic",
                            "sites": {"x.cpp:1": 2}, "excerpt": "@me fixed #12\n~~~~"}}
        g = {"fp": "f" * 12, "norm": "n", "signature": "error at #12 by @me",
             "category": "generic", "jobs": [job], "primary": job}
        ctx = {"env": [{"mgr": "conda", "name": "cmake", "green": "4.4", "red": "4.5",
                        "hits": [(".github/workflows/w.yml", 3, False, "x")],
                        "unpinned": [(".github/workflows/w.yml", 3, False, "x")]}],
               "env_job": job,
               "compare": {"url": "https://github.com/OSGeo/gdal/compare/a...b", "n": 1,
                           "subjects": ["CI: pin (#15516) thanks @dbaston"],
                           "ci_files": [], "n_files": 1},
               "gdal_open": [{"number": 15528, "title": "CMake 4.5 (#1) @x", "user": "dbaston",
                              "created": "2026-11-13", "kind": "PR",
                              "url": "https://github.com/OSGeo/gdal/pull/15528", "query": "q"}],
               "precedent": [{"sha": "c" * 40, "date": "2026-11-12",
                              "subject": "CI: x (#15516)", "file": "f"}],
               "queries": ["cmake 4.5", '"non-target-directive"'],
               "notes": ["note #3 @y"]}
        body, meta = w.render(g, ctx, "https://github.com/hypertidy/gdal-r-ci/actions/runs/9",
                              "now")
        w.check_quiet(body)
        w.check_quiet(w.title_for(g))
        self.assertEqual(meta["fp"], "f" * 12)


class LogFetch(unittest.TestCase):
    def test_retries_with_escape_flag(self):
        gh = w.GH(None, None, dry_run=True)
        seen = []

        def fake_run(args, token, stdin=None):
            seen.append(list(args))
            if "--allow-escape-sequences" not in args:
                raise RuntimeError("gh api ...: the response contains terminal escape "
                                   "sequences; pass --allow-escape-sequences to output it anyway")
            return "log text"

        gh._run = fake_run
        self.assertEqual(gh.log(1), "log text")
        self.assertEqual(gh.log(2), "log text")
        self.assertEqual(len(seen), 3)  # second log goes straight to the flag
        self.assertEqual(gh.log_failures, 0)

    def test_other_errors_count_as_failures(self):
        gh = w.GH(None, None, dry_run=True)

        def fake_run(args, token, stdin=None):
            raise RuntimeError("HTTP 403")

        gh._run = fake_run
        self.assertIsNone(gh.log(1))
        self.assertEqual(gh.log_failures, 1)
        self.assertFalse(gh.escape_flag)


class Guards(unittest.TestCase):
    def test_refuses_to_write_to_gdal(self):
        gh = w.GH(None, None, dry_run=True)
        with self.assertRaises(RuntimeError):
            gh.write("POST", "repos/OSGeo/gdal/issues", {"title": "x", "body": "y"})

    def test_refuses_loud_body(self):
        gh = w.GH(None, None, dry_run=True)
        with self.assertRaises(w.LoudText):
            gh.write("POST", "repos/%s/issues" % w.REPO, {"title": "x", "body": "cc @dbaston"})


if __name__ == "__main__":
    unittest.main()
