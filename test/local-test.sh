#!/usr/bin/env bash
# test/local-test.sh
#
# Fast local iteration loop for gdal-system Dockerfile changes.
# Builds with BuildKit cache so subsequent runs reuse layers up to the
# first changed line. Runs sanity checks on the resulting image.
#
# Usage:
#   bash test/local-test.sh                 # release variant, GDAL master
#   bash test/local-test.sh dev             # dev variant
#   bash test/local-test.sh release 3.12.4  # release with specific GDAL
#
# Run from repo root.

set -euo pipefail

VARIANT="${1:-release}"
GDAL_VERSION="${2:-master}"

NCPUS="${NCPUS:-$(nproc)}"

case "$VARIANT" in
    release)  TAG="local"     ;;
    dev)      TAG="local-dev" ;;
    *) echo "unknown variant: $VARIANT (use release or dev)"; exit 2 ;;
esac

if [ ! -f docker/Dockerfile.gdal-system ]; then
    echo "run from repo root (docker/Dockerfile.gdal-system not found)"
    exit 2
fi

IMAGE="gdal-system:${TAG}"

echo "=== Building ${IMAGE} (GDAL=${GDAL_VERSION}, NCPUS=${NCPUS}) ==="
DOCKER_BUILDKIT=1 docker build \
    -f docker/Dockerfile.gdal-system \
    --build-arg GDAL_VERSION="${GDAL_VERSION}" \
    --build-arg NCPUS="${NCPUS}" \
    --build-arg CACHE_DATE="$(date +%s)" \
    -t "${IMAGE}" \
    .

echo ""
echo "=== Sanity checks ==="

# Each test is a docker run that fails the script if it errors.
# Cheap, parallel-safe (different containers), and surfaces issues
# specific to the gdal-system layer alone.

run_check() {
    local label="$1"; shift
    printf "  %-40s " "$label"
    if docker run --rm "${IMAGE}" "$@" >/tmp/local-test.out 2>&1; then
        echo "OK"
    else
        echo "FAIL"
        echo "    --- output ---"
        sed 's/^/    /' /tmp/local-test.out
        echo "    --------------"
        return 1
    fi
}

run_check "gdal-config --version reports"           gdal-config --version
run_check "PROJ via pkg-config reports"              pkg-config --modversion proj
run_check "GEOS via geos-config reports"             geos-config --version
run_check "venv python exists"                       /opt/gdal-py/bin/python -c "import sys; print(sys.executable)"
run_check "numpy 2.x installed in venv"              /opt/gdal-py/bin/python -c "import numpy; assert numpy.__version__.startswith('2'), numpy.__version__"
run_check "osgeo.gdal imports"                       /opt/gdal-py/bin/python -c "from osgeo import gdal; print(gdal.__version__)"
run_check "osgeo.gdal_array imports (numpy ABI)"     /opt/gdal-py/bin/python -c "from osgeo import gdal_array; print('ok')"
run_check "key drivers present (arrow/parquet/netcdf/hdf5/zarr/kea)" \
    bash -c 'for d in arrow parquet netcdf hdf5 zarr kea; do gdal-config --formats | grep -qi "$d" || { echo "missing: $d"; exit 1; }; done'
run_check "SQLite driver has spatialite capability" \
    bash -c 'ogrinfo --format SQLite | grep -qi spatialite'
run_check "interactive bash prints MOTD"             bash -ic 'true' 2>&1 | grep -q "ghcr.io/hypertidy/gdal-system"

echo ""
echo "=== Image size ==="
docker images --format '  {{.Repository}}:{{.Tag}}  {{.Size}}' "${IMAGE}"

echo ""
echo "=== Done ==="
