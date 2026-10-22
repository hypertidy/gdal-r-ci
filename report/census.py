#!/usr/bin/env python3
"""census.py -- import the Python geo stack, then report mapped libraries.

Prints JSON: {"loaded": [...modules...], "families": {family: [paths]}}.
Also importable from R via reticulate (see census.R): call families().
"""

import importlib
import json
import os
import re

MODULES = [
    "numpy", "osgeo.gdal", "osgeo.ogr", "osgeo.osr", "osgeo.gdal_array",
    "pyproj", "shapely", "rasterio", "fiona", "pyogrio", "h5py", "netCDF4",
    "pyarrow", "pyarrow.parquet", "imagecodecs",
]

# One family per library that should exist exactly once in a process.
# Wheel-bundled copies are renamed by auditwheel (libhdf5-1a2b3c4d.so.310),
# so the patterns allow a -hash suffix.
FAMILIES = {
    "gdal": r"^libgdal(-[0-9a-f]+)?\.so",
    "proj": r"^libproj(-[0-9a-f]+)?\.so",
    "geos": r"^libgeos(-[0-9a-f]+)?(\.so|-\d)",
    "geos_c": r"^libgeos_c(-[0-9a-f]+)?\.so",
    "arrow": r"^libarrow(-[0-9a-f]+)?\.so",
    "parquet": r"^libparquet(-[0-9a-f]+)?\.so",
    "hdf5": r"^libhdf5(_serial)?(-[0-9a-f]+)?\.so",
    "netcdf": r"^libnetcdf(-[0-9a-f]+)?\.so",
    "tiff": r"^libtiff(-[0-9a-f]+)?\.so",
    "curl": r"^libcurl(-[0-9a-f]+)?\.so",
    "sqlite3": r"^libsqlite3(-[0-9a-f]+)?\.so",
    "openjp2": r"^libopenjp2(-[0-9a-f]+)?\.so",
}


def families():
    paths = set()
    with open("/proc/self/maps") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 6 and parts[5].startswith("/"):
                paths.add(parts[5])
    out = {}
    for fam, pat in FAMILIES.items():
        hits = sorted(p for p in paths if re.match(pat, os.path.basename(p)))
        if hits:
            out[fam] = hits
    return out


def load(modules=MODULES):
    loaded = []
    for m in modules:
        try:
            importlib.import_module(m)
            loaded.append(m)
        except Exception:
            pass
    return loaded


if __name__ == "__main__":
    loaded = load()
    print(json.dumps({"loaded": loaded, "families": families()}))
