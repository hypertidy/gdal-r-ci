# gdal-r-ci

Continuous integration infrastructure for R packages against bleeding-edge GDAL.

## Docker Images

Pre-built images on GHCR, rebuilt weekly to track `osgeo/gdal:ubuntu-full-latest`:

| Image | Description | Size |
|-------|-------------|------|
| `ghcr.io/hypertidy/gdal-r:latest` | R + system libs + PROJ fix | ~2GB |
| `ghcr.io/hypertidy/gdal-r-full:latest` | + gdalraster + optional: gdalcubes, sf, terra, vapour | ~3GB |
| `ghcr.io/hypertidy/gdal-r-python:latest` | + Python geo stack (rasterio, geopandas, etc.) | ~4GB |

### Quick Start

```bash
# Interactive R session with bleeding-edge GDAL
docker run --rm -ti ghcr.io/hypertidy/gdal-r-full:latest

# Check your package against latest GDAL
docker run --rm -v $(pwd):/pkg ghcr.io/hypertidy/gdal-r:latest \
  bash -c "cd /pkg && R CMD build . && R CMD check *.tar.gz"
```

### Image Hierarchy

```
ghcr.io/osgeo/gdal:ubuntu-full-latest    # GDAL team maintains
           │
           ▼
ghcr.io/hypertidy/gdal-r:latest          # + R, system libs, PROJ fix
           │                              # + minimal R packages (explicit)
           ▼
ghcr.io/hypertidy/gdal-r-full:latest     # + gdalraster, gdalcubes, sf, terra, vapour
           │                              # Use this for package CI
           ▼
ghcr.io/hypertidy/gdal-r-python:latest   # + Python geo stack
                                          # Use for R/Python interop
```

## Reusable Workflow for Package CI

Add to your package's `.github/workflows/`:

```yaml
name: Check GDAL Latest

on:
  schedule:
    - cron: '0 3 * * 0'  # Weekly
  workflow_dispatch:

jobs:
  gdal-latest:
    uses: hypertidy/gdal-r-ci/.github/workflows/check-gdal-latest.yml@main
```

See [examples/](examples/) for more options.

## Scheduled Checks

The CRAN-5 packages are tested fortnightly:

- [gdalraster](https://github.com/firelab/gdalraster)
- [gdalcubes](https://github.com/appelmar/gdalcubes)
- [terra](https://github.com/rspatial/terra)
- [sf](https://github.com/r-spatial/sf)
- [vapour](https://github.com/hypertidy/vapour)

Results create issues in this repo on failure.

## Package Manifests

The R packages installed in each image are **explicit** (no kitchen sink):

- [`config/r-packages-base.txt`](config/r-packages-base.txt) - Base image packages
- [`config/r-packages-required.txt`](config/r-packages-required.txt) - Geo packages in -full
- [`config/r-packages-optional.txt`](config/r-packages-optional.txt) - Geo packages in -full + required r-packages
- [`config/python-packages.txt`](config/python-packages.txt) - Python packages

Edit these files to change what's pre-installed.

## Version Alignment

**All packages link to the exact same GDAL/PROJ/GEOS.** No exceptions.

We enforce this by:
1. Building all packages from source (no binaries from pak/r2u/RSPM)
2. Running explicit version checks during image build
3. Failing the build if versions don't match

```bash
# Run version checks manually
docker run --rm ghcr.io/hypertidy/gdal-r-full:latest \
  Rscript /opt/scripts/check-r-versions.R

docker run --rm ghcr.io/hypertidy/gdal-r-python:latest \
  python3 /opt/scripts/check-python-versions.py
```

See [docs/library-alignment.md](docs/library-alignment.md) for the full rationale.

### The osgeo Bindings

The Python bindings (`osgeo.gdal`, `osgeo.ogr`, `osgeo.osr`) come from the GDAL build itself - they're already in the osgeo/gdal base image. We do NOT `pip install GDAL`. Other packages (rasterio, fiona) are built from source with `--no-binary` to ensure they link the same GDAL.

## Technical Details

### Upstream: osgeo/gdal Docker Images

We build on top of `ghcr.io/osgeo/gdal:ubuntu-full-latest`. Here's what you need to know about the upstream:

**Source locations in [OSGeo/gdal](https://github.com/OSGeo/gdal):**
```
docker/
├── ubuntu-full/
│   ├── Dockerfile      # The actual image definition
│   └── build.sh        # Local build script
├── ubuntu-small/       # Lighter variant
├── alpine-small/       # Alpine-based
├── alpine-normal/
└── README.md           # Documents all variants

.github/workflows/
├── linux_build.yml     # Main CI workflow - builds/pushes docker images on push to master
└── ...
```

**Build triggers:** The `:latest` images are rebuilt on every push to master (not scheduled - they track HEAD). The `linux_build.yml` workflow handles both CI testing and pushing updated images to GHCR. Tagged release images (e.g., `ubuntu-full-3.10.1`) are built on version tags.

**Key characteristics of ubuntu-full:**
- Base: `ubuntu:24.04`
- Python: 3.12 with osgeo bindings installed to `/usr/lib/python3/dist-packages/osgeo/`
- PROJ: Internal (renamed symbols) + system PROJ from Ubuntu
- All drivers enabled, including proprietary ones (FileGDB, Oracle, etc.)
- ~2GB compressed

**Registry:** Images moved from Docker Hub to GitHub Container Registry:
- Old: `docker pull osgeo/gdal:ubuntu-full-latest` (deprecated)
- New: `docker pull ghcr.io/osgeo/gdal:ubuntu-full-latest`

**Useful links:**
- [GDAL Docker README](https://github.com/OSGeo/gdal/tree/master/docker)
- [Package registry](https://github.com/OSGeo/gdal/pkgs/container/gdal)
- [ubuntu-full Dockerfile](https://github.com/OSGeo/gdal/blob/master/docker/ubuntu-full/Dockerfile)

### The PROJ Symlink Fix

The osgeo/gdal image has a clever dual-PROJ setup (internal PROJ with renamed symbols for GDAL, system PROJ for everything else). However, system PROJ only provides `libproj.so.25` without the standard `.so` symlink. Packages like terra and sf that link PROJ directly need:

```bash
ln -sf /lib/x86_64-linux-gnu/libproj.so.25 /lib/x86_64-linux-gnu/libproj.so
```

This is done automatically in our images.

### Why Not Build GDAL from Source?

The osgeo/gdal images are:
- Built by the GDAL team themselves
- Updated frequently (often nightly)
- Include all drivers and dependencies properly configured
- Much faster than building from source in CI

We add R on top rather than rebuilding GDAL.

## Related Projects

- [mdsumner/gdal-builds](https://github.com/mdsumner/gdal-builds) - Extended images with more R/Python packages (builds on these images)
- [mdsumner/gdalcheck](https://github.com/mdsumner/gdalcheck) - Reverse dependency checking infrastructure (future integration planned)
- [osgeo/gdal](https://github.com/OSGeo/gdal) - GDAL source and Docker images

## Documentation

- [docs/library-alignment.md](docs/library-alignment.md) - Why we build from source, the PROJ wrinkle, osgeo bindings
- [docs/gdal-builds-migration.md](docs/gdal-builds-migration.md) - How to migrate gdal-builds to use these base images
- [docs/gdalcheck-roadmap.md](docs/gdalcheck-roadmap.md) - Future plans for reverse dependency checking

## License

MIT
