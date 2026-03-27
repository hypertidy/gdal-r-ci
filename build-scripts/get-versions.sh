#!/bin/bash
# get-versions.sh — query latest release versions from GitHub for GDAL, PROJ, GEOS
# Outputs shell variable assignments; source this or eval in CI.
# Usage:
#   eval "$(bash get-versions.sh)"
#   echo $GDAL_VERSION $PROJ_VERSION $GEOS_VERSION
set -euo pipefail

gh_latest() {
    # $1 = owner/repo
    # Returns tag_name with leading 'v' stripped
    curl -sf "https://api.github.com/repos/$1/releases/latest" \
        -H "Accept: application/vnd.github+json" \
        ${GITHUB_TOKEN:+-H "Authorization: Bearer $GITHUB_TOKEN"} \
        | grep '"tag_name"' \
        | head -1 \
        | sed 's/.*"tag_name": *"v\?\([^"]*\)".*/\1/'
}

GDAL_VERSION=$(gh_latest "OSGeo/gdal")
PROJ_VERSION=$(gh_latest "OSGeo/PROJ")
GEOS_VERSION=$(gh_latest "libgeos/geos")

echo "GDAL_VERSION=${GDAL_VERSION}"
echo "PROJ_VERSION=${PROJ_VERSION}"
echo "GEOS_VERSION=${GEOS_VERSION}"
