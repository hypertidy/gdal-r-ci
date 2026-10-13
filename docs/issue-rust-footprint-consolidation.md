# Assess Rust footprint across the image chain, consider consolidation

## Summary

Rust is installed independently in **three** layers of the build chain. Each
grew up for a different reason, and they now overlap enough to be worth a
deliberate review — both for image size and for avoiding version drift between
the toolchains.

## Current state

| Layer | Dockerfile | `CARGO_HOME` / `RUSTUP_HOME` | Toolchain | Why it's here |
|---|---|---|---|---|
| base | `docker/Dockerfile.gdal-system` (~L113-121) | `/usr/local/cargo`, `/usr/local/rustup` | stable (default) | GDAL optional Rust features (pcodec via cargo) |
| python | `docker/Dockerfile.gdal-r-python` (~L160-178) | `/opt/cargo`, `/opt/rustup` | stable, minimal profile; guard asserts rustc >= 1.91 | builds `pizzarr` with `s3,gcs` features |
| rust leaf | `docker/Dockerfile.extras-rust` (~L30-53) | reuses `/opt/cargo`, `/opt/rustup` | pins **1.85.0** as default + clippy/rustfmt/rust-analyzer, lld, cargo-nextest | dev toolchain for downstream Rust work |

Chain: `gdal-system → gdal-r → gdal-r-full → gdal-r-python → gdal-r-python-extras → extras-rust`.

## Why this is worth a look

- **Two separate rustup roots** (`/usr/local/*` and `/opt/*`) carry two copies
  of the toolchain in the final images. Each toolchain is a few hundred MB.
- **Version coupling is implicit and partly contradictory.** `gdal-r-python`
  guards `rustc >= 1.91`, while `extras-rust` pins the default to `1.85.0`
  further down the chain. Anything that source-builds Rust code is sensitive to
  which toolchain/`PATH` wins at that layer. (Example surfaced while adding the
  R `ggsql` package: `SystemRequirements: rustc >= 1.86`. It builds fine at the
  `-extras` layer because the active `/opt/cargo` default there is stable
  >= 1.91 — but the 1.85.0 pin one layer down would *not* satisfy it, so the
  margin is thinner than it looks.)
- **New Rust-backed R/Python packages are arriving** (ggsql R + Python,
  pizzarr, potential extendr packages). A single, clearly-owned toolchain makes
  their version requirements easier to reason about.

## Questions to answer

1. The base toolchain is load-bearing: **GDAL needs Rust to build pcodec**, so
   `gdal-system` cannot simply drop it. The open question is therefore whether
   the later `/opt` toolchain can be eliminated by pointing downstream builds
   (pizzarr, extendr packages) at the *base* rustup root, leaving one toolchain
   for the whole chain — rather than removing the base one.
2. What is the minimum rustc the whole chain must guarantee? Reconcile the
   `>= 1.91` guard with the `1.85.0` pin — pick one source of truth.
3. Should the pinned dev toolchain (`extras-rust`) move earlier / be the single
   default, so source builds in `-extras` use a known version rather than
   "whatever stable resolves to"?
4. Measure the image-size delta of consolidation vs. the convenience of
   separate roots.

## Notes

- No code change proposed here yet — this is a scoping/investigation issue.
- Related: the pyarrow single-`libarrow` work in
  [`docs/pyarrow-system-arrow-build.md`](pyarrow-system-arrow-build.md) is a good template
  for the kind of "one runtime per process / one toolchain per image" cleanup.
