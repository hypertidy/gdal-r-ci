# conda-gdal-python: Ubuntu + Miniforge + GDAL/Python from conda-forge
#
# Usage:
#   docker build -t conda-gdal-python .
#   docker build --build-arg GDAL_SPEC="gdal=3.9" -t conda-gdal-python:3.9 .
#
# Run:
#   docker run -it --rm -v $(pwd):/work conda-gdal-python

FROM ubuntu:24.04

ARG PYTHON_VERSION=3.12
ARG GDAL_SPEC=gdal

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install minimal system deps for Miniforge
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        wget \
        git \
        && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Miniforge (conda-forge focused conda)
ENV CONDA_DIR=/opt/conda
ENV PATH="${CONDA_DIR}/bin:${PATH}"

RUN curl -fsSL https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -o /tmp/miniforge.sh && \
    bash /tmp/miniforge.sh -b -p ${CONDA_DIR} && \
    rm /tmp/miniforge.sh && \
    conda clean -afy

# Install GDAL and Python from conda-forge
RUN conda install -y -c conda-forge \
        python=${PYTHON_VERSION} \
        ${GDAL_SPEC} \
        proj \
        && \
    conda clean -afy

# Verify installation
RUN gdalinfo --version && \
    python -c "from osgeo import gdal; print(f'GDAL Python: {gdal.__version__}')" && \
    proj 2>&1 | head -1

# Set working directory
WORKDIR /work

# Default command
CMD ["bash"]
