#!/bin/bash
# build-gdal.sh — build GDAL from source against /usr/local PROJ/GEOS
#
# Uses the same PROJ installed by build-proj.sh.
# No PROJ_RENAME_SYMBOLS. GDAL and R packages share one libproj.
#
# After GDAL builds and installs, the Python bindings get rebuilt against
# numpy 2.x. Reason: GDAL's CMake build picks up whatever numpy headers are
# present at compile time. On Ubuntu 24.04 that's apt's python3-numpy (1.x),
# so the resulting _gdal_array.so is hard-linked against the numpy 1.x ABI.
# Downstream venvs install numpy 2.x (the modern stack requires it), and
# importing osgeo.gdal_array crashes with a numpy 1.x/2.x ABI mismatch.
# Rebuilding the bindings against numpy 2.x produces a _gdal_array.so that
# is forward-compatible with any 2.x venv numpy.
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
    -DPython_EXECUTABLE=$(command -v python3) \
    -DBUILD_JAVA_BINDINGS=OFF \
    -DBUILD_CSHARP_BINDINGS=OFF \
    -DBUILD_TESTING=OFF

cmake --build build --parallel "$NCPUS"
cmake --install build

# Verify osgeo landed correctly (against system numpy 1.x at this point)
python3 -c "from osgeo import gdal; print('osgeo.gdal:', gdal.__version__)" \
    || echo "WARNING: osgeo.gdal not importable (check PYTHONPATH)"

# ── Rebuild Python bindings against numpy 2.x ─────────────────────────────────
# See header comment for the why. This block reuses the swig sources still
# present in $WORKDIR/src; the trap at the top will clean them up after.
echo ""
echo "=== Rebuilding GDAL Python bindings against numpy 2.x ==="

# Ensure pip is available; on minimal Ubuntu the apt-installed Python may
# not include it depending on which python3-* packages were pulled.
if ! command -v pip3 >/dev/null 2>&1; then
    python3 -m ensurepip --upgrade --break-system-packages 2>/dev/null \
        || apt-get update -qq && apt-get install -y --no-install-recommends python3-pip
fi

# Install numpy 2.x for the system Python. --break-system-packages bypasses
# Ubuntu 24.04's PEP 668 externally-managed marker. Safe here because this
# IS the system Python and we want this upgrade.
pip3 install --break-system-packages --quiet --upgrade "numpy>=2"

# Rebuild and reinstall the bindings. Sources live under $WORKDIR/src/swig/python.
cd "$WORKDIR/src/swig/python"

# The bindings setup.py reads gdal-config to discover include paths and
# library locations — both already point at /usr/local from the cmake install.
pip3 install --break-system-packages --quiet --force-reinstall --no-deps .

# Sanity check: gdal_array (the numpy-bridging module) imports cleanly.
# This is the exact import that fails on dual-numpy systems.
python3 -c "
import numpy
print(f'numpy: {numpy.__version__}')
from osgeo import gdal, gdal_array
print(f'osgeo.gdal:       {gdal.__version__}')
print(f'osgeo.gdal_array: {gdal_array.__file__}')
print('Bindings rebuilt against numpy 2.x — gdal_array imports cleanly.')
"
