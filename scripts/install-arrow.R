# R arrow for ghcr.io/hypertidy/gdal-r-full, built from source against the
# system Arrow C++ that gdal-system installs from apt (libarrow-dev etc.).
#
# One libarrow per process: GDAL's Parquet/Arrow drivers, R arrow and (in
# gdal-r-python) pyarrow all link the same shared libarrow. A bundled or
# downloaded libarrow (LIBARROW_BINARY=true) would put a second Arrow C++ in
# the process, and recompiling it in every downstream CI job is slow.
#
# The R package's major version must equal the Arrow C++ major version, as
# for pyarrow in gdal-r-python. CRAN can briefly be ahead of or behind the
# apt release, so ask for the newest arrow within that major.

cpp_version <- system2("pkg-config", c("--modversion", "arrow"), stdout = TRUE)
major <- as.integer(strsplit(cpp_version, ".", fixed = TRUE)[[1]][1])
message("Arrow C++ (pkg-config): ", cpp_version)

Sys.setenv(
  LIBARROW_BINARY      = "false",
  ARROW_USE_PKG_CONFIG = "true",
  ARROW_R_DEV          = "false",
  NOT_CRAN             = "false"
)

repos <- c(CRAN = Sys.getenv("CRAN_URL", "https://cloud.r-project.org"))
spec <- sprintf(">= %d.0.0, < %d.0.0", major, major + 1L)
message("Installing R arrow ", spec, " from source")
remotes::install_version("arrow", version = spec, repos = repos,
                         type = "source", upgrade = "never")

# Verify: loads, same major, and links the shared system libarrow.
library(arrow)
r_version <- as.character(utils::packageVersion("arrow"))
message("R arrow: ", r_version)
if (as.integer(strsplit(r_version, ".", fixed = TRUE)[[1]][1]) != major) {
  stop("R arrow ", r_version, " does not match Arrow C++ ", cpp_version)
}
so <- system.file("libs", "arrow.so", package = "arrow")
ldd <- system2("ldd", so, stdout = TRUE)
if (!any(grepl("libarrow\\.so", ldd))) {
  stop("R arrow is not linked to the shared system libarrow:\n",
       paste(ldd, collapse = "\n"))
}
message(paste(grep("libarrow|libparquet", ldd, value = TRUE), collapse = "\n"))
