#!/usr/bin/env python3
"""image-report.py -- measure a gdal-r-ci image from the inside.

Run inside the image with the venv interpreter, stdlib only:

    docker run --rm -v "$PWD/report:/report:ro" IMAGE \
        /opt/gdal-py/bin/python /report/image-report.py

Prints one JSON document to stdout. Every probe is defensive: a missing
tool or package is recorded as null, never an error, so the same script
runs on every image in the chain (gdal-system has no R, and so on).
"""

import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd, timeout=600, env=None):
    """Return stdout (stripped) or None if the command is missing/fails."""
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def first_line(s):
    return s.splitlines()[0].strip() if s else None


# -- versions -----------------------------------------------------------------

def os_release():
    info = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.rstrip("\n").split("=", 1)
                    info[k] = v.strip('"')
    except OSError:
        pass
    return info.get("PRETTY_NAME"), info.get("VERSION_CODENAME")


def versions():
    pretty, codename = os_release()
    v = {
        "os": pretty,
        "codename": codename,
        "gdal": run(["gdal-config", "--version"]),
        "proj": run(["pkg-config", "--modversion", "proj"]),
        "geos": run(["geos-config", "--version"]),
        "arrow": run(["pkg-config", "--modversion", "arrow"]),
        "python": sys.version.split()[0],
        "r": None,
        "rustc": first_line(run(["rustc", "--version"])),
    }
    rv = run(["Rscript", "-e", "cat(as.character(getRversion()))"])
    if rv:
        v["r"] = rv
    return v


PY_PACKAGES = [
    "numpy", "GDAL", "pyarrow", "rasterio", "fiona", "pyogrio", "shapely",
    "pyproj", "geopandas", "xarray", "zarr", "h5py", "netCDF4", "dask",
    "icechunk", "virtualizarr", "kerchunk", "obstore", "rioxarray",
    "odc-geo", "polars", "duckdb", "sedonadb", "gdalxarray",
]

R_PACKAGES = [
    "gdalraster", "sf", "terra", "vapour", "gdalcubes", "stars", "wk", "s2",
    "geos", "reticulate", "arrow", "pizzarr", "nanoarrow", "duckdb",
]


def py_packages():
    from importlib import metadata
    out = {}
    for name in PY_PACKAGES:
        try:
            out[name] = metadata.version(name)
        except Exception:
            pass
    return out


def r_packages():
    if not shutil.which("Rscript"):
        return None
    expr = (
        "p <- c(%s); "
        "for (x in p) { v <- tryCatch(as.character(packageVersion(x)), "
        "error = function(e) NA); if (!is.na(v)) cat(x, v, '\\n') }"
    ) % ", ".join('"%s"' % p for p in R_PACKAGES)
    txt = run(["Rscript", "-e", expr])
    if txt is None:
        return {}
    out = {}
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out[parts[0]] = parts[1]
    return out


# -- sizes --------------------------------------------------------------------

DU_PATHS = [
    "/usr/local/share/proj",
    "/usr/local/lib",
    "/usr/local/include",
    "/usr/local/rustup",
    "/usr/local/cargo",
    "/opt/rustup",
    "/opt/cargo",
    "/opt/gdal-py",
    "/usr/local/lib/R/site-library",
    "/usr/lib/R",
    "/root/.TinyTeX",
    "/root/.cache",
    "/usr/lib/x86_64-linux-gnu",
    "/usr/share/doc",
    "/var/lib/apt/lists",
]


def conda_prefix():
    p = os.environ.get("CONDA_PREFIX")
    return p if p and os.path.isdir(os.path.join(p, "conda-meta")) else None


def du():
    out = {}
    paths = list(DU_PATHS)
    cp = conda_prefix()
    if cp:
        paths += [cp, os.path.join(cp, "lib"), os.path.join(cp, "share", "proj"),
                  os.path.join(cp, "lib", "R", "library"),
                  os.path.join(cp, "lib", "python%d.%d" % sys.version_info[:2],
                               "site-packages"),
                  os.path.join(cp, "include")]
    for p in paths:
        if not os.path.exists(p):
            continue
        txt = run(["du", "-sb", p], timeout=900)
        if txt:
            try:
                out[p] = int(txt.split()[0])
            except ValueError:
                pass
    return out


# -- strip check --------------------------------------------------------------

def has_debug(path):
    txt = run(["readelf", "-S", "-W", path], timeout=60)
    return txt is not None and ".debug_info" in txt


def strip_check():
    """Count shared objects that still carry DWARF debug info."""
    if not shutil.which("readelf"):
        return None
    groups = {}

    def scan(label, files):
        n = dbg = dbg_bytes = 0
        examples = []
        for f in files:
            if not os.path.isfile(f) or os.path.islink(f):
                continue
            n += 1
            if has_debug(f):
                dbg += 1
                dbg_bytes += os.path.getsize(f)
                if len(examples) < 5:
                    examples.append(f)
        groups[label] = {
            "files": n, "with_debug": dbg, "with_debug_bytes": dbg_bytes,
            "examples": examples,
        }

    libdir = "/usr/local/lib"
    if os.path.isdir(libdir):
        scan("usr_local_lib", [
            os.path.join(libdir, f) for f in sorted(os.listdir(libdir))
            if re.match(r"lib.*\.so", f)
        ])
    def r_libs(site):
        files = []
        for pkg in sorted(os.listdir(site)):
            d = os.path.join(site, pkg, "libs")
            if os.path.isdir(d):
                files += [os.path.join(d, f) for f in os.listdir(d)
                          if f.endswith(".so")]
        return files

    site = "/usr/local/lib/R/site-library"
    if os.path.isdir(site):
        scan("r_site_library", r_libs(site))
    cp = conda_prefix()
    if cp:
        lib = os.path.join(cp, "lib")
        scan("conda_lib", [os.path.join(lib, f) for f in sorted(os.listdir(lib))
                           if re.match(r"lib.*\.so", f)])
        rlib = os.path.join(cp, "lib", "R", "library")
        if os.path.isdir(rlib):
            scan("conda_r_library", r_libs(rlib))
    return groups


# -- shared-library census ----------------------------------------------------

def census():
    """Load the stack in-process and record which shared libraries get mapped.

    Python side: osgeo plus whatever geo packages are installed.
    R side (if R exists): gdalraster/sf/terra/vapour, and through reticulate
    the same Python modules, since that mixed process is where duplicate
    libraries bite.
    """
    out = {}
    py = os.path.join(HERE, "census.py")
    txt = run([sys.executable, py], timeout=600)
    out["python"] = json.loads(txt) if txt else None
    if shutil.which("Rscript"):
        r = os.path.join(HERE, "census.R")
        env = dict(os.environ)
        env["CENSUS_PY"] = py
        txt = run(["Rscript", r], timeout=900, env=env)
        try:
            out["r"] = json.loads(txt.splitlines()[-1]) if txt else None
        except (ValueError, IndexError):
            out["r"] = None
    else:
        out["r"] = None
    return out


# -- drivers ------------------------------------------------------------------

KEY_DRIVERS = [
    "GTiff", "COG", "VRT", "Zarr", "netCDF", "HDF5", "HDF4", "KEA", "GRIB",
    "JP2OpenJPEG", "WEBP", "PNG", "JPEG", "PDF", "FITS", "PostGISRaster",
    "GPKG", "SQLite", "Parquet", "Arrow", "PostgreSQL", "MySQL", "LIBKML",
    "GeoJSON", "FlatGeobuf", "ESRI Shapefile", "XLSX", "ADBC",
]


def drivers():
    names = []
    for cmd in (["gdalinfo", "--formats"], ["ogrinfo", "--formats"]):
        txt = run(cmd)
        if not txt:
            continue
        for line in txt.splitlines()[1:]:
            m = re.match(r"\s*(.+?)\s+-(raster|vector|multidimensional)", line)
            if m:
                names.append(m.group(1).strip())
    if not names:
        return None
    present = set(names)
    return {
        "count": len(present),
        "key": {d: (d in present) for d in KEY_DRIVERS},
    }


def main():
    report = {
        "conda_prefix": conda_prefix(),
        "versions": versions(),
        "py_packages": py_packages(),
        "r_packages": r_packages(),
        "du": du(),
        "strip": strip_check(),
        "census": census(),
        "drivers": drivers(),
    }
    json.dump(report, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
