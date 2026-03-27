#!/bin/bash
# build-kea.sh — build libkea from source
# KEA is an HDF5-based raster format used in the GDAL KEA driver.
# gdalraster tests use it; worth having in the base image.
set -euo pipefail

KEA_VERSION=${KEA_VERSION:-1.5.3}
NCPUS=${NCPUS:-0}
[ "$NCPUS" = "0" ] && NCPUS=$(nproc)

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT
cd "$WORKDIR"

wget -q "https://github.com/ubarsc/kealib/archive/kealib-${KEA_VERSION}.zip" -O kea.zip
unzip -q kea.zip
cd "kealib-kealib-${KEA_VERSION}"

cmake . \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DBUILD_SHARED_LIBS=ON \
    -DHDF5_INCLUDE_DIR=/usr/include/hdf5/serial \
    -DHDF5_LIB_PATH=/usr/lib/x86_64-linux-gnu/hdf5/serial \
    -DLIBKEA_WITH_GDAL=OFF

make "-j${NCPUS}"
make install
