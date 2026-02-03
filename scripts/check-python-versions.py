#!/usr/bin/env python3
"""
check-python-versions.py
Verify all Python packages link to the same GDAL/PROJ/GEOS versions

The osgeo bindings (osgeo.gdal, osgeo.ogr, osgeo.osr) are the ground truth -
they're built with GDAL itself and installed at GDAL build time.
All other packages (rasterio, fiona, pyogrio, etc.) should link to the same libraries.
"""

import subprocess
import sys

def get_system_version(cmd):
    """Get version from system command"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except:
        return None

def normalize_version(v):
    """Strip build metadata for comparison"""
    if v is None:
        return None
    # Remove -dev, dev, and anything after
    import re
    v = re.sub(r'[-.]?dev.*$', '', v, flags=re.IGNORECASE)
    v = re.sub(r'-.*$', '', v)
    return v

print("=== Python Package Library Version Alignment Check ===\n")

# System versions (ground truth)
system_gdal = get_system_version(['gdal-config', '--version'])
system_proj = get_system_version(['pkg-config', '--modversion', 'proj'])
system_geos = get_system_version(['geos-config', '--version'])

print("System libraries (ground truth):")
print(f"  GDAL: {system_gdal}")
print(f"  PROJ: {system_proj}")
print(f"  GEOS: {system_geos}")
print()

# Collect versions from packages
results = {}

# osgeo.gdal - THE ground truth for Python GDAL bindings
# These are built WITH GDAL, not installed via pip
try:
    from osgeo import gdal, ogr, osr
    results['osgeo.gdal'] = {
        'GDAL': gdal.VersionInfo('RELEASE_NAME'),
        'PROJ': None,  # GDAL bindings don't expose PROJ version directly
        'GEOS': None,
    }
except ImportError as e:
    print(f"WARNING: osgeo.gdal not available: {e}")
    print("This is unexpected in the osgeo/gdal image!")

# rasterio
try:
    import rasterio
    results['rasterio'] = {
        'GDAL': rasterio.gdal_version(),
        'PROJ': rasterio.proj_version(),
        'GEOS': None,
    }
except ImportError:
    pass
except AttributeError:
    # Older rasterio might not have proj_version
    results['rasterio'] = {
        'GDAL': rasterio.gdal_version(),
        'PROJ': None,
        'GEOS': None,
    }

# fiona
try:
    import fiona
    results['fiona'] = {
        'GDAL': fiona.gdal_version(),
        'PROJ': fiona.proj_version() if hasattr(fiona, 'proj_version') else None,
        'GEOS': None,
    }
except ImportError:
    pass

# pyogrio
try:
    import pyogrio
    results['pyogrio'] = {
        'GDAL': pyogrio.get_gdal_version_string() if hasattr(pyogrio, 'get_gdal_version_string') else pyogrio.__gdal_version__,
        'PROJ': None,
        'GEOS': None,
    }
except ImportError:
    pass
except AttributeError:
    pass

# pyproj - links PROJ directly
try:
    import pyproj
    results['pyproj'] = {
        'GDAL': None,
        'PROJ': pyproj.proj_version_str,
        'GEOS': None,
    }
except ImportError:
    pass

# shapely - links GEOS directly
try:
    import shapely
    results['shapely'] = {
        'GDAL': None,
        'PROJ': None,
        'GEOS': shapely.geos_version_string,
    }
except ImportError:
    pass

# geopandas - comprehensive show_versions
try:
    import geopandas
    # geopandas.show_versions() prints to stdout, capture it
    import io
    from contextlib import redirect_stdout
    
    f = io.StringIO()
    with redirect_stdout(f):
        geopandas.show_versions()
    gp_info = f.getvalue()
    
    # Parse relevant lines
    gp_gdal = gp_proj = gp_geos = None
    for line in gp_info.split('\n'):
        if line.strip().startswith('GDAL'):
            parts = line.split(':')
            if len(parts) >= 2:
                gp_gdal = parts[1].strip()
        elif line.strip().startswith('PROJ'):
            parts = line.split(':')
            if len(parts) >= 2:
                gp_proj = parts[1].strip()
        elif line.strip().startswith('GEOS') and 'lib' not in line.lower():
            parts = line.split(':')
            if len(parts) >= 2:
                gp_geos = parts[1].strip()
    
    results['geopandas'] = {
        'GDAL': gp_gdal,
        'PROJ': gp_proj,
        'GEOS': gp_geos,
    }
except ImportError:
    pass

# rioxarray
try:
    import rioxarray
    # rioxarray uses rasterio under the hood
    results['rioxarray'] = {
        'GDAL': 'via rasterio',
        'PROJ': 'via rasterio',
        'GEOS': None,
    }
except ImportError:
    pass

# odc-geo
try:
    import odc.geo
    # odc-geo uses rasterio/pyproj
    results['odc-geo'] = {
        'GDAL': 'via rasterio',
        'PROJ': 'via pyproj',
        'GEOS': None,
    }
except ImportError:
    pass

# Print results
print("Package-reported versions:")
print(f"{'Package':<15} {'GDAL':<20} {'PROJ':<12} {'GEOS':<12}")
print(f"{'-'*15:<15} {'-'*20:<20} {'-'*12:<12} {'-'*12:<12}")

for pkg, versions in results.items():
    gdal_v = versions['GDAL'] or '-'
    proj_v = versions['PROJ'] or '-'
    geos_v = versions['GEOS'] or '-'
    print(f"{pkg:<15} {gdal_v:<20} {proj_v:<12} {geos_v:<12}")

# Check alignment
print("\n=== Alignment Check ===")

def check_alignment(lib_name, system_ver, pkg_versions):
    """Check if all package versions match system version"""
    # Filter out None and 'via ...' markers
    actual_versions = {
        pkg: v for pkg, v in pkg_versions.items() 
        if v is not None and not v.startswith('via ')
    }
    
    if not actual_versions:
        print(f"{lib_name}: No packages report version directly")
        return True
    
    system_norm = normalize_version(system_ver)
    
    mismatches = []
    for pkg, v in actual_versions.items():
        pkg_norm = normalize_version(v)
        if pkg_norm != system_norm:
            mismatches.append((pkg, v, pkg_norm))
    
    if not mismatches:
        print(f"{lib_name}: OK (all packages match system {system_ver})")
        return True
    else:
        print(f"{lib_name}: MISMATCH!")
        print(f"  System: {system_ver} (normalized: {system_norm})")
        for pkg, v, v_norm in mismatches:
            print(f"  {pkg}: {v} (normalized: {v_norm}) DIFFERS")
        return False

gdal_versions = {pkg: v['GDAL'] for pkg, v in results.items()}
proj_versions = {pkg: v['PROJ'] for pkg, v in results.items()}
geos_versions = {pkg: v['GEOS'] for pkg, v in results.items()}

gdal_ok = check_alignment('GDAL', system_gdal, gdal_versions)
proj_ok = check_alignment('PROJ', system_proj, proj_versions)
geos_ok = check_alignment('GEOS', system_geos, geos_versions)

print()
if gdal_ok and proj_ok and geos_ok:
    print("✓ All versions aligned")
    sys.exit(0)
else:
    print("✗ Version misalignment detected!")
    print("This indicates packages were built against different library versions.")
    print("The environment may behave unpredictably.")
    sys.exit(1)
