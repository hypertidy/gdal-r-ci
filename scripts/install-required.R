# BUMP
pkgs <- readLines('/tmp/r-packages-required.txt')
pkgs <- pkgs[!grepl('^#', pkgs) & nchar(trimws(pkgs)) > 0]
for (pkg in pkgs) {
  message(strrep('=', 60))
  message('REQUIRED: ', pkg)
  message(strrep('=', 60))
  if (grepl('/', pkg)) {
    remotes::install_github(pkg, upgrade = 'never', build_vignettes = FALSE)
  } else {
    install.packages(pkg, type = 'source')
  }
}
