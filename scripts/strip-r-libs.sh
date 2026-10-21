#!/bin/bash
# strip-r-libs.sh STAMPFILE
#
# Strip debug info from R package shared objects created since STAMPFILE.
#
# Usage, inside ONE Docker RUN:
#   touch /tmp/r-stamp && Rscript install-things.R \
#     && bash /opt/scripts/strip-r-libs.sh /tmp/r-stamp
#
# Why this shape:
#   * It must run in the same RUN as the install. Stripping in a later RUN
#     copies every touched file up into a new layer, so the image grows by
#     the stripped size instead of shrinking.
#   * It must only touch files created by this RUN. Rewriting a .so that
#     came from a lower layer copies it up too, even if nothing is removed.
#   * -cnewer (inode change time), not -newer (mtime): binary packages from
#     PPM are untarred with their original mtimes, but ctime is always the
#     extraction time.
set -euo pipefail

stamp=${1:?usage: strip-r-libs.sh STAMPFILE}
[ -e "$stamp" ] || { echo "strip-r-libs.sh: stamp file $stamp not found" >&2; exit 1; }

n=0
for lib in /usr/local/lib/R/site-library /usr/lib/R/site-library; do
    [ -d "$lib" ] || continue
    while IFS= read -r -d '' so; do
        strip --strip-debug "$so"
        n=$((n + 1))
    done < <(find "$lib" -path '*/libs/*.so' -cnewer "$stamp" -print0)
done
rm -f "$stamp"
echo "strip-r-libs.sh: stripped $n shared object(s)"
