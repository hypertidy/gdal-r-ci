# Building pyarrow against the system Arrow C++ in gdal-r-python

Goal: one `libarrow` per process. GDAL's Arrow/Parquet drivers already load
the Apache apt `libarrow.so.2500`; the pyarrow wheel bundles its own copy of
Arrow C++, so any process that touches both (reticulate, gdalxarray, any
Python that opens a Parquet via OGR) carries two Arrow runtimes. Building
pyarrow from source and linking the system libraries removes the second
copy, the same way the image already has one GDAL and one PROJ.

Applies to `docker/Dockerfile.gdal-r-python` in hypertidy/gdal-r-ci.

## 0. What is installed (as of 2026-09-04)

Gathered from the current `gdal-r-full` image:

```
pkg-config --modversion arrow      -> 25.0.1
pkg-config --variable=prefix arrow -> /usr
libdir                             -> /usr/lib/x86_64-linux-gnu
headers                            -> /usr/include/arrow/api.h present
cmake config                       -> /usr/lib/x86_64-linux-gnu/cmake/Arrow/ArrowOptions.cmake
```

Shared libraries present (SONAME 2500):

```
libarrow.so  libarrow_compute.so  libarrow_dataset.so  libarrow_acero.so  libparquet.so
```

NOT present (separate apt packages, not installed):

```
libarrow_flight*  libgandiva*  libarrow_cuda*  libarrow_substrait*
```

`ArrowOptions.cmake` records how Apache configured the *whole* build, not
which packages are installed. FLIGHT, GANDIVA and CUDA say ON there but the
libraries are absent, so the pyarrow flags for them must be 0. ORC, GCS,
AZURE and HDFS are compiled into `libarrow.so` itself and can be 1.

Confirmed from `ArrowOptions.cmake`: `ARROW_S3 ON` and
`PARQUET_REQUIRE_ENCRYPTION ON`. Both corresponding pyarrow flags are 1.

> **Arrow 26 change (2026-10):** pyarrow 26 does `find_package(ArrowS3 REQUIRED)`
> when `PYARROW_WITH_S3=1`. In the Apache apt repo for Arrow 26, S3 is still
> compiled into `libarrow.so` (pyarrow's `if(NOT ARROW_S3)` guard passes), but
> there is **no** standalone `ArrowS3` CMake config and no S3 dev package to
> install — `apt-cache search libarrow` lists only acero, compute, dataset and
> base dev. So the find_package can never be satisfied and the pyarrow source
> build fails at configure with `Could not find ... ArrowS3`. The fix is to set
> `PYARROW_WITH_S3=0` (done in `Dockerfile.gdal-r-python`); pyarrow loses only
> its own `pyarrow.fs.S3FileSystem`, while GDAL `/vsis3`, `s3fs` and `obstore`
> still provide S3 access. Under Arrow 25 S3 needed no separate config and the
> flag was 1 — the text above describes that older layout. GCS/Azure/HDFS have
> no separate CMake package; pyarrow only calls `find_package` for S3 and CUDA.

Confirmed in `gdal-r-full` that GDAL itself is on these libraries:

```
ldd $(gdal-config --prefix)/lib/libgdal.so | grep -E 'arrow|parquet'
  libarrow_dataset.so.2500 => /lib/x86_64-linux-gnu/libarrow_dataset.so.2500
  libparquet.so.2500       => /lib/x86_64-linux-gnu/libparquet.so.2500
  libarrow_compute.so.2500 => /lib/x86_64-linux-gnu/libarrow_compute.so.2500
  libarrow.so.2500         => /lib/x86_64-linux-gnu/libarrow.so.2500
  libarrow_acero.so.2500   => /lib/x86_64-linux-gnu/libarrow_acero.so.2500
ogrinfo --formats | grep -iE 'parquet|arrow'
  Parquet -vector- (rw+uv)   Arrow -vector- (rw+v)   ADBC -vector- (ro)
```

Dynamic links, no private copy, drivers compiled in rather than plugins.
Paths show as `/lib/...` because of Ubuntu merged-usr; `/lib` is a symlink
to `/usr/lib`, and `/proc/self/maps` may report either spelling.

The R `arrow` package is not installed in `gdal-r-full` (by design), so
pyarrow is the only remaining second copy of Arrow C++ in the image.

## 1. Rules that fall out of this

1. pyarrow major version must equal the Arrow C++ major version. libarrow 25
   means pyarrow 25.x, no exceptions. Patch versions need not match.
2. Every `PYARROW_WITH_*` flag must be <= what the installed libraries
   provide. Setting 1 for a missing component fails at link time, which is
   the failure mode we want.
3. pyarrow must be installed before anything that depends on it, or uv will
   satisfy the dependency with a wheel. In the current Dockerfile that means
   before `geoarrow-pyarrow`, `stac-geoparquet`, `ibis-framework`,
   `stackstac`, `kerchunk`, `virtualizarr`, `sedonadb`.
4. Set the flags explicitly. Recent pyarrow autodetects components from the
   Arrow cmake config when a flag is unset; given point 0 above that would
   try to enable Flight and Gandiva and fail.

## 2. Dockerfile changes

### 2a. Header comment

Move pyarrow from the WHEELS list to the MUST-build list:

```
# --no-binary policy:
#   MUST build from source (link system GDAL/PROJ/GEOS/Arrow):
#     rasterio, fiona, pyogrio, shapely, pyproj, geopandas, odc-geo, rioxarray,
#     pyarrow (links the apt libarrow/libparquet that GDAL's Parquet driver
#     already loads; a wheel would put a second Arrow C++ in the process.
#     pyarrow major version MUST equal the Arrow C++ major version.)
#   WHEELS fine (pure Python, Cython, or safely bundled):
#     pandas, xarray, zarr, fsspec, netCDF4, h5py/h5netcdf, scipy,
#     matplotlib, dask, polars, duckdb, fastparquet
```

polars, duckdb and sedonadb carry their own Arrow *implementations*
(Rust / C++), not libarrow, so they do not conflict and stay as wheels.

### 2b. Version constraint, derived at build time

Insert after `ARG IMAGE_VARIANT=release`. A bump of libarrow in gdal-system
then fails loudly here instead of silently pulling a mismatched wheel.

```dockerfile
# pyarrow must match the Arrow C++ major version installed in gdal-system.
RUN echo "pyarrow==$(pkg-config --modversion arrow | cut -d. -f1).*" \
        > /opt/pyarrow-constraint.txt \
 && cat /opt/pyarrow-constraint.txt
```

### 2c. Source-built pyarrow block

Insert before the tappa block (so it precedes the large wheel block).
Build deps are installed first and `--no-build-isolation` is used so the
extension compiles against the venv's numpy 2.x, same policy as the GDAL
bindings in gdal-system.

```dockerfile
# -- pyarrow: link system Arrow C++ (one libarrow per process) ----------------
# Flags mirror what the Apache apt packages actually install (see
# ArrowOptions.cmake plus ls of the libdir): core, compute, dataset, acero,
# parquet, plus ORC/S3/GCS/Azure/HDFS which are compiled into libarrow.so.
# Flight, Gandiva, CUDA, Substrait are separate debs that are not installed.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv pip install --python /opt/gdal-py/bin/python \
        cython "cmake>=3.25" ninja setuptools setuptools_scm \
 && ARROW_HOME=/usr \
    PYARROW_BUNDLE_ARROW_CPP=0 \
    PYARROW_PARALLEL=$(nproc) \
    PYARROW_WITH_PARQUET=1 \
    PYARROW_WITH_PARQUET_ENCRYPTION=1 \
    PYARROW_WITH_DATASET=1 \
    PYARROW_WITH_ACERO=1 \
    PYARROW_WITH_ORC=1 \
    PYARROW_WITH_S3=1 \
    PYARROW_WITH_GCS=1 \
    PYARROW_WITH_AZURE=1 \
    PYARROW_WITH_HDFS=1 \
    PYARROW_WITH_FLIGHT=0 \
    PYARROW_WITH_GANDIVA=0 \
    PYARROW_WITH_SUBSTRAIT=0 \
    PYARROW_WITH_CUDA=0 \
    uv pip install --python /opt/gdal-py/bin/python \
        --no-build-isolation \
        --no-binary pyarrow \
        --constraint /opt/pyarrow-constraint.txt \
        pyarrow \
 && find /opt/gdal-py -type d -name __pycache__ -exec rm -rf {} +
```

Notes:

- `ARROW_HOME=/usr` is belt and braces; cmake finds `/usr` by default.
- `PYARROW_PARALLEL` matters, the build is 10-15 min single threaded and
  roughly 3-5 min with a modern core count.
- `libarrow_python` is built as part of pyarrow itself; `ARROW_PYTHON=OFF`
  in the C++ build is expected and fine.
- No RPATH work needed: `/usr/lib/x86_64-linux-gnu` is on the default
  loader path.

### 2d. Guard the existing wheel block

In the large `uv pip install`, remove `pyarrow` from the package list and
add the constraint and `--no-binary pyarrow` so a resolver decision can
never swap in a wheel:

```dockerfile
 && uv pip install --python /opt/gdal-py/bin/python \
        --no-build-isolation-package imagecodecs-numcodecs \
        --constraint /opt/pyarrow-constraint.txt \
        --no-binary pyarrow \
        build \
        pandas xarray scipy matplotlib cftime pytz tzdata \
        ...
        polars "ibis-framework[duckdb]" \
        ...
```

### 2e. Verification

Add directly after the pyarrow block, or fold into
`scripts/check-python-versions.py` (preferred, it already gates the release
variant). Three checks: version parity, nothing bundled, exactly one
libarrow mapped when both GDAL and pyarrow are loaded, in either order.

```dockerfile
# GDAL first, then pyarrow (the reticulate / gdalxarray order)
RUN <<'EOF' /opt/gdal-py/bin/python
import re, subprocess, pathlib
from osgeo import gdal
import pyarrow as pa
import pyarrow.parquet, pyarrow.dataset

cpp = subprocess.check_output(["pkg-config", "--modversion", "arrow"], text=True).strip()
print(f"pyarrow {pa.__version__}  cpp {pa.cpp_version}  system {cpp}")
assert pa.cpp_version.split(".")[0] == cpp.split(".")[0], "pyarrow/libarrow major mismatch"

pkg = pathlib.Path(pa.__file__).parent
bundled = list(pkg.glob("libarrow*.so*")) + list(pkg.glob("libparquet*.so*"))
assert not bundled, f"bundled Arrow C++ found: {bundled}"

maps = open("/proc/self/maps").read()
libs = sorted({m for m in re.findall(r"\S*libarrow\.so\S*", maps)})
print("libarrow mapped:", libs)
SYSLIB = ("/usr/lib/x86_64-linux-gnu/", "/lib/x86_64-linux-gnu/")  # merged-usr
assert len(libs) == 1 and libs[0].startswith(SYSLIB), libs
EOF

# pyarrow first, then GDAL's Parquet driver
RUN <<'EOF' /opt/gdal-py/bin/python
import re
import pyarrow as pa
from osgeo import gdal, ogr
assert ogr.GetDriverByName("Parquet") is not None, "GDAL lacks Parquet driver"
libs = {m for m in re.findall(r"\S*libarrow\.so\S*", open("/proc/self/maps").read())}
assert len(libs) == 1, libs
print("ok: single libarrow with pyarrow loaded first")
EOF
```

Optional stronger check for the canary: write a table with
`pyarrow.parquet.write_table`, open it with `ogr.Open`, then the reverse via
`gdal.VectorTranslate(..., format="Parquet")` and `pyarrow.parquet.read_table`.

### 2f. MOTD

Add Arrow to the Python line:

```dockerfile
echo "Py   $(/opt/gdal-py/bin/python -c 'import sys; print(sys.version.split()[0])')   numpy $(/opt/gdal-py/bin/python -c 'import numpy; print(numpy.__version__)')   pyarrow $(/opt/gdal-py/bin/python -c 'import pyarrow; print(pyarrow.__version__)') (libarrow $(pkg-config --modversion arrow))" ; \
```

## 3. The R side (not needed today)

R `arrow` is deliberately not installed in `gdal-r-full`, so this section
is for reference only. If it is ever added, it bundles its own libarrow and
a reticulate session would carry two copies again. Same fix, same version
rule (R arrow 25.x for libarrow 25):

```r
Sys.setenv(LIBARROW_BINARY = "false",
           ARROW_USE_PKG_CONFIG = "true",
           ARROW_R_DEV = "false")
install.packages("arrow", type = "source")
```

`nanoarrow` and `geoarrow` for R do not link libarrow and are unaffected.

Quick check that any R process still has a single libarrow (uses `sf` to
pull libgdal in; `gdalraster` or `vapour` work equally):

```sh
Rscript -e '
  library(sf); x <- sf::st_drivers()
  m <- grep("libarrow\\.so", readLines("/proc/self/maps"), value = TRUE)
  print(unique(sub(".*\\s(/\\S+)$", "\\1", m)))'
```

## 4. Things likely to bite

- **Adding Flight or Gandiva later.** Install `libarrow-flight-dev` /
  `libgandiva-dev` in gdal-system, then flip the flags. Do not flip the
  flags without the packages.
- **`:dev` variant.** If gdal-system ever switches from apt to building
  Arrow from main, `pkg-config` returns e.g. `26.0.0-SNAPSHOT`, the
  constraint becomes `26.*`, and no such sdist exists on PyPI. pyarrow would
  then have to come from `pip install ./arrow/python` out of the same
  checkout gdal-system built from. Not an issue while Arrow comes from apt.
- **Version bumps.** A gdal-system bump of the Arrow apt packages changes
  the constraint file, which invalidates the pyarrow layer and everything
  after it. That is the intended coupling.
- **pyarrow patch lag.** pyarrow patch releases do not always track C++
  patch releases one to one; `25.*` covers this, the ABI contract is the
  SONAME `libarrow.so.2500`.
