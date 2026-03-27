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

# Python: find the system python3 explicitly so cmake doesn't guess wrong
PYTHON3=$(command -v python3)

cmake -S src -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    \
    -DPROJ_ROOT=/usr/local \
    -DGEOS_ROOT=/usr/local \
    \
    -DGDAL_USE_ARROW=ON \
    -DGDAL_USE_PARQUET=ON \
    -DGDAL_USE_ARROWDATASET=ON \
    \
    -DGDAL_USE_HDF5=ON \
    -DGDAL_USE_HDF4=ON \
    -DGDAL_USE_NETCDF=ON \
    \
    -DGDAL_USE_ZSTD=ON \
    -DGDAL_USE_BLOSC=ON \
    -DGDAL_USE_LZ4=ON \
    -DGDAL_USE_LERC=ON \
    -DGDAL_USE_DEFLATE=ON \
    \
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
    -DGDAL_USE_TILEDB=ON \
    -DTileDB_ROOT=/usr/local \
    \
    -DGDAL_USE_SPATIALITE=ON \
    -DGDAL_USE_POSTGRESQL=ON \
    -DGDAL_USE_MYSQL=ON \
    -DGDAL_USE_EXPAT=ON \
    -DGDAL_USE_LIBKML=ON \
    \
    -DGDAL_USE_CFITSIO=ON \
    -DGDAL_USE_POPPLER=ON \
    -DGDAL_USE_FREEXL=ON \
    \
    -DBUILD_PYTHON_BINDINGS=ON \
    -DPython_EXECUTABLE="${PYTHON3}" \
    -DBUILD_JAVA_BINDINGS=OFF \
    -DBUILD_CSHARP_BINDINGS=OFF \
    -DBUILD_TESTING=OFF

cmake --build build --parallel "$NCPUS"
cmake --install build

# Verify the Python bindings landed and import correctly
python3 -c "from osgeo import gdal; print('osgeo.gdal:', gdal.__version__)"
