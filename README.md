# gdal-r-ci

CI infrastructure for R (and Python) geospatial packages against bleeding-edge GDAL.

GDAL, PROJ, and GEOS are built from source on plain `ubuntu:24.04` with standard
symbols — no internal PROJ, no dual-library setup. This means `R CMD check` runs
fully for all packages including sf and terra, with no `--no-test-load` workarounds.

## Images

Four images are published to GHCR, each in `:latest` (release) and `:dev` (GDAL HEAD) variants:

| Image | Contents | Use for |
|-------|----------|---------|
| `ghcr.io/hypertidy/gdal-system:latest` | GDAL + PROJ + GEOS + drivers | Base for custom images |
| `ghcr.io/hypertidy/gdal-r:latest` | + R + dev tooling | R package development |
| `ghcr.io/hypertidy/gdal-r-full:latest` | + gdalraster, sf, terra, vapour, gdalcubes | Package CI |
| `ghcr.io/hypertidy/gdal-python:latest` | + uv venv + rasterio, fiona, xarray, zarr... | R/Python interop |

```
gdal-system  →  gdal-r  →  gdal-r-full  →  gdal-python
```

The `:dev` variants track GDAL/PROJ/GEOS HEAD and rebuild daily — these are the canary.
The `:latest` variants track the latest releases and rebuild weekly.

## Quick start

```bash
# Interactive R session with latest stable GDAL
docker run --rm -ti ghcr.io/hypertidy/gdal-r-full:latest

# Check version alignment
docker run --rm ghcr.io/hypertidy/gdal-r-full:latest \
    Rscript /opt/scripts/check-r-versions.R

# Check Python stack
docker run --rm ghcr.io/hypertidy/gdal-python:latest \
    python /opt/scripts/check-python-versions.py
```

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
`:dev` only means an upstream GDAL API change that hasn't reached a release yet.

## Scheduled canary checks

Core packages are tested fortnightly against both release and dev images:

- [gdalraster](https://github.com/firelab/gdalraster)
- [sf](https://github.com/r-spatial/sf)
- [terra](https://github.com/rspatial/terra)
- [vapour](https://github.com/hypertidy/vapour)
- [gdalcubes](https://github.com/appelmar/gdalcubes)

Failures open issues automatically.

## Package lists

Packages installed in each image are explicit — no kitchen sink:

- [`config/r-packages-base.txt`](config/r-packages-base.txt) — base R dev tooling in `gdal-r`
- [`config/r-packages-required.txt`](config/r-packages-required.txt) — required geo packages in `gdal-r-full` (build fails if these fail)
- [`config/r-packages-optional.txt`](config/r-packages-optional.txt) — optional geo packages in `gdal-r-full` (failures logged, build continues)

## Why build from source?

The `osgeo/gdal` images build PROJ with renamed symbols (`-DPROJ_RENAME_SYMBOLS`)
so GDAL can use a bleeding-edge internal PROJ without disturbing the system PROJ.
This creates two PROJs in one container. R packages that link PROJ directly (sf,
terra) use the system PROJ; packages that go through GDAL headers use GDAL's
internal PROJ. When objects cross the boundary the process crashes — this is
[GDAL issue #13777](https://github.com/OSGeo/gdal/issues/13777).

We build GDAL ourselves against a single system PROJ at `/usr/local`, so there is
one `libproj.so` and everything links it. Full `R CMD check` works for all packages.

See [docs/library-alignment.md](docs/library-alignment.md) for full details.

## GEOS version capping

The release build caps GEOS to a version known to work with the resolved GDAL
release. GDAL 3.12.x was tested against GEOS ≤ 3.13.x; using GEOS 3.14.x with
GDAL 3.12.x introduces undefined symbols at runtime. `build-scripts/get-versions.sh`
handles this automatically — see the comments in that file for the cap table.

## Related


- [firelab/gdalraster](https://github.com/firelab/gdalraster) — primary test target
- [appelmar/gdalcubes](https://github.com/appelmar/gdalcubes) — optional GDAL package installed
- [r-spatial/sf](https://github.com/r-spatial/sf) — optional GDAL package installed
- [rspatial/terra](https://github.com/rspatial/terra) — optional GDAL package installed
- [hypertidy/vapour](https://github.com/hypertidy/vapour) — optional GDAL package installed
- [mdsumner/gdalcheck](https://github.com/mdsumner/gdalcheck) — reverse dependency checking (future)

## License

MIT
