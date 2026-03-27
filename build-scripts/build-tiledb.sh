#!/bin/bash
# build-tiledb.sh — build TileDB from source
# TileDB's apt package lags behind what GDAL's TileDB driver expects.
set -euo pipefail

TILEDB_VERSION=${TILEDB_VERSION:-2.26.2}
NCPUS=${NCPUS:-0}
[ "$NCPUS" = "0" ] && NCPUS=$(nproc)

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT
cd "$WORKDIR"

wget -q "https://github.com/TileDB-Inc/TileDB/archive/${TILEDB_VERSION}.tar.gz" -O tiledb.tar.gz
mkdir src && tar xf tiledb.tar.gz -C src --strip-components=1

cd src
mkdir build_cmake && cd build_cmake
../bootstrap --prefix=/usr/local --disable-werror --disable-tests
make "-j${NCPUS}"
make install-tiledb
