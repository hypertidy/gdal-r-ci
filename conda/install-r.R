# install-r.R ENV -- build the source R packages for a gdal-conda environment.
#
#   release: vapour (not yet on conda-forge); the rest are conda binaries
#   dev:     gdalraster, sf, terra, vapour from GitHub HEAD, compiled against
#            the environment's GDAL master
#
# Packages go into the environment's own R library. Missing dependencies,
# which should be none given pixi.toml, come from CRAN source.

args <- commandArgs(trailingOnly = TRUE)
env <- if (length(args)) args[[1]] else "release"

pkgs <- switch(env,
  release = c("hypertidy/vapour"),
  dev = c("firelab/gdalraster", "r-spatial/sf", "rspatial/terra",
          "hypertidy/vapour"),
  stop("unknown environment: ", env)
)

options(repos = c(CRAN = "https://cloud.r-project.org"),
        Ncpus = max(1L, parallel::detectCores()))

cat("R library:", .libPaths()[1], "\n")
cat("gdal-config:", system("gdal-config --version", intern = TRUE), "\n")

remotes::install_github(pkgs, upgrade = "never", dependencies = NA,
                        build_vignettes = FALSE, force = TRUE)

# Fail loudly if anything did not install or load.
for (p in basename(pkgs)) {
  suppressPackageStartupMessages(library(p, character.only = TRUE))
  cat(sprintf("%-11s %s\n", p, as.character(packageVersion(p))))
}
