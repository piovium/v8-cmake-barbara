# Build contract

`CMakeLists.txt` creates a global imported static target, `v8::v8`, whose dependency
is `v8_build`. This dependency is followed before consumer compilation, allowing
headers to arrive at build time. Configure creates empty include directories so
CMake's imported-target validation succeeds without network access. The archive
and generated ABI header are declared byproducts so Ninja can order link steps.

Each CMake configuration produces a JSON driver input, GN output directory and
staging directory. Debug headers must never be shared with a Release archive:
V8's inline API changes with GN feature choices. The upstream generated `v8-gn.h`
and `V8_GN_HEADER` provide the exact V8 and cppgc public definitions without
maintaining a second list of ABI macros.

`scripts/build_v8.py` owns bootstrap, GN generation, Ninja invocation and staging.
Managed sources use the immutable V8/depot_tools lock, and gclient resolves the
transitive revisions from V8's DEPS. GN and LLVM are provided by DEPS, not rolling
downloads chosen by this wrapper. gclient's completed-sync stamp is written only
after hooks succeed. A workspace lock serializes sync and build operations across
configurations/processes and is released by the OS after a crash.

GN is run with `--fail-on-unused-args`: a removed or renamed option must break the
build visibly. Ninja runs on every request, and staging preserves timestamps for
unchanged files. No configure-time network work or sub-build is necessary. The
wrapper never edits a consumer's compiler flags or global build type. Generated
output is confined to the binary tree; depot_tools also uses its standard caches.

The Windows patch changes Chromium's `default_crt` and `release_crt` selection on
Windows. It adds one GN argument and two conditions; `/MD[d]` and `/MT[d]` remain
implemented by upstream CRT configs. A second patch qualifies `std::nullptr_t`
in V8's public template header and supplies an explicit zero to `value_or` for
compatibility with system STLs. A callable-traits patch supports inherited call
operators, including those in MSVC's `std::function`. The header-dependency patch
includes `<memory>` for bigint's `std::unique_ptr`; another patch uses standard
atomic-flag initialization. External checkouts must have applicable patches
pre-applied. A failed patch check is an update
failure, never a reason to silently ignore the patch or use `/NODEFAULTLIB`.

The system STL and RTTI settings make ordinary CMake consumers practical. They
also mean this configuration cannot use the current V8 sandbox, which depends
on Chromium's hardened libc++. This tradeoff is explicit in the README. The
wrapper also disables the standalone PartitionAlloc replacement so it does not
take over the embedding application's global allocator.

No general `V8_EXTRA_GN_ARGS` string is exposed: changing the library layout,
toolchain ABI, external data, or CRT behind CMake's imported target would violate
the interface contract. Add a typed option with usage requirements and validation
when a concrete new configuration is needed.
