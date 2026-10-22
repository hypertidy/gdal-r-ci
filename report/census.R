# census.R -- load the R geo stack (and, via reticulate, the Python one) in
# one process, then report which shared libraries are mapped.
#
# Prints a single JSON line as the LAST line of output. Uses no packages
# beyond those being probed; JSON is written by hand.

pkgs <- c("gdalraster", "sf", "terra", "vapour", "gdalcubes", "arrow")
loaded <- character()
for (p in pkgs) {
  ok <- suppressWarnings(suppressMessages(
    tryCatch({ loadNamespace(p); TRUE }, error = function(e) FALSE)
  ))
  if (ok) loaded <- c(loaded, p)
}

py_loaded <- character()
census_py <- Sys.getenv("CENSUS_PY")
if (nzchar(census_py) && nzchar(Sys.getenv("RETICULATE_PYTHON")) &&
    requireNamespace("reticulate", quietly = TRUE)) {
  res <- tryCatch({
    reticulate::py_run_string(sprintf(
      "import sys; sys.path.insert(0, %s)",
      encodeString(dirname(census_py), quote = '"')))
    census <- reticulate::import("census")
    unlist(census$load())
  }, error = function(e) character())
  py_loaded <- res
}

families <- list(
  gdal = "^libgdal(-[0-9a-f]+)?\\.so",
  proj = "^libproj(-[0-9a-f]+)?\\.so",
  geos = "^libgeos(-[0-9a-f]+)?(\\.so|-[0-9])",
  geos_c = "^libgeos_c(-[0-9a-f]+)?\\.so",
  arrow = "^libarrow(-[0-9a-f]+)?\\.so",
  parquet = "^libparquet(-[0-9a-f]+)?\\.so",
  hdf5 = "^libhdf5(_serial)?(-[0-9a-f]+)?\\.so",
  netcdf = "^libnetcdf(-[0-9a-f]+)?\\.so",
  tiff = "^libtiff(-[0-9a-f]+)?\\.so",
  curl = "^libcurl(-[0-9a-f]+)?\\.so",
  sqlite3 = "^libsqlite3(-[0-9a-f]+)?\\.so",
  openjp2 = "^libopenjp2(-[0-9a-f]+)?\\.so"
)

maps <- readLines("/proc/self/maps", warn = FALSE)
f6 <- vapply(strsplit(trimws(maps), "[[:space:]]+"),
             function(x) if (length(x) >= 6) x[6] else "", "")
paths <- unique(f6[startsWith(f6, "/")])

jstr <- function(x) paste0('"', gsub('(["\\\\])', "\\\\\\1", x), '"')
jarr <- function(x) paste0("[", paste(vapply(x, jstr, ""), collapse = ","), "]")

fam_json <- character()
for (nm in names(families)) {
  hits <- sort(paths[grepl(families[[nm]], basename(paths))])
  if (length(hits)) fam_json <- c(fam_json, paste0(jstr(nm), ":", jarr(hits)))
}

cat("\n", paste0(
  '{"loaded":', jarr(loaded),
  ',"py_loaded":', jarr(py_loaded),
  ',"families":{', paste(fam_json, collapse = ","), "}}"
), "\n", sep = "")
