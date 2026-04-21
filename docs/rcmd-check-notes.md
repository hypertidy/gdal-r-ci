## rcmdcheck usage


```
docker pull ghcr.io/hypertidy/gdal-r-full:dev
docker run --rm -ti -v $(pwd):/pkg ghcr.io/hypertidy/gdal-r-full:dev bash
```

Use rcmdcheck::rcmdcheck() directly rather than devtools::check().


For CI against GDAL:

```r
rcmdcheck::rcmdcheck(
  path       = "/pkg",
  build_args = c("--no-build-vignettes", "--no-manual"),
  args       = c("--no-manual", "--ignore-vignettes", "--as-cran")
  ##error_on   = "warning"
)
```

Notes:
- build_args controls R CMD build, args controls R CMD check
- `--no-manual avoids` pdflatex/inconsolata.sty dependency (texlive-fonts-extra is 2GB)
- locale warning (en_US.UTF-8) needs locale-gen in the image, not an rcmdcheck fix
- devtools::check() wraps rcmdcheck but suppresses some --as-cran checks
- checkbashisms warning needs devscripts apt package
- -mno-omit-leaf-frame-pointer NOTE is R's own compiler flag, not the package
