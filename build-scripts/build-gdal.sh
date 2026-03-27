#!/bin/bash
# build-gdal.sh — build GDAL from source against /usr/local PROJ/GEOS
#
# Uses the same PROJ installed by build-proj.sh.
# No PROJ_RENAME_SYMBOLS. GDAL and R packages share one libproj.
set -euo pipefail

GDAL_VERSION=${GDAL_VERSION:-master}
GDAL_REPOSITORY=${GDAL_REPOSITORY:-OSGeo/gdal}
NCPUS=${NCPUS:-0}
[ "$NCPUS" = "0" ] && NCPUS=$(nproc)

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT
cd "$WORKDIR"

if [ "$GDAL_VERSION" = "master" ]; then
    git clone --depth 1 "https://github.com/${GDAL_REPOSITORY}.git" src
else
    wget -q "https://github.com/${GDAL_REPOSITORY}/archive/refs/tags/v${GDAL_VERSION}.tar.gz" \
        -O gdal.tar.gz
    mkdir src && tar xf gdal.tar.gz -C src --strip-components=1
fi

cmake -S src -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    \
    `# ── PROJ/GEOS: our source-built versions in /usr/local ──` \
    -DPROJ_ROOT=/usr/local \
    -DGEOS_ROOT=/usr/local \
    \
    `# ── Arrow / GeoParquet ──` \
    -DGDAL_USE_ARROW=ON \
    -DGDAL_USE_PARQUET=ON \
    -DGDAL_USE_ARROWDATASET=ON \
    \
    `# ── HDF / NetCDF ──` \
    -DGDAL_USE_HDF5=ON \
    -DGDAL_USE_HDF4=ON \
    -DGDAL_USE_NETCDF=ON \
    \
    `# ── Cloud-native compression ──` \
    -DGDAL_USE_ZSTD=ON \
    -DGDAL_USE_BLOSC=ON \
    -DGDAL_USE_LZ4=ON \
    -DGDAL_USE_LERC=ON \
    -DGDAL_USE_DEFLATE=ON \
    \
    `# ── Raster formats ──` \
    -DGDAL_USE_TIFF_INTERNAL=ON \
    -DGDAL_USE_GEOTIFF_INTERNAL=ON \
    -DGDAL_USE_PNG=ON \
    -DGDAL_USE_JPEG=ON \
    -DGDAL_USE_WEBP=ON \
    -DGDAL_USE_OPENJPEG=ON \
    -DGDAL_USE_KEA=ON \
    -DKEA_INCLUDE_DIR=/usr/local/include \
    -DKEA_LIBRARY=/usr/local/lib/libkea.so \
    \
    `# ── Vector / database drivers ──` \
    -DGDAL_USE_SPATIALITE=ON \
    -DGDAL_USE_RASTERLITE2=ON \
    -DGDAL_USE_POSTGRESQL=ON \
    -DGDAL_USE_MYSQL=ON \
    -DGDAL_USE_EXPAT=ON \
    -DGDAL_USE_LIBKML=ON \
    -DGDAL_USE_XERCES=ON \
    \
    `# ── Other formats ──` \
    -DGDAL_USE_CFITSIO=ON \
    -DGDAL_USE_POPPLER=ON \
    -DGDAL_USE_FREEXL=ON \
    \
    `# ── Python bindings: off (separate concern) ──` \
    -DBUILD_PYTHON_BINDINGS=OFF \
    -DBUILD_JAVA_BINDINGS=OFF \
    -DBUILD_CSHARP_BINDINGS=OFF \
    -DBUILD_TESTING=OFF

cmake --build build --parallel "$NCPUS"
cmake --install build
