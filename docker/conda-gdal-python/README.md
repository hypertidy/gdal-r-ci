# Docker Images

## conda-gdal-python

Ubuntu 24.04 + Miniforge + GDAL/Python from conda-forge.

### Pull from ghcr.io

```bash
# Latest GDAL
docker pull ghcr.io/hypertidy/conda-gdal-python:latest

# Specific GDAL version (when available)
docker pull ghcr.io/hypertidy/conda-gdal-python:gdal-3.9
```

### Run

```bash
# Interactive shell with current dir mounted
docker run -it --rm -v $(pwd):/work ghcr.io/hypertidy/conda-gdal-python

# One-off command
docker run --rm ghcr.io/hypertidy/conda-gdal-python gdalinfo --version

# Python with GDAL
docker run --rm ghcr.io/hypertidy/conda-gdal-python python -c "from osgeo import gdal; print(gdal.__version__)"
```

### Build locally

```bash
cd docker/conda-gdal-python

# Latest GDAL
docker build -t conda-gdal-python .

# Specific GDAL version
docker build --build-arg GDAL_SPEC="gdal=3.9" -t conda-gdal-python:3.9 .

# Specific Python version
docker build --build-arg PYTHON_VERSION=3.11 -t conda-gdal-python:py311 .
```

### Why conda-forge?

- Single coherent PROJ setup (no dual-PROJ issues like osgeo images)
- Easy version pinning
- Consistent with many scientific Python workflows
- Good for testing R packages that need to link against GDAL/PROJ

### Contents

- Ubuntu 24.04 base
- Miniforge (conda-forge focused conda distribution)
- GDAL with Python bindings
- PROJ
- Working directory: `/work`
