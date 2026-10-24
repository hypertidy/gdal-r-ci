#!/usr/bin/env Rscript
# smoke-mesh.R
#
# Quick functional check for gdal-r-mesh: wk reads the simple features
# surface types, a TIN round-trips through a wkpool triangle pool, the
# triangulation engines run, SFCGAL output reaches wk and wkpool, rgl draws
# on its null device, and the mesh models load. Fails (non-zero exit) on any
# mismatch. Optional packages are checked only if they installed.

library(wkpool)

check <- function(ok, what) {
  if (!isTRUE(ok)) stop("smoke-mesh: ", what, call. = FALSE)
  message("ok  ", what)
}

# 1. wk reads TIN / TRIANGLE / POLYHEDRALSURFACE (as MULTIPOLYGON / POLYGON)
check(identical(
  unclass(wk::wk_handle(wk::wkt("TIN (((0 0, 1 0, 0 1, 0 0)))"), wk::wkt_writer())),
  "MULTIPOLYGON (((0 0, 1 0, 0 1, 0 0)))"
), "wk reads TIN from WKT")

tin <- sf::st_as_sfc(c(
  "TIN Z (((0 0 0, 2 0 1, 0 2 1, 0 0 0)), ((2 0 1, 2 2 2, 0 2 1, 2 0 1)))",
  "TIN Z (((2 0 1, 4 0 0, 2 2 2, 2 0 1)))"
))
check(nrow(wk::wk_coords(tin)) == 12L, "wk reads sfc_TIN")
check(nrow(wk::wk_coords(wk::wkb(unclass(sf::st_as_binary(tin))))) == 12L,
      "wk reads TIN WKB")

# 2. TIN -> wkpool -> merged vertices, shared edge between the features
pool <- merge_coincident(establish_topology(tin))
check(nrow(pool_vertices(pool)) == 5L, "TIN corners merge to 5 vertices")
check(nrow(find_shared_edges(pool)) == 2L, "one edge shared by both features")

# 3. triangle pool from the TIN rings
s <- pool_segments(establish_topology(tin))
i <- which(!duplicated(s$.path))
tri <- new_wkpool_tri(pool_vertices(establish_topology(tin)),
                      s$.vx0[i], s$.vx0[i + 1L], s$.vx0[i + 2L],
                      feature = s$.feature[i])
check(length(tri) == 3L, "wkpool_tri from TIN rings")

# 4. triangulation engines on a square with a square hole
x <- c(0, 1, 1, 0, 0.25, 0.75, 0.75, 0.25)
y <- c(0, 0, 1, 1, 0.25, 0.25, 0.75, 0.75)
s0 <- 1:8
s1 <- c(2, 3, 4, 1, 6, 7, 8, 5)

m <- laridae::lari_new(x, y, s0 = s0, s1 = s1)
check(all(c(1L, 2L) %in% laridae::lari_depth(m)), "laridae CDT with depth")

ct <- cdtr::cdt_triangulate(x, y, s0 = s0, s1 = s1)
check(nrow(ct$T) >= 8L && all(c(1L, 2L) %in% ct$depth), "cdtr CDT with depth")

ec <- decido::earcut(cbind(x, y), holes = 5)
check(length(ec) %% 3L == 0L && length(ec) > 0L, "decido ear cuts")

tr <- RTriangle::triangulate(RTriangle::pslg(P = cbind(x, y), S = cbind(s0, s1),
                                            H = cbind(0.5, 0.5)))
check(nrow(tr$T) >= 8L, "RTriangle CDT with a hole")

# 5. SFCGAL: tessellate a polygon with a hole, the TIN goes back to a pool
check(nzchar(sfcgal::sfcgal_version()), "sfcgal binds SFCGAL")
sq <- sf::st_as_sfc(paste(
  "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0),",
  "(0.25 0.25, 0.25 0.75, 0.75 0.75, 0.75 0.25, 0.25 0.25))"
))
cg <- sfcgal::cg_tessellate(sq)
check(inherits(cg, "sfc_TIN"), "sfcgal tessellates to sfc_TIN")
cg_pool <- merge_coincident(establish_topology(cg))
check(nrow(pool_vertices(cg_pool)) == 8L, "SFCGAL TIN merges to 8 vertices")
check(abs(sum(sf::st_area(sf::st_cast(sf::st_as_sfc(wk::wk_handle(cg, wk::wkb_writer())),
                                      "POLYGON"))) - 0.75) < 1e-12,
      "SFCGAL TIN area via wk")

# 6. rgl on the null device
check(isTRUE(rgl::rgl.useNULL()), "rgl uses the null device")
invisible(rgl::open3d())
rgl::triangles3d(cbind(x, y, 0)[t(ct$T[ct$depth == 1L, , drop = FALSE]), ])
check(length(rgl::ids3d()$id) >= 1L, "rgl draws the cdtr mesh")
invisible(rgl::close3d())

# 7. mesh models
check(nrow(silicate::sc_object(silicate::SC(silicate::minimal_mesh))) == 2L,
      "silicate SC")
check(inherits(quadmesh::quadmesh(matrix(1:12, 3)), "mesh3d"), "quadmesh")
check(requireNamespace("polymer", quietly = TRUE), "polymer loads")
for (pkg in c("anglr", "meshcore")) {
  if (requireNamespace(pkg, quietly = TRUE)) message("ok  ", pkg, " loads (optional)")
  else message("--  ", pkg, " not installed (optional)")
}

message("\ngdal-r-mesh smoke test passed")
