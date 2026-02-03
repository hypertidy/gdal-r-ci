#!/usr/bin/env Rscript
# check-r-versions.R
# Verify all R packages link to the same GDAL/PROJ/GEOS versions
#
# This is a critical sanity check - if versions differ, we have a broken environment
# where packages may behave inconsistently or crash.
#
# Package APIs (as of 2026-02):
#   gdalraster::gdal_version()     -> chr[1:4], [4] is clean version
#   gdalraster::proj_version()     -> chr[1:4], [4] is clean version
#   gdalcubes::gdalcubes_gdalversion() -> "GDAL x.y.z, released..." (needs parsing)
#   sf::sf_extSoftVersion()        -> named chr vector with GDAL, PROJ, GEOS
#   terra::libVersion("gdal")      -> clean version string
#   vapour::vapour_gdal_version()  -> "GDAL x.y.z, released..." (needs parsing)
#   vapour::vapour_proj_version()  -> clean version string

cat("=== R Package Library Version Alignment Check ===\n\n")

# Helper to extract version from "GDAL x.y.z, released..." strings
extract_gdal_version <- function(s) {
  if (grepl("^GDAL ", s)) {
    sub("^GDAL ([^,]+),.*", "\\1", s)
  } else {
    s
  }
}

# Get system library versions (ground truth)
system_gdal <- system("gdal-config --version", intern = TRUE)
system_proj <- system("pkg-config --modversion proj", intern = TRUE)
system_geos <- system("geos-config --version", intern = TRUE)

cat("System libraries (ground truth):\n")
cat("  GDAL:", system_gdal, "\n")
cat("  PROJ:", system_proj, "\n")
cat("  GEOS:", system_geos, "\n\n")

# Collect versions from each package
results <- list()

# gdalraster - gdal_version() returns chr[4], element [4] is clean version
if (requireNamespace("gdalraster", quietly = TRUE)) {
  gv <- gdalraster::gdal_version()
  pv <- gdalraster::proj_version()
  results$gdalraster <- list(
    GDAL = gv[4],
    PROJ = pv[4],
    GEOS = NA  # gdalraster doesn't expose GEOS
  )
}

# terra - libVersion() returns clean strings
if (requireNamespace("terra", quietly = TRUE)) {
  results$terra <- list(
    GDAL = terra::libVersion("gdal"),
    PROJ = terra::libVersion("proj"),
    GEOS = terra::libVersion("geos")
  )
}

# sf - sf_extSoftVersion() returns named vector
if (requireNamespace("sf", quietly = TRUE)) {
  v <- sf::sf_extSoftVersion()
  results$sf <- list(
    GDAL = unname(v["GDAL"]),
    PROJ = unname(v["PROJ"]),
    GEOS = unname(v["GEOS"])
  )
}

# vapour - vapour_gdal_version() returns full string, needs parsing
if (requireNamespace("vapour", quietly = TRUE)) {
  results$vapour <- list(
    GDAL = extract_gdal_version(vapour::vapour_gdal_version()),
    PROJ = vapour::vapour_proj_version(),
    GEOS = NA  # vapour doesn't expose GEOS
  )
}

# gdalcubes - gdalcubes_gdalversion() returns full string, needs parsing
if (requireNamespace("gdalcubes", quietly = TRUE)) {
  results$gdalcubes <- list(
    GDAL = extract_gdal_version(gdalcubes::gdalcubes_gdalversion()),
    PROJ = NA,  # doesn't expose
    GEOS = NA
  )
}

# Print results
cat("Package-reported versions:\n")
cat(sprintf("%-12s %-25s %-12s %-12s\n", "Package", "GDAL", "PROJ", "GEOS"))
cat(sprintf("%-12s %-25s %-12s %-12s\n", "-------", "----", "----", "----"))

for (pkg in names(results)) {
  r <- results[[pkg]]
  cat(sprintf("%-12s %-25s %-12s %-12s\n",
              pkg,
              if (is.na(r$GDAL)) "-" else r$GDAL,
              if (is.na(r$PROJ)) "-" else r$PROJ,
              if (is.na(r$GEOS)) "-" else r$GEOS))
}

# Check for mismatches
cat("\n=== Alignment Check ===\n")

check_version <- function(lib_name, system_ver, pkg_versions) {
  # Filter out NAs
  pkg_versions <- pkg_versions[!is.na(pkg_versions)]

  if (length(pkg_versions) == 0) {
    cat(sprintf("%s: No packages report version (OK if not linked)\n", lib_name))
    return(TRUE)
  }

  # Normalize versions for comparison
  # Handles: "3.13.0dev-abc123" -> "3.13.0"
  #          "3.13.0" -> "3.13.0"
  #          "9.8.0" -> "9.8.0"
  normalize <- function(v) {
    # Strip everything after "dev" or first hyphen
    v <- sub("dev.*$", "", v)
    v <- sub("-.*$", "", v)
    trimws(v)
  }

  system_norm <- normalize(system_ver)
  pkg_norms <- sapply(pkg_versions, normalize, USE.NAMES = TRUE)

  all_match <- all(pkg_norms == system_norm)

  if (all_match) {
    cat(sprintf("%s: OK (all packages match system %s)\n", lib_name, system_ver))
  } else {
    cat(sprintf("%s: MISMATCH!\n", lib_name))
    cat(sprintf("  System: %s (normalized: %s)\n", system_ver, system_norm))
    for (i in seq_along(pkg_versions)) {
      status <- if (pkg_norms[i] == system_norm) "OK" else "DIFFERS"
      cat(sprintf("  %s: %s (normalized: %s) [%s]\n",
                  names(pkg_versions)[i], pkg_versions[i], pkg_norms[i], status))
    }
  }

  return(all_match)
}

gdal_versions <- sapply(results, function(x) x$GDAL)
proj_versions <- sapply(results, function(x) x$PROJ)
geos_versions <- sapply(results, function(x) x$GEOS)

gdal_ok <- check_version("GDAL", system_gdal, gdal_versions)
proj_ok <- check_version("PROJ", system_proj, proj_versions)
geos_ok <- check_version("GEOS", system_geos, geos_versions)

cat("\n")
if (gdal_ok && proj_ok && geos_ok) {
  cat("All versions aligned\n")
  quit(status = 0)
} else {
  cat("Version misalignment detected!\n")
  cat("This indicates packages were built against different library versions.\n")
  cat("The environment may behave unpredictably.\n")
  quit(status = 1)
}
