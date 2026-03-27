# Library version alignment

## The core principle

Every R package that links GDAL, PROJ, or GEOS must link the **exact same version**
of each library. Version mismatches cause silent data corruption, ABI crashes,
and subtle behavioural differences that are difficult to debug.

## Why we build from source (not osgeo/gdal images)

The upstream `osgeo/gdal:ubuntu-full` images build PROJ with renamed symbols
(`-DPROJ_RENAME_SYMBOLS -DPROJ_INTERNAL_CPP_NAMESPACE`). This means GDAL
uses an *internal* PROJ whose symbols are prefixed `internal_proj_*`, isolated
from any system PROJ. The image also installs Ubuntu's system PROJ alongside it.

That architecture works fine for GDAL itself, but it creates two PROJs in one
container. R packages that link PROJ directly (sf, terra) use the system PROJ;
packages that go through GDAL's headers (gdalraster, vapour) report GDAL's
internal PROJ version. When objects from both cross a boundary — or when the
dynamic linker resolves the same symbol from two DSOs — you get the crash that
upstream tracks as [GDAL issue #13777](https://github.com/OSGeo/gdal/issues/13777).

The previous gdal-r-ci worked around this with `--no-test-load` and by skipping
`R CMD check` for sf and terra entirely. That defeats the purpose of canary testing.

## What we do instead

We build GDAL ourselves from `ubuntu:24.04`, linking it against the same PROJ
we install to `/usr/local` without any symbol renaming. The result:

```
/usr/local/lib/libproj.so    ← one PROJ, standard symbols
/usr/local/lib/libgdal.so    ← links libproj.so above
/usr/local/lib/libgeos.so    ← one GEOS

R packages (sf, terra, vapour, gdalraster)
  link: /usr/local/lib/libproj.so   ← same library
  link: /usr/local/lib/libgdal.so   ← same library
  link: /usr/local/lib/libgeos.so   ← same library
```

Full `R CMD check` works for all packages. The version alignment check
(`scripts/check-r-versions.R`) is now strict — a PROJ mismatch between packages
is a real environment problem, not an expected artefact.

## Why we don't use pak / r2u / RSPM binaries

- **r2u** provides CRAN packages compiled against Ubuntu's system GDAL (~3.4 on 22.04,
  ~3.8 on 24.04). Those binaries will crash or silently misbehave when loaded in
  a container with a different GDAL version.
- **pak** with binary fallback has the same risk — a binary fetched from RSPM was
  compiled against whatever GDAL was current at RSPM's build time.

All R packages in these images are compiled from source in the same environment.
This is slower; that is why we pre-build images weekly and cache them in GHCR.

## Build order

```
ubuntu:24.04
  apt: build tools, format libraries (HDF5, NetCDF, Arrow, etc.)
  → GEOS from source  → /usr/local
  → PROJ from source  → /usr/local  (standard symbols, projsync grids)
  → KEA  from source  → /usr/local
  → GDAL from source  → /usr/local  (links /usr/local/lib/libproj.so)
  = gdal-r-base

  gdal-r-base
    → R from CRAN Ubuntu repo
    → base R packages (Rcpp, cpp11, wk, s2, remotes, testthat …)
    = gdal-r

    gdal-r
      → gdalraster (required, GitHub HEAD)
      → sf, terra, vapour, gdalcubes (optional, GitHub HEAD)
      → version alignment check (strict)
      = gdal-r-full
```

## Version check

`scripts/check-r-versions.R` queries each installed package for the GDAL/PROJ/GEOS
version it was linked against and compares with the system ground truth from
`gdal-config --version`, `pkg-config --modversion proj`, and `geos-config --version`.

With a single PROJ, all package-reported versions should match the system version
exactly. The script exits non-zero if they do not, failing the Docker build.

Run it anytime:

```bash
docker run --rm ghcr.io/hypertidy/gdal-r-full:latest \
    Rscript /opt/scripts/check-r-versions.R
```

## Image variants

| Tag | GDAL source | Rebuild schedule | Purpose |
|-----|-------------|-----------------|---------|
| `:latest` | latest release tarball | weekly (Mon 02:00 UTC) | stable CI for consumer packages |
| `:dev` | OSGeo/gdal HEAD | daily (03:00 UTC) | canary — catches API breaks before release |
