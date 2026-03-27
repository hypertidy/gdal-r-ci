from osgeo import gdal, ogr, osr
import rasterio, fiona, pyproj, shapely, geopandas
import xarray, zarr, fsspec, netCDF4, h5py

print('osgeo.gdal: ', gdal.__version__)
print('rasterio:   ', rasterio.__version__)
print('fiona:      ', fiona.__version__)
print('pyproj:     ', pyproj.__version__)
print('shapely:    ', shapely.__version__)
print('geopandas:  ', geopandas.__version__)
print('xarray:     ', xarray.__version__)
print('zarr:       ', zarr.__version__)
print('netCDF4:    ', netCDF4.__version__)
print('h5py:       ', h5py.__version__)
