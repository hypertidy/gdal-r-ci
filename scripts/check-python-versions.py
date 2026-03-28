from osgeo import gdal, ogr, osr
import rasterio, fiona, pyproj, shapely, geopandas
import xarray, zarr, fsspec, netCDF4, h5py
import numpy, pandas, scipy

# Critical: osgeo and rasterio must agree on GDAL version
osgeo_ver = gdal.__version__
rasterio_gdal = rasterio.__gdal_version__

print('=== Version check ===')
print(f'osgeo.gdal:    {osgeo_ver}')
print(f'rasterio GDAL: {rasterio_gdal}')

if osgeo_ver != rasterio_gdal:
    print(f'WARNING: GDAL version mismatch! osgeo={osgeo_ver} rasterio={rasterio_gdal}')
else:
    print('GDAL alignment: OK')

print()
print('=== Package versions ===')
print(f'numpy:      {numpy.__version__}')
print(f'rasterio:   {rasterio.__version__}')
print(f'fiona:      {fiona.__version__}')
print(f'pyproj:     {pyproj.__version__}')
print(f'shapely:    {shapely.__version__}')
print(f'geopandas:  {geopandas.__version__}')
print(f'xarray:     {xarray.__version__}')
print(f'zarr:       {zarr.__version__}')
print(f'netCDF4:    {netCDF4.__version__}')
print(f'h5py:       {h5py.__version__}')
print(f'pandas:     {pandas.__version__}')

# pyarrow: may have abseil ABI conflict with system libabsl-dev (installed for R s2 package)
# Import separately so failure here doesn't mask the above checks
try:
    import pyarrow
    print(f'pyarrow:    {pyarrow.__version__}')
except ImportError as e:
    print(f'pyarrow:    IMPORT FAILED (abseil ABI conflict likely) — {e}')

try:
    import polars
    print(f'polars:     {polars.__version__}')
except ImportError as e:
    print(f'polars:     IMPORT FAILED — {e}')
