# gdal-r-ci

Continuous integration for R packages against bleeding-edge GDAL.

This repository provides:

1. **Scheduled checks** - Fortnightly CI runs that test
`gdalcubes`, `gdalraster`, `sf`, `terra`, and `vapour` against the latest GDAL
Docker image
2. **Reusable workflow** - A GitHub Action workflow that any R package can call
to test against latest GDAL

## Why?

GDAL's C API occasionally changes in ways that require updates to R packages.
For example, [sf PR #2576](https://github.com/r-spatial/sf/pull/2576) changed
`GDALMetadata` to use `CSLConstList` for compatibility with newer GDAL versions.

Catching these issues early—before they hit CRAN—helps maintainers prepare fixes proactively.

## Scheduled Checks

The scheduled workflow runs on the 1st and 15th of each month at 02:00 UTC, testing these packages:

- [gdalcubes](https://github.com/appelmar/gdalcubes)
- [gdalraster](https://github.com/firelab/gdalraster)
- [sf](https://github.com/r-spatial/sf)
- [terra](https://github.com/rspatial/terra)
- [vapour](https://github.com/hypertidy/vapour)

If any check fails, an issue is automatically created in this repository.

### Manual Trigger

(NOTE: we haven't actually tried this yet ...)

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
      extra-deps: 'libnetcdf-dev'
      
      # Additional R packages to install
      r-extra-packages: 'tinytest, wk'
      
      # Additional R CMD check arguments
      check-args: '--no-manual --ignore-vignettes'
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

- **Container**: `ghcr.io/osgeo/gdal:ubuntu-full-latest` (Ubuntu Noble 24.04 as at January 2026)
- **R**: Latest from CRAN repository
- **GDAL**: Whatever is in the `:latest` tag (typically nightly builds)

### The GDAL Docker Image and PROJ

The `ghcr.io/osgeo/gdal:ubuntu-full-latest` image has an interesting
architecture worth understanding:

**GDAL** is installed to system paths (`/usr/bin/gdalinfo`, `/usr/bin/gdal-config`, `/usr/lib/...`). This means `gdal-config --cflags` and `gdal-config --libs` work as expected, and R packages using GDAL link correctly.

**PROJ** is more complex. The image contains two PROJ installations:

1. **Internal PROJ** at `/usr/local/gdal-internal/` - This is a bleeding-edge
version (e.g., 9.8.0) that GDAL itself uses. Crucially, all symbols are renamed
to `internal_proj_*` (e.g., `internal_proj_context_create` instead of
`proj_context_create`) to avoid conflicts. The `proj` command-line tool comes
from here.

2. **System PROJ** at `/lib/x86_64-linux-gnu/` - This is Ubuntu's packaged version (e.g., 9.4.0) with standard symbol names. However, only `libproj.so.25` exists—no `libproj.so` symlink is provided.

This design lets GDAL use cutting-edge PROJ internally while avoiding symbol conflicts with system libraries. However, it creates challenges for R packages:

- Packages like `terra` and `sf` that link directly to PROJ expect standard `-lproj` with standard symbols
- The internal PROJ's renamed symbols won't resolve
- Without the `.so` symlink, the linker can't find system PROJ either

### Our Workaround

The workflow creates the missing symlink:

```bash
ln -sf /lib/x86_64-linux-gnu/libproj.so.25 /lib/x86_64-linux-gnu/libproj.so
ldconfig
```

This means R packages link against **system PROJ** (9.4.0) while **GDAL uses internal PROJ** (9.8.0). For our purposes—catching GDAL API changes—this is fine. We're testing GDAL compatibility, not PROJ compatibility.

### How R Packages Find GDAL and PROJ

Different packages use different detection strategies:

| Package | GDAL detection | PROJ detection |
|---------|---------------|----------------|
| gdalraster | `gdal-config` | `gdal-config` (doesn't link PROJ directly) |
| vapour | `gdal-config` | `gdal-config` (doesn't link PROJ directly) |
| sf | `gdal-config` | `pkg-config proj` |
| terra | `gdal-config` | `pkg-config proj` + hardcoded `-lproj` |

Packages that only use `gdal-config` (like `gdalraster` and `vapour`) work out
of the box. Packages that link PROJ directly need the symlink fix.

Note: `terra`'s configure script uses `pkg-config` to find PROJ's version and
include path, but then hardcodes `-lproj` rather than using `pkg-config --libs
proj`. This is why simply setting `PKG_CONFIG_PATH` to the internal PROJ doesn't
work—even though pkg-config would return `-linternalproj`, terra ignores that
and uses `-lproj` anyway.

### R Installation

R is installed from the official CRAN Ubuntu repository following [CRAN's
instructions](https://cran.r-project.org/bin/linux/ubuntu/):

```bash
wget -qO- https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc \
  | tee -a /etc/apt/trusted.gpg.d/cran_ubuntu_key.asc
add-apt-repository -y "deb https://cloud.r-project.org/bin/linux/ubuntu $(lsb_release -cs)-cran40/"
apt-get install -y r-base r-base-dev
```

### Pre-installed System Libraries

The workflow installs common dependencies needed by R geospatial packages:

- `pkg-config` (not in the GDAL image by default!)
- `cmake` (for packages that vendor dependencies)
- `libcurl4-openssl-dev`, `libssl-dev`, `libxml2-dev`
- `libfontconfig1-dev`, `libfreetype6-dev`, `libharfbuzz-dev`, `libfribidi-dev`
- `libpng-dev`, `libtiff-dev`, `libjpeg-dev`
- `libsqlite3-dev`, `libudunits2-dev`, `libnetcdf-dev`, `netcdf-bin`
- `libproj-dev`, `libgeos-dev` (for packages linking these directly)
- `libpq-dev`, `unixodbc-dev` (for database connectivity)
- `libabsl-dev` (for s2, used by sf)
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

### Example: CSLConstList

In GDAL 3.13+, `GetMetadata()` returns `CSLConstList` (a `const char* const*`)
instead of `char**`. Code like this fails:

```cpp
char **m = poDataset->GetMetadata();  // Error: invalid conversion from CSLConstList
```

The fix is straightforward:

```cpp
CSLConstList m = poDataset->GetMetadata();  // Or: const char* const* m = ...
```

## Debugging Locally

To reproduce the CI environment locally, start the container:

```bash
docker run -it --rm ghcr.io/osgeo/gdal:ubuntu-full-latest bash
```

Then inside the container, install system dependencies:

```bash
apt-get update -qq
apt-get install -y --no-install-recommends \
  software-properties-common dirmngr wget ca-certificates gnupg git \
  pkg-config lsb-release cmake \
  libcurl4-openssl-dev libssl-dev libxml2-dev \
  libfontconfig1-dev libfreetype6-dev libharfbuzz-dev libfribidi-dev \
  libpng-dev libtiff-dev libjpeg-dev \
  libsqlite3-dev libudunits2-dev libnetcdf-dev netcdf-bin \
  libproj-dev libgeos-dev libpq-dev unixodbc-dev \
  libabsl-dev \
  pandoc qpdf
```

Create the PROJ symlink (required for sf/terra):

```bash
ln -sf /lib/x86_64-linux-gnu/libproj.so.25 /lib/x86_64-linux-gnu/libproj.so
ldconfig
```

Install R from CRAN:

```bash
wget -qO- https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc \
  | tee -a /etc/apt/trusted.gpg.d/cran_ubuntu_key.asc
add-apt-repository -y "deb https://cloud.r-project.org/bin/linux/ubuntu $(lsb_release -cs)-cran40/"
apt-get update -qq
apt-get install -y --no-install-recommends r-base r-base-dev
```

Check versions:

```bash
gdalinfo --version            # GDAL (bleeding edge)
pkg-config --modversion proj  # System PROJ (used by R packages)
proj 2>&1 | head -1           # Internal PROJ (used by GDAL)
R --version | head -1
```

Clone and test a package (using gdalraster as example):

```bash
git clone --depth 1 https://github.com/firelab/gdalraster.git
cd gdalraster

Rscript -e "
  options(repos = c(CRAN = 'https://cloud.r-project.org'))
  install.packages(c('remotes', 'knitr', 'rmarkdown', 'testthat'))
  remotes::install_deps(dependencies = c('Depends', 'Imports', 'LinkingTo'), upgrade = 'never')
"

R CMD build .
_R_CHECK_FORCE_SUGGESTS_=false R CMD check --no-manual --ignore-vignettes *.tar.gz
```

For sf or terra, the same approach works. Note that we use:
- `dependencies = c('Depends', 'Imports', 'LinkingTo')` to skip Suggests (avoids circular sf/terra dependencies)
- `_R_CHECK_FORCE_SUGGESTS_=false` to allow check to proceed without suggested packages
- `--ignore-vignettes` to skip vignette building

## Related Projects

- [r2u](https://github.com/eddelbuettel/r2u) - CRAN packages as Ubuntu binaries
- [rocker-org](https://github.com/rocker-org/rocker-versioned2) - R Docker images
- [osgeo/gdal](https://github.com/OSGeo/gdal) - GDAL source and Docker images

## License

MIT
