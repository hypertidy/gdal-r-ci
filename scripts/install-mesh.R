#!/usr/bin/env Rscript
# install-mesh.R
#
# Mesh packages installed on top of gdal-r-full to produce gdal-r-mesh.
# Reads /tmp/r-packages-mesh.txt in order; see that file for the entry
# forms. Entries prefixed with "?" are optional.
#
# GitHub and GitLab entries are installed with remotes and
# upgrade = "never", so the GDAL-linked packages already in gdal-r-full
# (sf, terra, ...) are kept. A remote ref is always installed even if a
# CRAN version of the same package is present (wk is the case that matters).

options(
  Ncpus = max(1L, parallel::detectCores() - 1L),
  repos = c(CRAN = Sys.getenv("CRAN_URL", "https://cloud.r-project.org"))
)

entries <- readLines("/tmp/r-packages-mesh.txt")
entries <- trimws(entries[!grepl("^#", entries) & nchar(trimws(entries)) > 0])

optional <- startsWith(entries, "?")
pkgs <- sub("^\\?", "", entries)

pkg_name <- function(pkg) {
  sub("@.*$", "", sub("^.*/", "", sub("^gitlab::", "", pkg)))
}

install_one <- function(pkg) {
  if (startsWith(pkg, "gitlab::")) {
    remotes::install_gitlab(sub("^gitlab::", "", pkg), upgrade = "never",
                            build_vignettes = FALSE, force = TRUE)
  } else if (grepl("/", pkg)) {
    remotes::install_github(pkg, upgrade = "never", build_vignettes = FALSE,
                            force = TRUE)
  } else {
    install.packages(pkg, type = "source")
  }
  requireNamespace(pkg_name(pkg), quietly = TRUE)
}

ok <- logical(length(pkgs))
for (i in seq_along(pkgs)) {
  pkg <- pkgs[i]
  message(strrep("=", 60))
  message("MESH: ", pkg, if (optional[i]) " (optional)")
  message(strrep("=", 60))
  ok[i] <- tryCatch(install_one(pkg), error = function(e) {
    message("FAILED: ", conditionMessage(e))
    FALSE
  })
  if (!ok[i] && !optional[i]) {
    stop("gdal-r-mesh: ", pkg, " did not install", call. = FALSE)
  }
}

message()
message(strrep("=", 60))
message("Mesh package summary:")
for (i in seq_along(pkgs)) {
  name <- pkg_name(pkgs[i])
  if (!ok[i]) {
    message(sprintf("  %-10s FAILED (optional)", name))
    next
  }
  d <- utils::packageDescription(name)
  ref <- if (!is.null(d$RemoteSha)) {
    sprintf("%s@%s", d$RemoteRef %||% "HEAD", substr(d$RemoteSha, 1, 7))
  } else {
    "CRAN"
  }
  message(sprintf("  %-10s %-12s %s", name, d$Version, ref))
}
