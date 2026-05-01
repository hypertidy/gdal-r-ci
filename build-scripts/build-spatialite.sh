#!/bin/bash
# build-spatialite.sh — build libspatialite from source
#
# Must run AFTER GEOS, PROJ, and GDAL are installed to /usr/local.
# Removes the apt-installed libspatialite-dev first to avoid header confusion.
set -euo pipefail

SPATIALITE_VERSION=${SPATIALITE_VERSION:-5.1.0}
SPATIALITE_URL=${SPATIALITE_URL:-"https://www.gaia-gis.it/gaia-sins/libspatialite-sources/libspatialite-${SPATIALITE_VERSION}.tar.gz"}

NCPUS=${NCPUS:-0}
[ "$NCPUS" = "0" ] && NCPUS=$(nproc)

# Remove apt spatialite — it was compiled against system GEOS 3.12.1
# and would conflict with our /usr/local GEOS at the header level
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

# Build deps not already in /usr/local
apt-get install -y --no-install-recommends \
    libminizip-dev \
    libxml2-dev

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
PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:${PKG_CONFIG_PATH:-} \
./configure \
    --prefix=/usr/local \
    --with-geosconfig=/usr/local/bin/geos-config \
    --with-projdir=/usr/local \
    --disable-rttopo \
    --disable-static

make "-j${NCPUS}"
make install
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
