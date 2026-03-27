#!/usr/bin/env Rscript
# check-r-versions.R
# Verify all R packages link to the same GDAL/PROJ/GEOS.
#
# With a single PROJ (no osgeo/gdal internal-PROJ), all packages should report
# exactly the same versions. PROJ check is now strict (was warn_only before).
#
# Package version APIs:
#   gdalraster::gdal_version()          -> chr[4], [4] is "X.Y.Z"
#   gdalraster::proj_version()          -> list $major/$minor/$patch/$name
#   sf::sf_extSoftVersion()             -> named chr: GDAL, PROJ, GEOS
#   terra::libVersion("gdal"|"proj"|"geos") -> "X.Y.Z"
#   vapour::vapour_gdal_version()       -> "GDAL X.Y.Z, released ..."
#   vapour::vapour_proj_version()       -> "X.Y.Z"
#   gdalcubes::gdalcubes_gdalversion()  -> "GDAL X.Y.Z, released ..."

cat("=== R package library version alignment ===\n\n")

extract_gdal_ver <- function(s) sub("^GDAL ([^,]+),.*", "\\1", s)

system_gdal <- system("gdal-config --version", intern = TRUE)
system_proj <- system("pkg-config --modversion proj", intern = TRUE)
system_geos <- system("geos-config --version", intern = TRUE)

cat("System libraries (ground truth):\n")
cat("  GDAL:", system_gdal, "\n")
cat("  PROJ:", system_proj, "\n")
cat("  GEOS:", system_geos, "\n\n")

results <- list()

if (requireNamespace("gdalraster", quietly = TRUE)) {
  pv <- gdalraster::proj_version()
  results$gdalraster <- list(
    GDAL = gdalraster::gdal_version()[4],
    PROJ = pv$name,
    GEOS = NA_character_
  )
}

if (requireNamespace("terra", quietly = TRUE)) {
  results$terra <- list(
    GDAL = terra::libVersion("gdal"),
    PROJ = terra::libVersion("proj"),
    GEOS = terra::libVersion("geos")
  )
}

if (requireNamespace("sf", quietly = TRUE)) {
  v <- sf::sf_extSoftVersion()
  results$sf <- list(
    GDAL = unname(v["GDAL"]),
    PROJ = unname(v["PROJ"]),
    GEOS = unname(v["GEOS"])
  )
}

if (requireNamespace("vapour", quietly = TRUE)) {
  results$vapour <- list(
    GDAL = extract_gdal_ver(vapour::vapour_gdal_version()),
    PROJ = vapour::vapour_proj_version(),
    GEOS = NA_character_
  )
}

if (requireNamespace("gdalcubes", quietly = TRUE)) {
  results$gdalcubes <- list(
    GDAL = extract_gdal_ver(gdalcubes::gdalcubes_gdalversion()),
    PROJ = NA_character_,
    GEOS = NA_character_
  )
}

cat(sprintf("%-12s %-12s %-12s %-12s\n", "Package", "GDAL", "PROJ", "GEOS"))
cat(sprintf("%-12s %-12s %-12s %-12s\n", "-------", "----", "----", "----"))
for (pkg in names(results)) {
  r <- results[[pkg]]
  cat(sprintf("%-12s %-12s %-12s %-12s\n",
    pkg,
    if (is.na(r$GDAL)) "-" else r$GDAL,
    if (is.na(r$PROJ)) "-" else r$PROJ,
    if (is.na(r$GEOS)) "-" else r$GEOS))
}
cat("\n")

normalize <- function(v) {
  v <- sub("dev.*$", "", v); v <- sub("-.*$", "", v); trimws(v)
}

check_lib <- function(name, sys_ver, pkg_vers) {
  pkg_vers <- pkg_vers[!is.na(pkg_vers)]
  if (length(pkg_vers) == 0) {
    cat(name, ": no packages report version\n"); return(TRUE)
  }
  sys_n   <- normalize(sys_ver)
  pkg_n   <- sapply(pkg_vers, normalize)
  ok      <- all(pkg_n == sys_n)
  if (ok) {
    cat(name, ": OK (all match system", sys_ver, ")\n")
  } else {
    cat(name, ": MISMATCH\n")
    cat("  system:", sys_ver, "\n")
    for (i in seq_along(pkg_vers)) {
      flag <- if (pkg_n[i] == sys_n) "ok" else "DIFFERS"
      cat(sprintf("  %-12s %s [%s]\n", names(pkg_vers)[i], pkg_vers[i], flag))
    }
  }
  ok
}

cat("=== Alignment check ===\n")
gdal_ok <- check_lib("GDAL", system_gdal, sapply(results, `[[`, "GDAL"))
# PROJ: strict — with a single PROJ there is no legitimate reason for mismatch
proj_ok <- check_lib("PROJ", system_proj, sapply(results, `[[`, "PROJ"))
geos_ok <- check_lib("GEOS", system_geos, sapply(results, `[[`, "GEOS"))
cat("\n")

if (gdal_ok && proj_ok && geos_ok) {
  cat("All versions aligned — environment is clean.\n")
  quit(status = 0)
} else {
  cat("Version misalignment detected.\n")
  cat("Packages may have been compiled against different libraries.\n")
  quit(status = 1)
}
