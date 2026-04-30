#!/bin/bash
# build-gdal.sh — build GDAL from source against /usr/local PROJ/GEOS
#
# Uses the same PROJ installed by build-proj.sh.
# No PROJ_RENAME_SYMBOLS. GDAL and R packages share one libproj.
#
# Python bindings link against /opt/gdal-py/bin/python's numpy (2.x). The
# venv was set up before this script runs; no post-hoc rebuild needed.
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

PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:${PKG_CONFIG_PATH:-} \
cmake -S src -B build \
    -DCMAKE_UNITY_BUILD=ON \
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
    -DGDAL_USE_SPATIALITE=ON \
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
    -DPython_EXECUTABLE=/opt/gdal-py/bin/python \
    -DBUILD_JAVA_BINDINGS=OFF \
    -DBUILD_CSHARP_BINDINGS=OFF \
    -DBUILD_TESTING=OFF

cmake --build build --parallel "$NCPUS"
cmake --install build

# Bindings: install via uv (consistent with rest of chain) into the venv.
# Lands at /opt/gdal-py/lib/python3.x/site-packages/osgeo/, not /usr/local.
# --no-deps because numpy is already in the venv and we don't want pip-style
# resolution of GDAL's stated requirements.
# --no-build-isolation because the build needs the venv's numpy 2.x to link
# the bindings; an isolated build env wouldn't have it.
echo "=== Installing GDAL Python bindings into venv ==="
cd "$WORKDIR/build/swig/python"
uv pip install --python /opt/gdal-py/bin/python --no-deps --no-build-isolation .

# Verify bindings landed in the venv and import cleanly. Both gdal and the
# numpy-bridging gdal_array module must work; the latter is the canary for
# the dual-numpy bug class.
/opt/gdal-py/bin/python -c "
import numpy
print(f'numpy:            {numpy.__version__}')
from osgeo import gdal, gdal_array
print(f'osgeo.gdal:       {gdal.__version__}')
print(f'osgeo.gdal_array: {gdal_array.__file__}')
"
