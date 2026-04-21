# gdal-r-ci

CI infrastructure for R (and Python) geospatial packages against bleeding-edge GDAL.

GDAL, PROJ, and GEOS are built from source on plain `ubuntu:24.04` with standard
symbols — no internal PROJ, no dual-library setup. This means full `R CMD check`
including `--as-cran` and PDF manual rendering works for all packages including
sf and terra, with no `--no-test-load` workarounds.

## Images

Four images are published to GHCR, each in `:latest` (release) and `:dev`
(GDAL HEAD) variants:

| Image | Contents | Use for |
|-------|----------|---------|
| `ghcr.io/hypertidy/gdal-system:latest` | GDAL + PROJ + GEOS + drivers | Base for custom images |
| `ghcr.io/hypertidy/gdal-r:latest` | + R + dev tooling + tinytex | R package development |
| `ghcr.io/hypertidy/gdal-r-full:latest` | + gdalraster, sf, terra, vapour, gdalcubes | Package CI |
| `ghcr.io/hypertidy/gdal-python:latest` | + uv venv + rasterio, fiona, xarray, zarr... | R/Python interop |

```
gdal-system  →  gdal-r  →  gdal-r-full  →  gdal-python
```

The `:dev` variants track GDAL HEAD + latest released PROJ/GEOS, rebuilt daily —
these are the canary. The `:latest` variants track the latest releases of all three,
rebuilt weekly.

## Quick start

```bash
# Interactive R session with latest stable GDAL
docker run --rm -ti ghcr.io/hypertidy/gdal-r-full:latest

# Check version alignment
docker run --rm ghcr.io/hypertidy/gdal-r-full:latest \
    Rscript /opt/scripts/check-r-versions.R

# Run R CMD check on a local package
docker run --rm -v $(pwd):/pkg ghcr.io/hypertidy/gdal-r-full:latest \
    Rscript -e 'rcmdcheck::rcmdcheck("/pkg", args = "--as-cran")'
```

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

R packages installed in each image are explicit — no kitchen sink:

- [`config/r-packages-base.txt`](config/r-packages-base.txt) — base R dev tooling in `gdal-r`
- [`config/r-packages-required.txt`](config/r-packages-required.txt) — required geo packages in `gdal-r-full` (build fails if these fail, for `:latest` only — see below)
- [`config/r-packages-optional.txt`](config/r-packages-optional.txt) — optional geo packages in `gdal-r-full` (failures logged, build continues)

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

## GEOS version capping

The release build caps GEOS to a version known to work with the resolved GDAL
release. GDAL 3.12.x was tested against GEOS ≤ 3.13.x; using GEOS 3.14.x with
GDAL 3.12.x introduces undefined symbols at runtime. `build-scripts/get-versions.sh`
handles this automatically — see the comments in that file for the cap table.

For `:dev`, GDAL is always `master` but PROJ and GEOS use the latest releases
(not their `main` branches). We're testing GDAL API changes, not PROJ/GEOS dev,
and keeping PROJ/GEOS at releases ensures R packages can actually build.

## Ongoing maintenance

The infrastructure is designed to run itself:

- `build-gdal-system.yml` runs weekly for release, daily for dev
- Each image only rebuilds if its upstream digest changed, using
  `repository_dispatch` to cascade through `gdal-system → gdal-r → gdal-r-full → gdal-python`
- `scheduled-canary.yml` runs fortnightly, opens issues on failure

When something needs human attention:

- **`:dev` fails, `:latest` passes** — upstream GDAL API change. File issue against the package (e.g. terra's `gdal_algs.cpp` on `CSLConstList` type changes).
- **`:latest` fails** — regression in a released GDAL. Rare and urgent. Check the canary logs to identify whether it's a package, GDAL, or our build infrastructure.
- **Both fail** — probably our infrastructure. Check the build logs for the system layer, run `no_cache: true` rebuild if needed.
- **Version alignment warning** — should never happen on `:latest` (build-time check is strict). On `:dev` it's logged and expected during upstream transitions.

### Forcing a full rebuild

If something looks stale, trigger `build-gdal-system.yml` manually with
`no_cache: true, variant: both`. The `CACHE_DATE` ARG guarantees cache busting
for the system layer; downstream GHA caches fall through automatically since
their base image digest will have changed.

## Related

- [firelab/gdalraster](https://github.com/firelab/gdalraster) — primary test target
- [r-spatial/sf](https://github.com/r-spatial/sf)
- [rspatial/terra](https://github.com/rspatial/terra)
- [hypertidy/vapour](https://github.com/hypertidy/vapour)
- [appelmar/gdalcubes](https://github.com/appelmar/gdalcubes)
- [mdsumner/gdalcheck](https://github.com/mdsumner/gdalcheck) — reverse dependency checking built on these images

## License

MIT
