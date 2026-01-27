# gdal-r-ci

Continuous integration for R packages against bleeding-edge GDAL.

This repository provides:

1. **Scheduled checks** - Fortnightly CI runs that test `sf`, `terra`, `gdalraster`, `vapour`, `gdalcubes`, and `stars` against the latest GDAL Docker image
2. **Reusable workflow** - A GitHub Action workflow that any R package can call to test against latest GDAL

## Why?

GDAL's C API occasionally changes in ways that require updates to R packages. For example, [sf PR #2576](https://github.com/r-spatial/sf/pull/2576) changed `GDALMetadata` to use `CSLConstList` for compatibility with newer GDAL versions.

Catching these issues early—before they hit CRAN—helps maintainers prepare fixes proactively.

## Scheduled Checks

The scheduled workflow runs on the 1st and 15th of each month at 02:00 UTC, testing these packages:

- [sf](https://github.com/r-spatial/sf)
- [terra](https://github.com/rspatial/terra)
- [gdalraster](https://github.com/firelab/gdalraster)
- [vapour](https://github.com/hypertidy/vapour)
- [gdalcubes](https://github.com/appelmar/gdalcubes)
- [stars](https://github.com/r-spatial/stars)

If any check fails, an issue is automatically created in this repository.

### Manual Trigger

You can manually trigger the scheduled workflow from the Actions tab:

1. Go to **Actions** → **Scheduled GDAL Compatibility Check**
2. Click **Run workflow**
3. Optionally specify packages (comma-separated) or leave as "all"

## Using the Reusable Workflow

Add this to your R package's `.github/workflows/` directory:

### Basic Usage

```yaml
# .github/workflows/check-gdal-latest.yml
name: Check GDAL Latest

on:
  schedule:
    - cron: '0 3 * * 0'  # Weekly on Sunday
  workflow_dispatch:

jobs:
  gdal-latest:
    uses: hypertidy/gdal-r-ci/.github/workflows/check-gdal-latest.yml@main
```

### With Options

```yaml
name: Check GDAL Latest

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  gdal-latest:
    uses: hypertidy/gdal-r-ci/.github/workflows/check-gdal-latest.yml@main
    with:
      # Git ref to checkout (branch, tag, SHA)
      ref: 'main'
      
      # Additional apt packages to install
      extra-deps: 'libnetcdf-dev libudunits2-dev'
      
      # Additional R packages to install
      r-extra-packages: 'tinytest, wk'
      
      # Additional R CMD check arguments
      check-args: '--no-manual --no-vignettes'
```

### Workflow Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `ref` | Git ref to checkout | Default branch |
| `extra-deps` | Space-separated apt packages | (none) |
| `r-extra-packages` | Comma-separated R packages | (none) |
| `check-args` | Arguments to R CMD check | `--no-manual` |

## Technical Details

### Environment

- **Container**: `ghcr.io/osgeo/gdal:ubuntu-full-latest` (Ubuntu Noble 24.04)
- **R**: Latest from CRAN repository
- **GDAL**: Whatever is in the `:latest` tag (typically nightly builds)

### R Installation

R is installed from the official CRAN Ubuntu repository following [CRAN's instructions](https://cran.r-project.org/bin/linux/ubuntu/):

```bash
wget -qO- https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc \
  | tee -a /etc/apt/trusted.gpg.d/cran_ubuntu_key.asc
add-apt-repository "deb https://cloud.r-project.org/bin/linux/ubuntu $(lsb_release -cs)-cran40/"
apt-get install -y r-base r-base-dev
```

### Pre-installed System Libraries

The workflow installs common dependencies needed by R geospatial packages:

- `libcurl4-openssl-dev`, `libssl-dev`, `libxml2-dev`
- `libfontconfig1-dev`, `libfreetype6-dev`, `libharfbuzz-dev`, `libfribidi-dev`
- `libpng-dev`, `libtiff5-dev`, `libjpeg-dev`
- `libsqlite3-dev`, `libudunits2-dev`, `libnetcdf-dev`
- `pandoc`, `qpdf`

## Adding More Packages

To add a package to the scheduled checks, edit `.github/workflows/scheduled-check.yml`:

1. Add to `ALL_PACKAGES` env variable
2. Add a case in the "Clone package repository" step

PRs welcome!

## Interpreting Failures

When a check fails, examine:

1. **00install.out** - Compilation errors (often API changes)
2. **00check.log** - Test failures
3. **testthat.Rout.fail** - Detailed test failures

Common GDAL API changes that cause issues:

- Const-correctness changes (like `CSLConstList`)
- New/removed function parameters
- Struct field changes
- Deprecated function removal

## Related Projects

- [r2u](https://github.com/eddelbuettel/r2u) - CRAN packages as Ubuntu binaries
- [rocker-org](https://github.com/rocker-org/rocker-versioned2) - R Docker images
- [osgeo/gdal](https://github.com/OSGeo/gdal) - GDAL source and Docker images

## License

MIT
