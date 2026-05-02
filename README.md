# gdal-r-ci

CI infrastructure for R (and Python) geospatial packages against bleeding-edge GDAL.

GDAL, PROJ, and GEOS are built from source on plain `ubuntu:24.04` with standard
symbols — no internal PROJ, no dual-library setup. This means full `R CMD check`
including `--as-cran` and PDF manual rendering works for all packages including
sf and terra, with no `--no-test-load` workarounds. The same chain produces a
single working environment for R-and-Python interop where reticulate, rasterio,
sf, terra, gdalraster, vapour, and the osgeo Python bindings all link the same
GDAL, the same PROJ, the same GEOS, and the same numpy ABI.

See a short demonstration of use of the `gdal-r-python` image here: https://gist.github.com/mdsumner/1b38b300f7dc6e0a8cdfa3cd8fbc84ce

## Images

Five images are published to GHCR. The first four publish `:latest` (release)
and `:dev` (GDAL HEAD) variants; the leaf publishes `:latest` only.

| Image | Contents | Use for |
|-------|----------|---------|
| `ghcr.io/hypertidy/gdal-system` | GDAL + PROJ + GEOS + drivers + uv venv with numpy 2.x | Base for custom images |
| `ghcr.io/hypertidy/gdal-r` | + R + dev tooling + tinytex | R package development |
| `ghcr.io/hypertidy/gdal-r-full` | + gdalraster, sf, terra, vapour, gdalcubes | Package CI |
| `ghcr.io/hypertidy/gdal-r-python` | + rasterio, fiona, xarray, zarr, kerchunk, virtualizarr… | R/Python interop |
| `ghcr.io/hypertidy/gdal-r-python-extras` | + R kitchen sink (hypertidy stack, arrow, targets, dev tooling) | Workbench / interactive |

```
gdal-system  →  gdal-r  →  gdal-r-full  →  gdal-r-python  →  gdal-r-python-extras
```

The `:dev` variants track GDAL HEAD + latest released PROJ/GEOS, rebuilt daily —
these are the canary. The `:latest` variants track the latest releases of all
three, rebuilt weekly. `gdal-r-python-extras` has no `:dev` variant by design;
for bleeding-edge work, base on `gdal-r-python:dev` directly and overlay
packages via a writable `R_LIBS_USER` mount at runtime.

### gdal-system

The base layer. Builds GEOS, PROJ, and GDAL from source against a single
`/usr/local`. Also creates the uv-managed Python venv at `/opt/gdal-py` with
numpy 2.x, *before* GDAL builds — so GDAL's Python bindings link against the
venv's numpy ABI from the start. This means every downstream layer inherits a
single, internally-consistent numpy 2.x environment with the osgeo bindings
correctly bound. The venv lives at every subsequent layer; downstream layers
just install packages into it.

### gdal-r-python

R-and-Python, not Python-only — the new name reflects that (renamed from
`gdal-python`). The venv inherited from `gdal-system` already contains numpy
and the osgeo bindings. This layer adds Python geospatial packages on top:
source-built and linking the system GDAL/PROJ/GEOS:
`rasterio`, `fiona`, `pyogrio`, `shapely`, `pyproj`, `geopandas`, `odc-geo`,
`rioxarray`. Everything else takes wheels. reticulate is installed and pinned
to `/opt/gdal-py/bin/python` via `RETICULATE_PYTHON`; `py_require()` calls
augment the existing venv rather than spawning ephemeral environments.

### gdal-r-python-extras

Adds the everyday-R kitchen sink on top of `gdal-r-python` via
[`scripts/install-extras.R`](scripts/install-extras.R). Spatial and hypertidy
CRAN packages are source-built; everything else takes Posit Public Package
Manager binaries. The set is curated rather than exhaustive — anything WIP or
rarely reached for stays out and is installed on demand into a writable overlay.

## Quick start

```bash
# Interactive R session with latest stable GDAL
docker run --rm -ti ghcr.io/hypertidy/gdal-r-full:latest

# Interactive R + Python (reticulate works out of the box)
docker run --rm -ti ghcr.io/hypertidy/gdal-r-python:latest

# Full workbench (R kitchen sink + Python)
docker run --rm -ti ghcr.io/hypertidy/gdal-r-python-extras:latest

# Check version alignment
docker run --rm ghcr.io/hypertidy/gdal-r-full:latest \
    Rscript /opt/scripts/check-r-versions.R

# Run R CMD check on a local package
docker run --rm -v $(pwd):/pkg ghcr.io/hypertidy/gdal-r-full:latest \
    Rscript -e 'rcmdcheck::rcmdcheck("/pkg", args = "--as-cran")'
```

All images use `CMD ["bash"]` so `docker run -ti` lands you in a shell with the
full toolchain on `PATH`. R, Python, and CLI tools are all available
interactively without picking a host language up front. A short banner prints
on entry showing the GDAL/PROJ/GEOS/R/Python versions baked into that specific
image; the banner links back to the relevant section of this README.

See [docs/rcmd-check-notes.md](docs/rcmd-check-notes.md) for check args and
per-package notes (extra deps needed for sf, terra, etc).

## Reusable workflow for package CI

Add to your package's `.github/workflows/`:

```yaml
name: Check against GDAL latest

on:
  schedule:
    - cron: '0 3 * * 0'
  workflow_dispatch:

jobs:
  gdal-check:
    uses: hypertidy/gdal-r-ci/.github/workflows/check-gdal-release.yml@main
```

This runs `R CMD check` against both `:latest` and `:dev` images. A failure in
`:dev` only means an upstream GDAL API change that hasn't reached a release yet —
file it upstream, not against your package.

## Scheduled canary checks

Core packages are tested fortnightly against both release and dev images:

- [gdalraster](https://github.com/firelab/gdalraster) — primary test target
- [sf](https://github.com/r-spatial/sf)
- [terra](https://github.com/rspatial/terra)
- [vapour](https://github.com/hypertidy/vapour)
- [gdalcubes](https://github.com/appelmar/gdalcubes)

Failures open issues automatically in this repo.

## Package lists

Package contents are explicit — no kitchen sink in the CI-contractual layers.

- [`config/r-packages-base.txt`](config/r-packages-base.txt) — base R dev tooling in `gdal-r`
- [`config/r-packages-required.txt`](config/r-packages-required.txt) — required geo packages in `gdal-r-full` (build fails if these fail, for `:latest` only)
- [`config/r-packages-optional.txt`](config/r-packages-optional.txt) — optional geo packages in `gdal-r-full` (failures logged, build continues)
- [`scripts/install-extras.R`](scripts/install-extras.R) — full curated R set installed in `gdal-r-python-extras` (CRAN spatial, hypertidy stack, AAD pipelines, arrow/duckdb/targets, dev tooling)

For `:dev`, failures in required packages are logged but don't fail the build —
gdalraster failing against GDAL master is canary information worth publishing
as an image, not a reason to withhold the optional packages too.

## Why build from source?

The `osgeo/gdal` images build PROJ with renamed symbols (`-DPROJ_RENAME_SYMBOLS`)
so GDAL can use a bleeding-edge internal PROJ without disturbing the system PROJ.
This creates two PROJs in one container. R packages that link PROJ directly (sf,
terra) use the system PROJ; packages that go through GDAL's headers (gdalraster,
vapour) report GDAL's internal PROJ version. When objects cross the boundary the
process crashes — this is
[GDAL issue #13777](https://github.com/OSGeo/gdal/issues/13777).

We build GDAL ourselves against a single system PROJ at `/usr/local`, so there is
one `libproj.so` and everything links it. Full `R CMD check` works for all packages.

Spatialite is also built from source — the apt package is compiled against the
system GEOS 3.12.1, and its headers at `/usr/include/geos_c.h` conflict with our
`/usr/local/include/geos_c.h` (3.13.1+). Building spatialite against our GEOS
keeps the entire stack at one consistent version.

See [docs/library-alignment.md](docs/library-alignment.md) for full details.

## One library, one ABI

Three classes of duplicate-library bug have surfaced and been closed in this
chain. They have different specifics but share a structure:

| Bug | Cause | Fix |
|-----|-------|-----|
| Dual PROJ | osgeo/gdal images embed PROJ with renamed symbols | Single `/usr/local` PROJ; build GDAL against it |
| Dual GDAL | pak's `pkg_install()` resolves R packages' GDAL sysreq via apt | `options(pkg.sysreqs = FALSE)` — apt is forbidden, /usr/local satisfies |
| Dual numpy | apt's python3-numpy is 1.x; venv installs 2.x; osgeo bindings linked against 1.x | Venv created in gdal-system; numpy 2.x installed *before* GDAL bindings build |

Each had the same structural shape: two libraries claiming to be the same
library, in one process, with code linked against either one randomly.
The solution is always the same in shape — pick one source of truth, rebuild
everything against it, eliminate the alternatives. Whether it's `/usr/local`
for system libs, `pkg.sysreqs=FALSE` for pak, or the up-front venv for numpy,
the principle is identity-not-shadowing.

## GEOS version capping

The release build caps GEOS to a version known to work with the resolved GDAL
release. GDAL 3.12.x was tested against GEOS ≤ 3.13.x; using GEOS 3.14.x with
GDAL 3.12.x introduces undefined symbols at runtime. `build-scripts/get-versions.sh`
handles this automatically — see the comments in that file for the cap table.

For `:dev`, GDAL is always `master` but PROJ and GEOS use the latest releases
(not their `main` branches). We're testing GDAL API changes, not PROJ/GEOS dev,
and keeping PROJ/GEOS at releases ensures R packages can actually build.

## Build hygiene

A few patterns make rebuilds fast and image sizes manageable:

- **Single-numpy-ABI from layer 1.** The Python venv at `/opt/gdal-py` is
  created in `gdal-system` with numpy 2.x installed *before* GDAL builds. GDAL's
  Python bindings link against this numpy from the start. Every downstream layer
  inherits the same venv; no `--system-site-packages`, no post-hoc rebuilds, no
  ABI ambiguity.
- **uv with BuildKit cache mounts.** `--mount=type=cache,target=/root/.cache/uv`
  keeps wheels out of image layers entirely. Cold builds populate the cache;
  warm rebuilds finish in minutes. uv is the only pip-shaped tool in the chain
  — no apt python3-pip, no `--break-system-packages` shenanigans.
- **`PYTHONDONTWRITEBYTECODE=1`** plus a `__pycache__` sweep at the end of every
  install RUN. Avoids hundreds of MB of `.pyc` accumulation across layers.
- **Source vs binary policy is explicit.** Spatial Python packages that link
  GDAL/PROJ/GEOS are `--no-binary`; everything else takes wheels. Spatial R
  packages and hypertidy CRAN are installed via `pak::pkg_install("...?source")`
  with `pkg.sysreqs = FALSE`; everything else takes PPM binaries.
- **CMake unity build** for GDAL halves compile time on the cmake step.

## Local development

For iterating on Dockerfile or build-script changes without burning CI minutes,
[`test/local-test.sh`](test/local-test.sh) builds `gdal-system` locally and runs
sanity checks on the result. Cache-friendly: subsequent runs reuse layers up to
the first changed line. On a 32-core machine the first build is around 15
minutes; warm rebuilds for changes near the bottom of the Dockerfile are
seconds.

```bash
bash test/local-test.sh                  # release variant
bash test/local-test.sh dev              # dev variant
NCPUS=16 bash test/local-test.sh         # cap parallelism
```

To debug a failing build interactively, comment out the failing RUN step
temporarily, build to that point, then drop in:

```bash
docker run -ti --rm -v $(pwd)/build-scripts:/build-scripts \
    gdal-system:local bash
```

The `-v` mount lets you edit the build scripts on the host while iterating
inside the container.

## Ongoing maintenance

The infrastructure is designed to run itself:

- `build-gdal-system.yml` runs weekly for release, daily for dev
- Each image only rebuilds if its upstream digest changed, using
  `repository_dispatch` to cascade through
  `gdal-system → gdal-r → gdal-r-full → gdal-r-python → gdal-r-python-extras`
- The cascade to `gdal-r-python-extras` only fires for the release variant,
  since extras has no `:dev` tag
- `scheduled-canary.yml` runs fortnightly, opens issues on failure

When something needs human attention:

- **`:dev` fails, `:latest` passes** — upstream GDAL API change. File issue
  against the package (e.g. terra's `gdal_algs.cpp` on `CSLConstList` type
  changes; gdalcubes's parallel signature changes).
- **`:latest` fails** — regression in a released GDAL. Rare and urgent. Check
  the canary logs to identify whether it's a package, GDAL, or our build
  infrastructure.
- **Both fail** — probably our infrastructure. Check the build logs for the
  system layer, run `no_cache: true` rebuild if needed.
- **Version alignment warning** — should never happen on `:latest` (build-time
  check is strict). On `:dev` it's logged and expected during upstream
  transitions. Note: GDAL on `:dev` may report a version label like `3.13.0dev`
  via `gdal-config` and `3.13.0beta2` via `GDALVersionInfo` — the alignment
  script normalises both to `3.13.0` so cosmetic suffix differences don't
  trigger false alarms.
- **Suggests-related test or example failures** in canary results that don't
  match a GDAL story — these are real bugs in the canaried packages, surfaced
  by the deliberately-Suggests-minimal canary environment. File upstream.
  The canary's narrowness is itself a feature; see
  [`docs/r-cmd-check-suggests-and-ordering.md`](docs/r-cmd-check-suggests-and-ordering.md).

### Forcing a full rebuild

If something looks stale, trigger `build-gdal-system.yml` manually with
`no_cache: true, variant: both`. The `CACHE_DATE` ARG guarantees cache busting
for the system layer; downstream GHA caches fall through automatically since
their base image digest will have changed.

### Overlaying packages at runtime

`gdal-r-python-extras` is curated, not exhaustive. For packages that aren't
baked — anything WIP, or just one-off experiments — install into a writable
library at runtime instead of rebuilding the image:

```bash
docker run --rm -ti \
  -v $HOME/R-overlay:/opt/r-overlay \
  -e R_LIBS_USER=/opt/r-overlay \
  ghcr.io/hypertidy/gdal-r-python-extras:latest
```

Inside, `pak::pkg_install("hypertidy/zaro", lib = "/opt/r-overlay")` installs to
the bind-mounted directory, which persists across container runs. The same
pattern works on Singularity without bind-mounts because `$HOME` is writable
by default. Use the writable-overlay path for hypertidy WIP packages
(`zaro`, `shearwater`, `cloudcache`, `ndr`, `gdalcheck`) where rebuild cadence
matters more than discoverability.

For Python packages, `uv pip install --python /opt/gdal-py/bin/python <pkg>`
adds to the inherited venv. Inside R, `reticulate::py_require("<pkg>")` does
the same via reticulate's bridge — `RETICULATE_PYTHON` is pinned so additions
land in `/opt/gdal-py`, not in an ephemeral venv.

## Related

- [firelab/gdalraster](https://github.com/firelab/gdalraster) — primary test target
- [r-spatial/sf](https://github.com/r-spatial/sf)
- [rspatial/terra](https://github.com/rspatial/terra)
- [hypertidy/vapour](https://github.com/hypertidy/vapour)
- [appelmar/gdalcubes](https://github.com/appelmar/gdalcubes)
- [mdsumner/gdalcheck](https://github.com/mdsumner/gdalcheck) — reverse dependency checking built on these images

## License

MIT
