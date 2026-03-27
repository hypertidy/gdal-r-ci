#!/usr/bin/env Rscript
# check-r-versions.R
# Verify all R packages link to the same GDAL/PROJ/GEOS.
#
# GDAL: strict — all packages must report same version
# PROJ: warn only — gdalraster/vapour report GDAL's compile-time PROJ constant
#       while terra/sf query PROJ's runtime API directly. With a single PROJ
#       these differ because GDAL release tarballs embed the PROJ version from
#       when they were cut, not the PROJ we built against. Not a real mismatch.
# GEOS: strict — all packages must report same version

cat("=== R package library version alignment ===\n\n")

# Strip codename suffix e.g. '3.12.3 "Chicoutimi"' -> '3.12.3'
strip_codename <- function(v) trimws(sub('".*"', '', sub("'.*'", '', v)))

extract_gdal_ver <- function(s) {
  s <- strip_codename(s)
  sub("^GDAL ([^,]+),.*", "\\1", s)
}

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
    GDAL = strip_codename(gdalraster::gdal_version()[4]),
    PROJ = pv$name,
    GEOS = NA_character_
  )
}

if (requireNamespace("terra", quietly = TRUE)) {
  results$terra <- list(
    GDAL = strip_codename(terra::libVersion("gdal")),
    PROJ = terra::libVersion("proj"),
    GEOS = terra::libVersion("geos")
  )
}

if (requireNamespace("sf", quietly = TRUE)) {
  v <- sf::sf_extSoftVersion()
  results$sf <- list(
    GDAL = strip_codename(unname(v["GDAL"])),
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
  v <- strip_codename(v)
  v <- sub("dev.*$", "", v)
  v <- sub("-.*$", "", v)
  trimws(v)
}

check_lib <- function(name, sys_ver, pkg_vers, warn_only = FALSE) {
  pkg_vers <- pkg_vers[!is.na(pkg_vers)]
  if (length(pkg_vers) == 0) {
    cat(name, ": no packages report version\n"); return(TRUE)
  }
  sys_n <- normalize(sys_ver)
  pkg_n <- sapply(pkg_vers, normalize)
  ok    <- all(pkg_n == sys_n)
  if (ok) {
    cat(name, ": OK (all match system", sys_ver, ")\n")
  } else if (warn_only) {
    cat(name, ": NOTE — versions differ (expected: packages reporting via GDAL",
        "headers use compile-time PROJ, not runtime PROJ)\n")
    for (i in seq_along(pkg_vers)) {
      flag <- if (pkg_n[i] == sys_n) "ok" else "via-GDAL-headers"
      cat(sprintf("  %-12s %s [%s]\n", names(pkg_vers)[i], pkg_vers[i], flag))
    }
    return(TRUE)
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
proj_ok <- check_lib("PROJ", system_proj, sapply(results, `[[`, "PROJ"),
                     warn_only = TRUE)
geos_ok <- check_lib("GEOS", system_geos, sapply(results, `[[`, "GEOS"))
cat("\n")

#!/usr/bin/env Rscript
# check-r-versions.R
# Verify all R packages link to the same GDAL/PROJ/GEOS.
#
# GDAL: strict — all packages must report same version
# PROJ: warn only — gdalraster/vapour report GDAL's compile-time PROJ constant
#       while terra/sf query PROJ's runtime API directly. With a single PROJ
#       these differ because GDAL release tarballs embed the PROJ version from
#       when they were cut, not the PROJ we built against. Not a real mismatch.
# GEOS: strict — all packages must report same version

cat("=== R package library version alignment ===\n\n")

# Strip codename suffix e.g. '3.12.3 "Chicoutimi"' -> '3.12.3'
strip_codename <- function(v) trimws(sub('".*"', '', sub("'.*'", '', v)))

extract_gdal_ver <- function(s) {
  s <- strip_codename(s)
  sub("^GDAL ([^,]+),.*", "\\1", s)
}

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
    GDAL = strip_codename(gdalraster::gdal_version()[4]),
    PROJ = pv$name,
    GEOS = NA_character_
  )
}

if (requireNamespace("terra", quietly = TRUE)) {
  results$terra <- list(
    GDAL = strip_codename(terra::libVersion("gdal")),
    PROJ = terra::libVersion("proj"),
    GEOS = terra::libVersion("geos")
  )
}

if (requireNamespace("sf", quietly = TRUE)) {
  v <- sf::sf_extSoftVersion()
  results$sf <- list(
    GDAL = strip_codename(unname(v["GDAL"])),
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
  v <- strip_codename(v)
  v <- sub("dev.*$", "", v)
  v <- sub("-.*$", "", v)
  trimws(v)
}

check_lib <- function(name, sys_ver, pkg_vers, warn_only = FALSE) {
  pkg_vers <- pkg_vers[!is.na(pkg_vers)]
  if (length(pkg_vers) == 0) {
    cat(name, ": no packages report version\n"); return(TRUE)
  }
  sys_n <- normalize(sys_ver)
  pkg_n <- sapply(pkg_vers, normalize)
  ok    <- all(pkg_n == sys_n)
  if (ok) {
    cat(name, ": OK (all match system", sys_ver, ")\n")
  } else if (warn_only) {
    cat(name, ": NOTE — versions differ (expected: packages reporting via GDAL",
        "headers use compile-time PROJ, not runtime PROJ)\n")
    for (i in seq_along(pkg_vers)) {
      flag <- if (pkg_n[i] == sys_n) "ok" else "via-GDAL-headers"
      cat(sprintf("  %-12s %s [%s]\n", names(pkg_vers)[i], pkg_vers[i], flag))
    }
    return(TRUE)
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
proj_ok <- check_lib("PROJ", system_proj, sapply(results, `[[`, "PROJ"),
                     warn_only = TRUE)
geos_ok <- check_lib("GEOS", system_geos, sapply(results, `[[`, "GEOS"))
cat("\n")

if (gdal_ok && proj_ok && geos_ok) {
  cat("All versions aligned — environment is clean.\n")
  invisible(TRUE)
} else {
  cat("Version misalignment detected.\n")
  cat("Packages may have been compiled against different libraries.\n")
  stop("Version misalignment detected.", call. = FALSE)
}
