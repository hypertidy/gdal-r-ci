# Library Version Alignment Philosophy

## The Core Principle

**Every R or Python package that links to GDAL, PROJ, or GEOS must link to the exact same version.**

This is non-negotiable. Version mismatches can cause:
- Silent data corruption (different projection handling)
- Crashes (ABI incompatibility)
- Subtle behavioral differences that are hard to debug

## Why We Build From Source (Not pak/r2u)

Hybrid approaches that mix pre-built binaries with source builds are dangerous:

1. **r2u** provides CRAN packages as Ubuntu binaries, but they're built against Ubuntu's system GDAL (e.g., 3.4.x), not bleeding-edge GDAL (3.10.x)

2. **pak** with binary fallback might pull a binary built against GDAL 3.8 while we have GDAL 3.10

3. **pip wheels** for rasterio/fiona often bundle their own GDAL, creating version skew

The only safe approach: **build everything from source against the same libraries**.

Yes, this is slower. That's why we pre-build images weekly.

## The GDAL/PROJ/GEOS Stack

```
┌─────────────────────────────────────────────────────────────┐
│ GEOS (geometry engine)                                       │
│  - Used by: sf, terra, shapely, GDAL itself                 │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│ PROJ (coordinate transformations)                            │
│  - Used by: sf, terra, GDAL, pyproj, rasterio               │
│  - Note: osgeo/gdal image has INTERNAL PROJ with renamed    │
│    symbols - GDAL uses that, R/Python use system PROJ       │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│ GDAL (raster/vector I/O, format drivers)                    │
│  - Used by: everything                                       │
│  - Provides: osgeo.gdal Python bindings (built with GDAL)   │
└─────────────────────────────────────────────────────────────┘
```

## The osgeo.gdal Bindings Situation

### How They Work

The official Python bindings (`osgeo.gdal`, `osgeo.ogr`, `osgeo.osr`) are:

1. **Built as part of GDAL itself** (not a separate pip package)
2. **Installed to a specific Python path during GDAL's cmake install**
3. **Tightly coupled to the GDAL version** - must match exactly

In the osgeo/gdal Docker image:
```
/usr/lib/python3/dist-packages/osgeo/
├── __init__.py
├── gdal.py
├── ogr.py
├── osr.py
└── _gdal.cpython-312-x86_64-linux-gnu.so  # The actual bindings
```

### The GDAL-from-pip Problem

If you `pip install GDAL`, you get:
- A **different** build of the bindings
- Possibly against a **different** GDAL version
- **Conflicts** with the system GDAL that R packages link to

**Never pip install GDAL in our images.** Use the bindings that come with GDAL.

### Verifying osgeo Bindings

```python
from osgeo import gdal
print(gdal.VersionInfo('RELEASE_NAME'))  # Should match gdal-config --version
```

If these don't match, the environment is broken.

## The PROJ Internal Symbols Wrinkle

The osgeo/gdal image has a clever but confusing setup:

```
/usr/local/gdal-internal/lib/libinternalproj.so
  - PROJ 9.8.0 (bleeding edge)
  - All symbols renamed: proj_* → internal_proj_*
  - Used by GDAL internally

/lib/x86_64-linux-gnu/libproj.so.25
  - PROJ 9.4.0 (Ubuntu's version)
  - Standard symbols
  - Used by R packages (sf, terra) and Python packages (pyproj, rasterio)
```

This means:
- **GDAL** uses internal PROJ 9.8.0
- **R/Python packages** use system PROJ 9.4.0
- They can coexist because symbols don't conflict

For our purposes (testing GDAL API compatibility), this is fine. We're primarily testing GDAL, and PROJ 9.4 vs 9.8 differences are usually minor.

### Linux Shared Library Versioning (sonames)

Understanding Linux library versioning helps debug linking issues:

```
libproj.so.25.9.8.0
    │     │  │ │ │
    │     │  └─┴─┴── minor/patch (API-compatible changes)
    │     └────────── soname/ABI version (increments on incompatible changes)
    └──────────────── library name

Symlink chain:
libproj.so      → libproj.so.25        (linker uses: -lproj)
libproj.so.25   → libproj.so.25.9.8.0  (runtime loader uses)
libproj.so.25.9.8.0                    (actual file)
```

The **soname** (e.g., `25`) changes when the library breaks ABI compatibility:

| PROJ version | soname |
|--------------|--------|
| 6.x | 15 |
| 7.x | 19 |
| 8.x | 22 |
| 9.0–9.4+ | 25 |

When PROJ 10 ships, expect soname 26+. The symlink fix in Dockerfile.gdal-r currently hardcodes `libproj.so.25` - this will need updating. A future improvement would detect dynamically:

```bash
ln -sf $(ls /lib/x86_64-linux-gnu/libproj.so.* 2>/dev/null | head -1) /lib/x86_64-linux-gnu/libproj.so
```

### The Missing Symlink

System PROJ only provides `libproj.so.25`, not the standard `libproj.so` symlink. Packages that link with `-lproj` fail to find it. Our fix:

```bash
ln -sf /lib/x86_64-linux-gnu/libproj.so.25 /lib/x86_64-linux-gnu/libproj.so
ldconfig
```

## Version Check Scripts

We include explicit checks that verify alignment:

- `scripts/check-r-versions.R` - Verifies sf, terra, gdalraster, vapour all see same GDAL/PROJ/GEOS
- `scripts/check-python-versions.py` - Verifies osgeo.gdal, rasterio, fiona, pyproj, shapely alignment

These run during image build and can be run anytime:

```bash
docker run --rm ghcr.io/hypertidy/gdal-r-full:latest Rscript /opt/scripts/check-r-versions.R
docker run --rm ghcr.io/hypertidy/gdal-r-python:latest python3 /opt/scripts/check-python-versions.py
```

## What If Versions Don't Match?

If the checks fail, something is wrong:

1. **pip installed a wheel with bundled GDAL** - Remove it, install with `--no-binary`
2. **A package was installed from r2u/RSPM** - Reinstall from source
3. **System libraries changed after package install** - Reinstall all packages

The nuclear option: rebuild the image from scratch.

## Future Considerations

### Python Virtual Environments

If we need tighter control, we could:
```bash
python3 -m venv /opt/geo-env --system-site-packages
source /opt/geo-env/bin/activate
pip install --no-binary :all: rasterio fiona  # Force source build
```

The `--system-site-packages` flag lets the venv see the osgeo bindings.

### Multiple GDAL Versions

For testing against multiple GDAL versions, we'd need separate images:
- `gdal-r:3.9` 
- `gdal-r:3.10`
- `gdal-r:latest` (bleeding edge)

This is future work - for now we only track latest.
