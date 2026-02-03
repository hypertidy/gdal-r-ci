# gdalcheck Integration Roadmap

## Current State

gdalcheck is parked - it has ambitious goals but the infrastructure isn't ready.

**What gdalcheck wants to do:**
- Test ~930 reverse dependencies of sf/terra/gdalraster/vapour/stars
- Pre-compile ~1500 R packages as binary cache
- Run checks in parallel on HPC/cloud
- Publish dashboard to GitHub Pages

**What's blocking it:**
- Binary cache building takes ~2 hours and 15GB
- No stable base image to build cache against
- GDAL version changes invalidate the cache

## How gdal-r-ci Helps

Once we have stable, weekly-rebuilt images:

```
ghcr.io/hypertidy/gdal-r-full:latest
           │
           ▼
┌──────────────────────────────────────┐
│ ghcr.io/hypertidy/gdal-r-cache:latest│
│  + Pre-compiled binary cache         │
│  + ~1500 packages as .tar.gz         │
└──────────────────────────────────────┘
```

The cache image can be rebuilt when:
1. `gdal-r-full` changes (weekly)
2. CRAN packages update (daily check, rebuild if needed)

## Phase 1: CRAN-5 Stability (current)

Focus: Get gdal-r-ci working reliably for the 5 core packages

- [x] Design image hierarchy
- [ ] Build and publish images
- [ ] Test reusable workflow
- [ ] Run scheduled checks for 2-4 weeks
- [ ] Fix any issues that emerge

## Phase 2: Binary Cache (future)

Focus: Add binary package cache for faster revdep checking

1. Add `Dockerfile.gdal-r-cache`:
   ```dockerfile
   FROM ghcr.io/hypertidy/gdal-r-full:latest
   
   # Pre-install common dependencies as binaries
   COPY scripts/build_binary_cache.R /tmp/
   RUN Rscript /tmp/build_binary_cache.R /opt/r-cache 8
   
   ENV R_LIBS_SITE=/opt/r-cache
   ```

2. Add cache-aware check workflow that:
   - Uses cached packages when available
   - Falls back to CRAN install for missing
   - Reports which packages needed compilation

## Phase 3: Full Revdep Checking (future)

Focus: Scale to all reverse dependencies

1. Generate package manifest from CRAN
2. Parallel check infrastructure (GitHub Actions matrix or external runner)
3. Dashboard for results
4. Automated issue creation for failures

## Questions to Resolve

1. **Cache invalidation**: How do we know when to rebuild?
   - Option A: Rebuild weekly regardless
   - Option B: Check CRAN for updates daily, rebuild if needed
   - Option C: Version-lock cache, rebuild monthly

2. **Storage**: Where does the cache live?
   - Option A: Baked into Docker image (simple but large)
   - Option B: Separate artifact, mounted at runtime
   - Option C: Use r2u binaries where available

3. **Scope**: Which packages to pre-compile?
   - All revdeps of CRAN-5 (~930)
   - Just Imports/Depends (smaller)
   - Curated list based on check frequency

## Timeline

- **Now**: Focus on Phase 1, park gdalcheck
- **Q2 2026**: Revisit once CRAN-5 checks are stable
- **Q3 2026**: Consider Phase 2 if there's demand
