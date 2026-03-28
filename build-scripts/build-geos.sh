#!/bin/bash
# build-geos.sh — build GEOS from source and install to /usr/local
set -euo pipefail

GEOS_VERSION=${GEOS_VERSION:-main}
NCPUS=${NCPUS:-0}
[ "$NCPUS" = "0" ] && NCPUS=$(nproc)

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT
cd "$WORKDIR"

if [ "$GEOS_VERSION" = "main" ] || [ "$GEOS_VERSION" = "master" ]; then
    git clone --depth 1 https://github.com/libgeos/geos.git src
else
    wget -q "https://download.osgeo.org/geos/geos-${GEOS_VERSION}.tar.bz2" -O geos.tar.bz2
    mkdir src && tar xf geos.tar.bz2 -C src --strip-components=1
fi

cmake -S src -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DBUILD_TESTING=OFF

cmake --build build --parallel "$NCPUS"
cmake --install build

# Remove system GEOS dev package if present — it arrives as a dependency of
# libspatialite-dev and puts stale headers in /usr/include that confuse
# R packages into compiling against the wrong GEOS version.
# We have our source-built GEOS in /usr/local so this is safe.
if dpkg -l libgeos-dev >/dev/null 2>&1; then
    apt-get remove -y --auto-remove libgeos-dev
    echo "Removed system libgeos-dev (replaced by source build in /usr/local)"
fi
