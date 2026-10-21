#!/bin/bash
# build-spatialite.sh — build libspatialite from source
#
# Must run AFTER GEOS and PROJ are installed to /usr/local, and BEFORE GDAL
# (GDAL's SQLite/GPKG drivers link it).
# Removes the apt-installed libspatialite-dev first to avoid header confusion.
set -euo pipefail

SPATIALITE_VERSION=${SPATIALITE_VERSION:-5.1.0}
SPATIALITE_URL=${SPATIALITE_URL:-"https://www.gaia-gis.it/gaia-sins/libspatialite-sources/libspatialite-${SPATIALITE_VERSION}.tar.gz"}

NCPUS=${NCPUS:-0}
[ "$NCPUS" = "0" ] && NCPUS=$(nproc)

# Remove apt spatialite: it is compiled against the system GEOS (3.12.1 on
# 24.04, 3.14.1 on 26.04), not our /usr/local GEOS, and would conflict at
# the header level
if dpkg -l libspatialite-dev >/dev/null 2>&1; then
    apt-get remove -y libspatialite-dev libspatialite8t64 2>/dev/null || \
    apt-get remove -y libspatialite-dev libspatialite7 2>/dev/null || \
    apt-get remove -y libspatialite-dev || true
    echo "Removed apt libspatialite"
fi

# Also remove system libgeos-dev now that spatialite won't need it
if dpkg -l libgeos-dev >/dev/null 2>&1; then
    apt-get remove -y libgeos-dev
    echo "Removed system libgeos-dev"
fi

# Build deps not already in /usr/local (normally already present from the
# main apt layer; the lists were removed there, so refresh before installing)
apt-get update -qq
apt-get install -y --no-install-recommends \
    libminizip-dev \
    libxml2-dev
rm -rf /var/lib/apt/lists/*

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT
cd "$WORKDIR"

echo "Downloading spatialite from ${SPATIALITE_URL}"
wget -q "${SPATIALITE_URL}" -O spatialite.tar.gz \
    || { echo "ERROR: spatialite download failed from ${SPATIALITE_URL}"; exit 1; }
mkdir src && tar xf spatialite.tar.gz -C src --strip-components=1
cd src

# Configure: point explicitly at /usr/local for GEOS/PROJ
# disable RTTOPO if not available (optional topology support)
# gcc >= 14 makes implicit function declarations an error, and spatialite
# 5.1.0 has some. Debian/Ubuntu build the same unpatched 5.1.0 with exactly
# this flag appended (debian/rules: DEB_CFLAGS_MAINT_APPEND); harmless on
# older gcc.
CFLAGS="${CFLAGS:--O2} -Wno-error=implicit-function-declaration" \
PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:${PKG_CONFIG_PATH:-} \
./configure \
    --prefix=/usr/local \
    --with-geosconfig=/usr/local/bin/geos-config \
    --with-projdir=/usr/local \
    --disable-rttopo \
    --disable-static

make "-j${NCPUS}"
# install-strip: strip at install time, in the same layer (see build-geos.sh).
make install-strip
ldconfig

echo "spatialite: $(spatialite --version 2>&1 | head -1 || echo 'installed')"

# Verify pkg-config can find it (needed by GDAL cmake)
if pkg-config --exists spatialite; then
    echo "spatialite pkg-config: $(pkg-config --modversion spatialite)"
else
    echo "WARNING: spatialite not found via pkg-config"
    echo "Expected .pc file at /usr/local/lib/pkgconfig/spatialite.pc"
    ls /usr/local/lib/pkgconfig/ | grep -i spat || echo "Not found"
fi
