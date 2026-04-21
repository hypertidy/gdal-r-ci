# Running R CMD check against gdal-r-full

The `gdal-r-full` image is set up for full `R CMD check --as-cran` including
PDF manual rendering. tinytex is pre-installed with the extra LaTeX packages
gdalraster and others need (`inconsolata`, `upquote`, `courier`, `helvetic`,
`hyperref`, `titling`, `framed`, `grfext`), and the `en_US.UTF-8` locale is
generated so there's no locale warning regardless of where the container runs.

## Quick start

```bash
docker pull ghcr.io/hypertidy/gdal-r-full:latest
docker run --rm -ti -v $(pwd):/pkg ghcr.io/hypertidy/gdal-r-full:latest bash
```

Inside the container:

```r
rcmdcheck::rcmdcheck(
    path       = "/pkg",
    build_args = c("--no-build-vignettes", "--no-manual"),
    args       = c("--no-manual", "--ignore-vignettes", "--as-cran")
)
```

For maximum CRAN fidelity including PDF manual and vignettes:

```r
rcmdcheck::rcmdcheck(path = "/pkg", args = "--as-cran")
```

## What you need to know

- `build_args` controls `R CMD build`; `args` controls `R CMD check`. These are
  often confused. Flags like `--no-manual` need to go in `args` to take effect
  during check.
- Use `rcmdcheck::rcmdcheck()` directly, not `devtools::check()`. devtools
  wraps rcmdcheck but sets `_R_CHECK_CRAN_INCOMING_REMOTE_=FALSE` and a few
  other env vars that suppress some `--as-cran` checks. For canary CI you want
  the unfiltered signal.
- `checkbashisms` warning is covered by the `devscripts` apt package (installed).
- `-mno-omit-leaf-frame-pointer` NOTE is R's own compiler flag, not the
  package — ignore it.

## Per-package notes

These packages have all been verified to pass full `R CMD check` inside
`gdal-r-full`, against both `:latest` (released GDAL) and `:dev` (GDAL master,
pending upstream changes). Each needs a few additional CRAN packages from
their Suggests that are not pre-installed in `gdal-r-full`.

### gdalraster

No extra deps needed — passes clean.

### terra

```r
remotes::install_cran(c('XML', 'deldir', 'leaflet'))
```

### sf

```bash
apt-get install -y unixodbc-dev
```

```r
remotes::install_cran(c(
    'blob', 'covr', 'ggplot2', 'maps', 'mapview', 'microbenchmark',
    'odbc', 'pbapply', 'pool', 'RPostgres', 'RPostgreSQL', 'RSQLite',
    'spatstat', 'spatstat.geom', 'spatstat.random', 'spatstat.linnet',
    'spatstat.utils', 'stars', 'tidyr', 'tmap'
))
```

### vapour

```r
remotes::install_cran('spelling')
```

### gdalcubes

Currently needs a fork branch to compile against GDAL master
(`CSLConstList` type change not yet merged upstream):

```r
system("git clone https://github.com/mdsumner/gdalcubes_R")
setwd("gdalcubes_R")
system("git checkout CSLConstList-gdal-3.1")
system("apt-get update && apt-get install -y cargo libavfilter-dev")
remotes::install_cran(c('stars', 'av', 'gifski', 'lubridate'))
rcmdcheck::rcmdcheck(
    build_args = c("--no-manual", "--no-build-vignettes"),
    args       = c("--no-manual")
)
```
