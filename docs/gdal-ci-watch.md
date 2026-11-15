# GDAL CI watch

[`watch/gdal_ci_watch.py`](../watch/gdal_ci_watch.py), run every 3 hours by
[`gdal-ci-watch.yml`](../.github/workflows/gdal-ci-watch.yml), watches
OSGeo/gdal master CI. When a job goes red there, it opens an issue in this
repository with enough context to write a fix: what broke, when, what changed
in the environment, and whether someone on GDAL is already on it.

Most GDAL CI breakage comes from upstream tools that are installed without a
pinned version, not from GDAL commits: pytest, cmake, apt/brew/conda-forge
packages, runner images. The watcher is built around spotting that.

## What it never does

- Write anything to OSGeo/gdal: no issues, comments, reactions, PRs, or
  workflow dispatches. It only uses API reads and a sparse clone of
  `.github/`, `ci/` and the requirements files.
- Link back to or mention anything on the GDAL side. Writing
  `OSGeo/gdal#N`, a GDAL issue or PR URL, or an `@login` in an issue here
  would add a backlink on the GDAL issue or notify the person. All such text
  is put in code spans. `check_quiet()` blocks any title, body or comment that
  has one outside a code span; if it trips, the run fails and nothing is
  posted. Links to GDAL Actions runs, commits, compare views and file blobs
  are fine: they create no timeline events.
- Write outside this repository. `GH.write()` refuses any other path.

Commit messages in this repository should not reference GDAL issues or PRs
either: code spans don't stop a commit message from creating a backlink.

## How a failure is followed

1. Each GDAL workflow that still exists on master and has run there in the
   last 10 days is checked. Its latest completed master run (push, schedule
   or dispatch) is the current state. Workflows that don't build or test
   GDAL are skipped (`SKIP_WORKFLOW_FILES`).
2. For each red job, earlier master runs are walked back to the job's last
   green run. Cancelled and skipped runs are passed over.
3. PR runs of the same workflow from the last 48 hours are checked for the
   same job failing. Several authors hitting it is the clearest sign of an
   environment break, and of contributors being held up by it.
4. The failing step is read from the job log: from the end of the echoed
   command to the first `##[error]`. For a Docker build, only the BuildKit
   step that failed is used, since parallel steps interleave in the log. The
   most specific error line becomes the signature (CMake error, compiler
   error, resolver error, runner annotation, pytest/ctest failure, curl
   error, then the word "error" on its own, not inside a name like
   `libgpg-error-dev`). Paths and numbers are normalised, so one root cause
   across jobs and workflows becomes a single issue.
5. An issue is opened when a signature has been red on 2 or more master runs,
   or on PRs from 2 or more authors, or when the same commit went from green
   to red. Once an issue is open it is updated while the signature stays red.

## What an issue contains

All of it is produced by the script; no LLM is involved.

- **Likely:** one line of verdict. Possible verdicts: transient (the step
  logged an API rate limit, DNS or connection failure, 502/503/504, or a lost
  runner; a re-run may pass, but a step that hits it often may need making
  more robust); same commit was green (environment); failed while installing
  dependencies; CI/build files changed in between; no CI/build files changed
  but package versions did (drift); only source changed (possible code
  regression).
- Jobs, failing steps, red since, master runs red, PR authors red, last
  green, with links to the job logs.
- **Error sites:** distinct `file:line` (or test) locations from the log.
- **Package versions, last green to first red:** parsed from both job logs
  (conda, pip, pytest header and plugins, apt, apk, brew, cmake/swig/ninja
  version lines, runner image). Packages that GDAL CI names on an install
  line come first, with links to those lines and whether they are pinned.
- **Commits between:** compare link, whether any CI/build files changed, and
  the commit subjects.
- **Open on GDAL:** open PRs and issues updated in the two weeks before the
  job went red or since, matched on package and version, on distinctive
  tokens from the error, and on CI/CMake/build PRs opened since the job went
  red. If the fix is already in progress, this is where it shows up.
- **Precedent:** recent `CI:` commits on the same files, and commits that
  mention the package. These show the usual shape of the fix and the commit
  message style.
- **Log excerpt** around the signature and the end of the failing step.

Issues carry the `gdal-ci-watch` label and a hidden
`<!-- gdal-ci-watch {...} -->` line holding the fingerprint and job list. A
run edits the body only when the content changed, comments when more jobs
join, reopens when a closed signature comes back, and closes when the jobs
are green on master again, or when they now fail under another signature
that has its own issue. Each run's issue bodies and `plan.json` are uploaded
as an artifact; the step summary shows every red job, alerted or not.

## Tokens

`GITHUB_TOKEN` handles issues here and is enough for reading OSGeo/gdal,
job logs included. The workflow grants it `pull-requests: read`: without
that, GDAL's PRs are left out of the open issue listing (and out of issue
search), so an open fix PR would be missed. `GDAL_READ_TOKEN`, if set as a
secret, is used for GDAL reads instead.

## Running locally

```bash
git clone -q --depth 1 --filter=blob:none --no-checkout https://github.com/OSGeo/gdal /tmp/gdal-ci
git -C /tmp/gdal-ci sparse-checkout set --no-cone '/.github/' '/ci/' '/autotest/requirements.txt' '/doc/requirements.txt'
git -C /tmp/gdal-ci checkout -q
python3 watch/gdal_ci_watch.py --dry-run --gdal-ci-dir /tmp/gdal-ci \
  --out /tmp/watch-out --cache-dir /tmp/watch-cache
python3 -m unittest discover -s watch
```

`--dry-run` posts nothing: it writes each issue body to `--out` and prints the
summary. `--cache-dir` keeps job logs and job lists between runs. Thresholds:
`--min-red-runs`, `--min-pr-authors`, `--pr-hours`, `--stale-days`.

## Testing a fix

Push a branch to a personal fork of GDAL with Actions enabled. GDAL's own
workflows run there. Jobs that tag, deploy or delete are guarded to
`OSGeo/gdal`, and a fork's token can't push to `ghcr.io/osgeo`, so nothing
reaches GDAL until a PR is opened by hand. (Don't dispatch `docker.yml` on
the fork: it would just fail trying to push there.) Linux jobs can also be reproduced locally from
`.github/workflows/<job>/Dockerfile.ci` in a GDAL checkout.

Whatever goes to GDAL is subject to its
[AI tool policy](https://github.com/OSGeo/gdal/blob/master/doc/source/community/ai_tool_policy.rst):
the issue here is context for a human-written fix, and any LLM help with that
fix must be disclosed.
