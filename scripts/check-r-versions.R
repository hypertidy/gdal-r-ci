#!/usr/bin/env Rscript
# check-r-versions.R
# Verify all R packages link to the same GDAL/PROJ/GEOS versions
#
# This is a critical sanity check - if versions differ, we have a broken environment
# where packages may behave inconsistently or crash.

cat("=== R Package Library Version Alignment Check ===\n\n")

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
errors <- character()

# gdalraster - uses gdal_version()
if (requireNamespace("gdalraster", quietly = TRUE)) {
  results$gdalraster <- list(
    GDAL = gdalraster::gdal_version(),
    PROJ = gdalraster::proj_version(),
    # gdalraster doesn't expose GEOS directly
    GEOS = NA
  )
}

# terra - uses gdal(lib=...)
if (requireNamespace("terra", quietly = TRUE)) {
  results$terra <- list(
    GDAL = terra::gdal(),
    PROJ = terra::gdal(lib = "PROJ"),
    GEOS = terra::gdal(lib = "GEOS")
  )
}

# sf - uses sf_extSoftVersion()
if (requireNamespace("sf", quietly = TRUE)) {
  v <- sf::sf_extSoftVersion()
  results$sf <- list(
    GDAL = unname(v["GDAL"]),
    PROJ = unname(v["PROJ"]),
    GEOS = unname(v["GEOS"])
  )
}

# vapour - uses vapour_gdal_version()
if (requireNamespace("vapour", quietly = TRUE)) {
  results$vapour <- list(
    GDAL = vapour::vapour_gdal_version(),
    PROJ = vapour::vapour_proj_version(),
    # vapour doesn't expose GEOS
    GEOS = NA
  )
}


# gdalcubes
if (requireNamespace("gdalcubes", quietly = TRUE)) {
  v <- gdalcubes::gdalcubes_gdal_version()
  results$gdalcubes <- list(
    GDAL = v,
    PROJ = NA,  # doesn't expose
    GEOS = NA
  )
}

# Print results
cat("Package-reported versions:\n")
cat(sprintf("%-12s %-20s %-12s %-12s\n", "Package", "GDAL", "PROJ", "GEOS"))
cat(sprintf("%-12s %-20s %-12s %-12s\n", "-------", "----", "----", "----"))

for (pkg in names(results)) {
  r <- results[[pkg]]
  cat(sprintf("%-12s %-20s %-12s %-12s\n",
              pkg,
              if (is.na(r$GDAL)) "-" else r$GDAL,
              if (is.na(r$PROJ)) "-" else r$PROJ,
              if (is.na(r$GEOS)) "-" else r$GEOS))
}

# Check for mismatches
cat("\n=== Alignment Check ===\n")

check_version <- function(lib_name, system_ver, pkg_versions) {
  # Filter out NAs and "via sf" markers
  pkg_versions <- pkg_versions[!is.na(pkg_versions) & pkg_versions != "via sf"]

  if (length(pkg_versions) == 0) {
    cat(sprintf("%s: No packages report version (OK if not linked)\n", lib_name))
    return(TRUE)
  }

  # Normalize versions for comparison (strip build metadata like "-dev")
  normalize <- function(v) {
    sub("-.*$", "", sub("dev.*$", "", v))
  }

  system_norm <- normalize(system_ver)
  pkg_norms <- sapply(pkg_versions, normalize)

  all_match <- all(pkg_norms == system_norm)

  if (all_match) {
    cat(sprintf("%s: OK (all packages match system %s)\n", lib_name, system_ver))
  } else {
    cat(sprintf("%s: MISMATCH!\n", lib_name))
    cat(sprintf("  System: %s\n", system_ver))
    for (i in seq_along(pkg_versions)) {
      status <- if (pkg_norms[i] == system_norm) "OK" else "DIFFERS"
      cat(sprintf("  %s: %s [%s]\n", names(pkg_versions)[i], pkg_versions[i], status))
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
  cat("✓ All versions aligned\n")
  quit(status = 0)
} else {
  cat("✗ Version misalignment detected!\n")
  cat("This indicates packages were built against different library versions.\n")
  cat("The environment may behave unpredictably.\n")
  quit(status = 1)
}
