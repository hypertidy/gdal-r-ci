#!/bin/bash
# get-versions.sh — query latest release versions from GitHub for GDAL, PROJ, GEOS
#
# GEOS note: always query latest GEOS but cap at a version known to work with
# the resolved GDAL release. GEOS 3.14.x introduced symbols that GDAL 3.12.x
# doesn't reference, causing undefined symbol errors at runtime in R packages.
# We use GDAL's own release notes to determine the tested GEOS range.
#
# Safe pairings (update as new GDAL releases ship):
#   GDAL 3.10.x → GEOS <= 3.13.x
#   GDAL 3.11.x → GEOS <= 3.13.x
#   GDAL 3.12.x → GEOS <= 3.13.x
#   GDAL 3.13.x → GEOS <= 3.14.x
set -euo pipefail

gh_latest() {
    curl -sf "https://api.github.com/repos/$1/releases/latest" \
        -H "Accept: application/vnd.github+json" \
        ${GITHUB_TOKEN:+-H "Authorization: Bearer $GITHUB_TOKEN"} \
        | grep '"tag_name"' \
        | head -1 \
        | sed 's/.*"tag_name": *"v\?\([^"]*\)".*/\1/'
}

GDAL_VERSION=$(gh_latest "OSGeo/gdal")
PROJ_VERSION=$(gh_latest "OSGeo/PROJ")
GEOS_LATEST=$(gh_latest "libgeos/geos")

# Cap GEOS based on GDAL major.minor to avoid undefined symbol errors
GDAL_MAJOR=$(echo "$GDAL_VERSION" | cut -d. -f1)
GDAL_MINOR=$(echo "$GDAL_VERSION" | cut -d. -f2)

# GDAL < 3.13 should use GEOS 3.13.x max
if [ "$GDAL_MAJOR" -lt 3 ] || { [ "$GDAL_MAJOR" -eq 3 ] && [ "$GDAL_MINOR" -lt 13 ]; }; then
    # Check if latest GEOS is 3.14+; if so cap at 3.13 series
    GEOS_MAJOR=$(echo "$GEOS_LATEST" | cut -d. -f1)
    GEOS_MINOR=$(echo "$GEOS_LATEST" | cut -d. -f2)
    if [ "$GEOS_MAJOR" -gt 3 ] || { [ "$GEOS_MAJOR" -eq 3 ] && [ "$GEOS_MINOR" -ge 14 ]; }; then
        # Find latest 3.13.x release
        GEOS_VERSION=$(curl -sf "https://api.github.com/repos/libgeos/geos/releases" \
            -H "Accept: application/vnd.github+json" \
            ${GITHUB_TOKEN:+-H "Authorization: Bearer $GITHUB_TOKEN"} \
            | grep '"tag_name"' \
            | sed 's/.*"tag_name": *"v\?\([^"]*\)".*/\1/' \
            | grep '^3\.13\.' \
            | head -1)
        echo "# NOTE: capped GEOS ${GEOS_LATEST} → ${GEOS_VERSION} for GDAL ${GDAL_VERSION}" >&2
    else
        GEOS_VERSION="$GEOS_LATEST"
    fi
else
    GEOS_VERSION="$GEOS_LATEST"
fi

echo "GDAL_VERSION=${GDAL_VERSION}"
echo "PROJ_VERSION=${PROJ_VERSION}"
echo "GEOS_VERSION=${GEOS_VERSION}"
