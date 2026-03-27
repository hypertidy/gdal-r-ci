#!/bin/bash
# build-proj.sh — build PROJ from source and install to /usr/local
#
# CRITICAL: no -DPROJ_RENAME_SYMBOLS, no -DPROJ_INTERNAL_CPP_NAMESPACE.
# This is the single PROJ that both GDAL and R packages (sf, terra, vapour)
# will link against. Standard symbols only.
set -euo pipefail

PROJ_VERSION=${PROJ_VERSION:-master}
NCPUS=${NCPUS:-0}
[ "$NCPUS" = "0" ] && NCPUS=$(nproc)

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT
cd "$WORKDIR"

if [ "$PROJ_VERSION" = "master" ]; then
    git clone --depth 1 https://github.com/OSGeo/PROJ.git src
else
    wget -q "https://download.osgeo.org/proj/proj-${PROJ_VERSION}.tar.gz" -O proj.tar.gz
    mkdir src && tar xf proj.tar.gz -C src --strip-components=1
fi

cmake -S src -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DBUILD_SHARED_LIBS=ON \
    -DBUILD_TESTING=OFF \
    -DENABLE_TIFF=ON \
    -DENABLE_CURL=ON

cmake --build build --parallel "$NCPUS"
cmake --install build

# Download datum shift grids (needed for accurate transformations).
# projsync writes to the PROJ data directory.
# Download datum shift grids.
# --bbox with global extent fetches the most commonly needed grids without
# pulling the full ~600MB that --all would download. Non-fatal if network fails.
/usr/local/bin/projsync --system-directory \
    --bbox -180,-90,180,90 --quiet || \
    echo "projsync failed (network?), continuing without optional grids"
