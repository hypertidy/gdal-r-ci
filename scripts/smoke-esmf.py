"""Smoke test for gdal-r-esmf: one small global conservative map from each of
xESMF (ESMPy), ESMF_RegridWeightGen and TempestRemap. Every map must
preserve a constant field (rows of the weight matrix sum to 1). Run in a
scratch directory; it writes a few small netCDF files there."""

import subprocess

import netCDF4
import numpy as np

TOL = 1e-10


def check_rows(name, S, row, n_b):
    sums = np.bincount(row - 1, weights=S, minlength=n_b)
    err = np.abs(sums - 1).max()
    print(f"{name}: {S.size} weights, {n_b} destination cells, max |row sum - 1| = {err:.2e}")
    assert err < TOL, f"{name}: constant field not preserved"


def read_map(path):
    with netCDF4.Dataset(path) as ds:
        return (ds["S"][:].data, ds["row"][:].data,
                ds.dimensions["n_b"].size)


# -- xESMF / ESMPy ------------------------------------------------------------
import esmpy
import xesmf as xe

print(f"esmpy {esmpy.__version__}, xesmf {xe.__version__}")
src = xe.util.grid_global(10, 10)
dst = xe.util.grid_global(15, 12)
regridder = xe.Regridder(src, dst, "conservative")
w = regridder.weights.data  # sparse COO, (n_b, n_a)
check_rows("xesmf", w.data, w.coords[0] + 1, w.shape[0])


# -- ESMF_RegridWeightGen -----------------------------------------------------
def write_scrip(path, dlon, dlat):
    """Global regular lat/lon grid as SCRIP, corners counterclockwise."""
    lon_e = np.arange(-180, 180 + dlon / 2, dlon)
    lat_e = np.arange(-90, 90 + dlat / 2, dlat)
    nx, ny = lon_e.size - 1, lat_e.size - 1
    lon0, lat0 = np.meshgrid(lon_e[:-1], lat_e[:-1])
    lon1, lat1 = np.meshgrid(lon_e[1:], lat_e[1:])
    corner_lon = np.stack([lon0, lon1, lon1, lon0], -1).reshape(-1, 4)
    corner_lat = np.stack([lat0, lat0, lat1, lat1], -1).reshape(-1, 4)
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("grid_size", nx * ny)
        ds.createDimension("grid_corners", 4)
        ds.createDimension("grid_rank", 2)
        ds.createVariable("grid_dims", "i4", ("grid_rank",))[:] = [nx, ny]
        for name, val in [("grid_center_lon", corner_lon.mean(1)),
                          ("grid_center_lat", corner_lat.mean(1))]:
            v = ds.createVariable(name, "f8", ("grid_size",))
            v.units = "degrees"
            v[:] = val
        for name, val in [("grid_corner_lon", corner_lon),
                          ("grid_corner_lat", corner_lat)]:
            v = ds.createVariable(name, "f8", ("grid_size", "grid_corners"))
            v.units = "degrees"
            v[:] = val
        ds.createVariable("grid_imask", "i4", ("grid_size",))[:] = 1


write_scrip("src_scrip.nc", 10, 10)
write_scrip("dst_scrip.nc", 15, 12)
subprocess.run(["ESMF_RegridWeightGen", "--source", "src_scrip.nc",
                "--destination", "dst_scrip.nc", "--weight", "esmf_map.nc",
                "--method", "conserve", "--no_log"],
               check=True, stdout=subprocess.DEVNULL)
check_rows("ESMF_RegridWeightGen", *read_map("esmf_map.nc"))


# -- TempestRemap -------------------------------------------------------------
def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


run("GenerateRLLMesh", "--lon", "36", "--lat", "18", "--file", "src.g")
run("GenerateRLLMesh", "--lon", "24", "--lat", "15", "--file", "dst.g")
run("GenerateOverlapMesh", "--a", "src.g", "--b", "dst.g", "--out", "ov.g")
run("GenerateOfflineMap", "--in_mesh", "src.g", "--out_mesh", "dst.g",
    "--ov_mesh", "ov.g", "--in_np", "1", "--out_map", "tr_map.nc")
check_rows("TempestRemap", *read_map("tr_map.nc"))

print("gdal-r-esmf smoke test passed")
