# Migrating gdal-builds to use hypertidy/gdal-r-ci base images

## Current State (gdal-builds)

- Starts from rocker/verse
- Builds GDAL from source (slow, ~1hr)
- Installs 100+ R packages
- Installs Python stack
- Results in 6-7GB image

## Target State

- Start from `ghcr.io/hypertidy/gdal-r-python:latest`
- Add only the extra packages needed for AAD workflows
- Much faster builds (base image is pre-built)
- Clearer separation of concerns

## New Dockerfile for gdal-builds

```dockerfile
# ghcr.io/mdsumner/gdal-builds:rocker-gdal-dev-python
# Extended R+Python environment for AAD workflows
# Builds on hypertidy/gdal-r-python which provides:
#   - Bleeding-edge GDAL from osgeo
#   - R with core geo packages (terra, sf, gdalraster, vapour, stars)
#   - Python geo stack (rasterio, geopandas, xarray, etc.)

FROM ghcr.io/hypertidy/gdal-r-python:latest

LABEL org.opencontainers.image.source="https://github.com/mdsumner/gdal-builds"

# Additional system libraries for extended packages
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    librdf0-dev \
    libraptor2-dev \
    librasqal3-dev \
    openjdk-11-jdk \
    && rm -rf /var/lib/apt/lists/*

# Extended R packages for AAD workflows
RUN Rscript -e "\
    install.packages(c( \
        # Tidyverse ecosystem \
        'tidyverse', \
        # AAD-specific packages \
        'remotes' \
    ), Ncpus = parallel::detectCores()); \
    remotes::install_github(c( \
        'AustralianAntarcticDivision/blueant', \
        'AustralianAntarcticDivision/raadtools', \
        'AustralianAntarcticDivision/raadfiles', \
        'AustralianAntarcticDivision/palr', \
        'hypertidy/whatarelief', \
        'hypertidy/sds', \
        'hypertidy/dsn', \
        'hypertidy/PROJ', \
        'hypertidy/ximage' \
    ))"

# Extended Python packages
RUN pip3 install --break-system-packages --no-cache-dir \
    stackstac \
    pystac \
    pystac-client \
    odc-geo \
    planetary-computer

# RStudio Server (optional - makes image much larger)
# Uncomment if needed for interactive use
# RUN apt-get update -qq && apt-get install -y --no-install-recommends \
#     gdebi-core \
#     && wget https://download2.rstudio.org/server/jammy/amd64/rstudio-server-2023.12.1-402-amd64.deb \
#     && gdebi --non-interactive rstudio-server-*.deb \
#     && rm rstudio-server-*.deb \
#     && rm -rf /var/lib/apt/lists/*

CMD ["R"]
```

## Migration Steps

1. **Phase 1: Test** (now)
   - Build new Dockerfile locally
   - Verify all AAD workflows work
   - Compare package versions

2. **Phase 2: Parallel** (1-2 weeks)
   - Push new image alongside existing
   - Update workflows to test both
   - Collect feedback

3. **Phase 3: Switch** 
   - Update main tag to use new base
   - Archive old Dockerfiles to `legacy/`
   - Update README

## What Gets Dropped

The new approach explicitly does NOT include these from the old gdal-builds:
- RStudio Server (add back if needed, but adds ~500MB)
- tidyverse pre-installed (install in derived images or on-demand)
- Legacy packages that aren't actively used

## Benefits

1. **Faster rebuilds** - base image is pre-built weekly
2. **Smaller diff** - only your additions, not all of GDAL
3. **Better alignment** - same GDAL as hypertidy packages use
4. **Clearer dependencies** - explicit package lists in config files
