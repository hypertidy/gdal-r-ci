pkgs <- readLines('/tmp/r-packages-optional.txt')
pkgs <- pkgs[!grepl('^#', pkgs) & nchar(trimws(pkgs)) > 0]
results <- list()
for (pkg in pkgs) {
  message(strrep('=', 60))
  message('OPTIONAL: ', pkg)
  message(strrep('=', 60))
  pkg_name <- sub('.*/','', pkg)
  ok <- tryCatch({
    if (grepl('/', pkg)) {
      remotes::install_github(pkg, upgrade = 'never', build_vignettes = FALSE)
    } else {
      install.packages(pkg, type = 'source')
    }
    requireNamespace(pkg_name, quietly = TRUE)
  }, error = function(e) {
    message('FAILED: ', conditionMessage(e)); FALSE
  })
  results[[pkg_name]] <- ok
}
message()
message(strrep('=', 60))
message('Optional package summary:')
for (n in names(results)) {
  message(sprintf('  %-20s [%s]', n, if (results[[n]]) 'OK' else 'FAILED'))
}
