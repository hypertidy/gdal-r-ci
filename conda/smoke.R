# smoke.R -- versions, and one GDAL/PROJ/GEOS seen from R and Python.
#
# Loads the R GDAL packages that are present, imports osgeo through
# reticulate in the same process, prints what each reports, and fails if
# more than one libgdal / libproj / libgeos_c is mapped.

pkgs <- c("gdalraster", "sf", "terra", "vapour")
have <- pkgs[vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
for (p in have) suppressPackageStartupMessages(loadNamespace(p))

cat("gdal-config :", system("gdal-config --version", intern = TRUE), "\n")
if ("sf" %in% have) {
  v <- sf::sf_extSoftVersion()
  cat("sf          : GDAL", v[["GDAL"]], " PROJ", v[["PROJ"]], " GEOS", v[["GEOS"]], "\n")
}
if ("terra" %in% have) cat("terra       : GDAL", terra::gdal(), "\n")
if ("gdalraster" %in% have) cat("gdalraster  : ", gdalraster::gdal_version()[1], "\n")
if ("vapour" %in% have) cat("vapour      : ", vapour::vapour_gdal_version(), "\n")

py <- Sys.getenv("RETICULATE_PYTHON",
                 file.path(Sys.getenv("CONDA_PREFIX"), "bin", "python"))
Sys.setenv(RETICULATE_PYTHON = py)
gdal <- reticulate::import("osgeo.gdal")
cat("osgeo       : ", gdal$`__version__`, " (", py, ")\n", sep = "")

maps <- readLines("/proc/self/maps", warn = FALSE)
lib_paths <- function(pattern) {
  f <- vapply(strsplit(trimws(maps), "[[:space:]]+"),
              function(x) if (length(x) >= 6) x[6] else "", "")
  unique(f[grepl(pattern, basename(f))])
}
fams <- c(gdal = "^libgdal\\.so", proj = "^libproj\\.so",
          geos_c = "^libgeos_c\\.so")
bad <- FALSE
for (nm in names(fams)) {
  hits <- lib_paths(fams[[nm]])
  cat(sprintf("%-11s : %s\n", nm, paste(hits, collapse = " | ")))
  if (length(hits) > 1) bad <- TRUE
}
if (bad) stop("more than one copy of a core library is mapped")
cat("ok: one libgdal, one libproj, one libgeos_c in this process\n")
