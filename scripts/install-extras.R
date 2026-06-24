#!/usr/bin/env Rscript
# install-extras.R
#
# Kitchen-sink R packages installed on top of gdal-r-full to produce
# gdal-r-extras. Run inside the Docker build.
#
# Policy:
#   * Spatial + hypertidy CRAN packages are installed from source so they
#     link against the custom GDAL / PROJ / GEOS already in the image.
#   * Everything else prefers Posit Public Package Manager binaries for
#     speed; this is the difference between a 15-minute build and a
#     90-minute build.
#   * Hypertidy WIP, AAD, and other GitHub-only packages are pulled from
#     r-universe (preferred) or GitHub (fallback) via pak.

# ---- 0. Bootstrap pak --------------------------------------------------------
# pak is the install driver. Faster, parallel, real solver, handles sysreqs,
# and respects the source-vs-binary qualifier we use below.
if (!requireNamespace("pak", quietly = TRUE)) {
  install.packages(
    "pak",
    repos = sprintf(
      "https://r-lib.github.io/p/pak/stable/%s/%s/%s",
      .Platform$pkgType, R.Version()$os, R.Version()$arch
    )
  )
}

options(
  Ncpus = max(1L, parallel::detectCores() - 1L),
  pak.no_extra_messages = TRUE,
  install.packages.check.source = "no",
  pkg.show_progress = TRUE
)

Sys.setenv(R_PROGRESSR_ENABLE = "false")
Sys.setenv(PKG_PROGRESS_BARS = "false")

# ---- 1. Repositories ---------------------------------------------------------
PPM        <- "https://packagemanager.posit.co/cran/__linux__/noble/latest"
CRAN       <- "https://cloud.r-project.org"
HYPERTIDY  <- "https://hypertidy.r-universe.dev"
ROPENSCI   <- "https://ropensci.r-universe.dev"
AAD        <- "https://australianantarcticdivision.r-universe.dev"

# ---- 2. Package sets ---------------------------------------------------------

# 2a. Spatial — MUST be source-built against this image's GDAL stack.
spatial <- c(
  "sf", "terra", "stars", "lwgeom", "wk", "s2", "geos", "geoarrow",
  "gdalraster", "exactextractr", "fasterize",
  "pizzarr", "rstac", "rsi", "tidync", "zarr"
)

# 2b. Hypertidy CRAN — source so they pick up the image's GDAL where relevant.
hypertidy_cran <- c(
  "vaster", "tissot", "geographiclib", "wkpool", "decido",
  "silicate", "sfheaders", "graticule", "quadmesh", "spex",
  "gibble", "palr", "affinity", "rbgm", "trip",
  "RTriangle", "polyclip", "geometries", "terrainmeshr", "sooty"
)

# 2c. Cloud / Arrow / Parquet / DuckDB.
cloud <- c(
  "arrow", "nanoarrow", "duckdb", "duckdbfs", "duckplyr",
  "adbcdrivermanager", "redux"
)

# 2d. Object stores & HTTP.
http <- c(
  "httr2", "curl", "aws.s3", "aws.signature", "AzureStor",
  "paws.storage", "minioclient", "piggyback"
)

# 2e. Targets & parallelism.
pipeline <- c(
  "targets", "tarchetypes", "crew", "crew.cluster",
  "mirai", "future", "furrr", "future.batchtools",
  "multidplyr", "rslurm", "carrier"
)

# 2f. Tidy core (deliberately à la carte; no `tidyverse` meta).
tidy <- c(
  "dplyr", "tidyr", "purrr", "stringr", "readr", "tibble",
  "lubridate", "hms", "glue", "fs", "vctrs", "rlang",
  "ggplot2", "leaflet", "DBI", "RSQLite",
  "xml2", "jsonlite", "yaml", "base64enc", "jpeg",
  "qs2", "fst", "archive"
)

# 2g. Dev tooling.
dev <- c(
  "devtools", "usethis", "roxygen2", "testthat", "tinytest",
  "rcmdcheck", "urlchecker", "lintr", "styler", "pkgdown",
  "callr", "processx", "withr", "sessioninfo", "desc", "brio",
  "cli", "digest", "knitr", "rmarkdown", "quarto",
  "languageserver", "httpgd", "bench", "lobstr",
  "Rcpp", "cpp11", "rextendr"
)

# 2h. Hypertidy WIP — r-universe nightly builds preferred.
hypertidy_dev <- c(
  "hypertidy/vapour",
  "hypertidy/grout",
  "hypertidy/ximage",
  "hypertidy/sds",
  "hypertidy/dsn",
  "hypertidy/controlledburn"
)

# 2i. AAD / data pipeline ecosystem.
aad <- c(
  #"AustralianAntarcticDivision/raadfiles",
  #"AustralianAntarcticDivision/raadtools",
  "AustralianAntarcticDivision/blueant",
  "ropensci/bowerbird",
  "mdsumner/bluelink"
)

# 2j. Other GitHub-only.
gh_other <- c(
  "r-lib/revdepcheck",
  "coolbutuseless/zstdlite"
)

# ---- 3. Phase A: spatial + hypertidy_cran, source-only -----------------------
# `?source` qualifier forces pak to build from source even if PPM has a binary.
message("\n== Phase A: spatial + hypertidy CRAN (source) ==")
options(repos = c(CRAN = CRAN))

# Tell pak NOT to apt-install system deps. /usr/local has GDAL/PROJ/GEOS
# built from source; Ubuntu's libgdal-dev would shadow them
options(
  pkg.sysreqs = FALSE,
  pkg.sysreqs_update = FALSE,
  pkg.sysreqs_db_update = FALSE
)
Sys.setenv(PKG_SYSREQS = "false")



# cat("GITHUB_PAT in R:", nchar(Sys.getenv("GITHUB_PAT")), "\n")
# cat("GITHUB_TOKEN in R:", nchar(Sys.getenv("GITHUB_TOKEN")), "\n")
#
# # Verify PAT reaches pak's subprocess
# callr::r(function() {
#   cat("PAT in subprocess:", nchar(Sys.getenv("GITHUB_PAT")), "\n")
#   cat("TOKEN in subprocess:", nchar(Sys.getenv("GITHUB_TOKEN")), "\n")
# })

# pat <- trimws(readLines("/run/secrets/gh_pat", warn = FALSE))
# Sys.setenv(GITHUB_PAT = pat, GITHUB_TOKEN = pat)
# writeLines(
#   c(paste0("GITHUB_PAT=", pat), paste0("GITHUB_TOKEN=", pat)),
#   file.path(Sys.getenv("HOME"), ".Renviron")
# )

pak::pkg_install(
  paste0(c(spatial, hypertidy_cran), "?source"),
  ask = FALSE,
  upgrade = FALSE
)


# ---- 4. Phase B: everything else, PPM binaries OK ----------------------------
message("\n== Phase B: cloud / http / pipeline / tidy / dev (binary) ==")
options(repos = c(PPM = PPM, CRAN = CRAN))

pak::pkg_install(
  c(cloud, http, pipeline, tidy, dev),
  ask = FALSE,
  upgrade = FALSE
)

# ---- 5. Phase C: r-universe / GitHub overlays --------------------------------
message("\n== Phase C: hypertidy WIP + AAD + other GitHub ==")
# options(repos = c(
#   hypertidy = HYPERTIDY,
#   ropensci  = ROPENSCI,
#   aad       = AAD,
#   PPM       = PPM,
#   CRAN      = CRAN
# ))

# pak::pkg_install(
#   c(hypertidy_dev, aad, gh_other),
#   ask = FALSE,
#   upgrade = FALSE
# )
remotes::install_github(c(hypertidy_dev, aad, gh_other), upgrade = FALSE)


## --- bioconductor

if (!require("BiocManager", quietly = TRUE)) {
    try(install.packages("BiocManager"))
}
try(BiocManager::install(c("rhdf5filters", "Rhdf5lib"), update = FALSE))
system("git clone --branch remote-chunk-refs https://github.com/mdsumner/rhdf5")
try(remotes::install_local("rhdf5"))
system("rm -rf rhdf5")

# ---- 6. Sanity check ---------------------------------------------------------
# Reuse the shared alignment script. With pkg.sysreqs=FALSE we trust source
# builds picked up /usr/local; this confirms it. The shared script handles
# version-suffix normalisation and the PROJ-via-headers nuance — see comments
# at the top of check-r-versions.R.
message("\n== Sanity check: GDAL alignment across packages ==")
source("/opt/scripts/check-r-versions.R")

message("\n== Done ==")
