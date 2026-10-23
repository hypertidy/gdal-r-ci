#!/usr/bin/env Rscript
# install-mesh.R
#
# Mesh packages installed on top of gdal-r-full to produce gdal-r-mesh.
# Reads /tmp/r-packages-mesh.txt; every entry is required, in order.
#
# GitHub entries are installed with remotes and upgrade = "never", so the
# GDAL-linked packages already in gdal-r-full (sf, terra, ...) are kept.
# A GitHub ref is always installed even if a CRAN version of the same
# package is present (wk is the case that matters).

options(
  Ncpus = max(1L, parallel::detectCores() - 1L),
  repos = c(CRAN = Sys.getenv("CRAN_URL", "https://cloud.r-project.org"))
)

pkgs <- readLines("/tmp/r-packages-mesh.txt")
pkgs <- trimws(pkgs[!grepl("^#", pkgs) & nchar(trimws(pkgs)) > 0])

for (pkg in pkgs) {
  message(strrep("=", 60))
  message("MESH: ", pkg)
  message(strrep("=", 60))
  if (grepl("/", pkg)) {
    remotes::install_github(pkg, upgrade = "never", build_vignettes = FALSE,
                            force = TRUE)
  } else {
    install.packages(pkg, type = "source")
  }
  name <- sub("@.*$", "", sub("^.*/", "", pkg))
  if (!requireNamespace(name, quietly = TRUE)) {
    stop("gdal-r-mesh: ", pkg, " did not install", call. = FALSE)
  }
}

message()
message(strrep("=", 60))
message("Mesh package summary:")
for (pkg in pkgs) {
  name <- sub("@.*$", "", sub("^.*/", "", pkg))
  d <- utils::packageDescription(name)
  ref <- if (!is.null(d$RemoteSha)) {
    sprintf("%s@%s", d$RemoteRef %||% "HEAD", substr(d$RemoteSha, 1, 7))
  } else {
    "CRAN"
  }
  message(sprintf("  %-10s %-12s %s", name, d$Version, ref))
}
