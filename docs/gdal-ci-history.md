# GDAL CI history

[`watch/gdal_ci_history.py`](../watch/gdal_ci_history.py) is a read-only study
of OSGeo/gdal's pull request CI. It asks one question: if a pull request ran
only some of the CI jobs, and the full matrix ran less often, which failures
would the reduced set still catch?

It is the companion to the [GDAL CI watch](gdal-ci-watch.md). The watch
follows master and reports what is broken now. This looks back over weeks of
pull request runs and measures what each job contributed. It is run by hand,
not on a schedule.

## What it never does

- Write anything to OSGeo/gdal. It reads the Actions API (runs and jobs) and
  the logs of failed jobs, nothing else.
- Keep logins. A fork and a branch are stored as hashes, which is enough to
  count how many distinct forks hit the same error.
- Involve an LLM. The report is produced by the script alone.

## How a failed job is classified

The unit is a push to a pull request against master: one commit, with all the
workflow runs GitHub started for it. Every job that failed on a push is put
in one class, tried in this order.

| Class | Meaning |
|---|---|
| Inherited | The same job was red on master: either in the last master run before the pull request run, or in the first one within 24 hours after it (drift reaches pull requests before master runs again). Also inherited if every error in the job failed a master run of the same workflow within 72 hours. |
| Retried | The job failed, was re-run on the same commit, and passed. |
| Setup | The job failed in a step that installs dependencies. |
| Shared | Every error in the job also failed pull requests from three or more forks in the window. |
| Own | None of the above. This is the failure the full matrix is there to catch. |

When in doubt a failure is "own", so "own" is an upper bound:

- Errors are read from the failed step of the job log with the watch's
  signature code, then paths and numbers are normalised.
- Two errors are only compared when they name something specific: a CMake
  error, a compiler error, a package that would not resolve, a runner
  annotation, a Python import error, a failed pytest test, a failed download.
  A ctest line names only the suite, and a bare "error" line is printed by
  many unrelated failures, so neither is compared.
- When pytest names the failed tests, all of them are kept. A job is excused
  only if every one of its failed tests is inherited or shared. One flaky
  test next to one real failure stays "own".

Left out of the study:

- Backports to release branches, which run the release branch's older
  workflows. They are recognised by the base branch GitHub reports, or by the
  `backport-N-to-<branch>` name of the branch.
- Pushes whose runs failed before any job existed. These look like pull
  requests that were never approved to run; the API does not say.

## The reduced set

For each push with an own failure, any job that failed on it would have
flagged it. The reduced set is built greedily: each step adds the job that
flags the most not-yet-flagged pushes per runner minute, using the job's
median duration when it passes.

Only jobs seen in the last 14 days can be chosen, because the matrix changes.
A job that moved to another workflow under the same name is treated as one
job. A push that failed only in jobs not seen recently is counted, and no set
catches it.

That order fits the data it was chosen from, so the script also does a
held-out check. It chooses the order again from the early two thirds of the
window and scores it on the last third. Next to it is the best a set of the
same runner minutes could have done with the later pushes known in advance.

## Results: 27 September to 26 November 2026

From the run of 26 November 2026 over 60 days: 244 pushes from 151 branches.

| Pushes | Count | Share |
|---|---|---|
| With a failed job or run | 189 | 77% |
| Failed, but with no failure of its own | 95 | 39% |
| With a failure of its own | 94 | 39% |

| Failed jobs | Count | Share |
|---|---|---|
| Inherited | 363 | 48% |
| Shared | 56 | 7% |
| Setup | 17 | 2% |
| Retried | 9 | 1% |
| Own | 305 | 41% |

Of the 305 own failures, 123 had no specific error to compare.

A push ran about 605 runner minutes of jobs. The held-out check chose its
order from the 61 own-failing pushes before 6 November and scored it on the 33
after:

| Jobs in the set | Runner minutes | Later pushes caught | Best possible |
|---|---|---|---|
| 7 | 55 | 14 of 33 (42%) | 61% |
| 9 | 117 | 21 of 33 (64%) | 76% |
| 15 | 228 | 28 of 33 (85%) | 97% |
| 16 | 300 | 31 of 33 (94%) | 100% |

In short:

- Nearly six in ten failed jobs on pull requests were not caused by the pull
  request, and four in ten pushes failed for no reason of their own.
- About a fifth of the runner time caught about two thirds of the pushes that
  had a failure of their own. About half the runner time caught 94%.
- No job dominates. The job most often the only one to fail, `Ubuntu 20.04,
  gcc`, was the sole catcher on 10 of the 94 pushes.
- The largest shared causes looked like tool drift: an error raised inside
  pytest (22 failed jobs across 6 forks) and a CMake error (8 across 5).

The nine jobs at 117 minutes were three code checks, `Alpine, gcc`,
`Ubuntu 20.04, gcc`, both macOS jobs and two Windows jobs.

## Limits

- The held-out part is 33 pushes from one split. A share measured on 33 is
  uncertain by roughly 15 points either way.
- Master's state is matched by time, not by the commit a pull request is
  based on. A branch based on an old master can fail from a break that master
  has since fixed, and that failure counts as own.
- Pull requests from forks against release branches cannot be told apart
  from those against master, and are counted. There are few of them.
- Catching a push means at least one of its failing jobs is in the set. The
  contributor would still not see the other failures until the full run.
- Pushes to one pull request are not independent: one branch can supply
  several failing pushes with the same cause.
- Runner minutes are not waiting time. Queueing is not measured, and a job
  that fails early costs less than its median.
- For errors other than pytest failures, only the most specific line of the
  failed step is compared.

## Running

It needs the `gh` CLI, logged in. Nothing else.

```bash
python3 watch/gdal_ci_history.py --days 60 --out /tmp/history-out
python3 -m unittest discover -s watch
```

This writes `report.md` (also printed) and `data.json` to `--out`. Sixty days
takes roughly 2,500 API calls and an hour the first time, most of it reading
some 500 job logs. Job lists and the errors read from each log are
cached in `~/.cache/gdal-ci-history` (`--cache`), so a later run only fetches
what is new. Logs themselves are not kept.

To change the analysis without fetching anything, re-run it on saved data:

```bash
python3 watch/gdal_ci_history.py --data /tmp/history-out/data.json --out /tmp/again
```

`--train-share` sets how much of the window the held-out check chooses from
(default two thirds). `GDAL_READ_TOKEN` or `GH_TOKEN` is used for reads if
set.

Whatever comes of this that goes to GDAL is subject to its
[AI tool policy](https://github.com/OSGeo/gdal/blob/master/doc/source/community/ai_tool_policy.rst):
the report is evidence for a person to weigh and present, and any LLM help
with what is written there must be disclosed.
