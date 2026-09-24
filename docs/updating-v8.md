# Updating V8

The lock is `v8-version.json`. Do not pin `main`, `lkgr`, or a branch name in build
code, and do not hand-maintain V8 source lists. Use a released four-part V8 tag.

1. Resolve the proposed version and inspect the change:

   ```sh
   python3 scripts/update_v8.py <major.minor.build.patch> --dry-run
   python3 scripts/update_v8.py <major.minor.build.patch>
   git diff -- v8-version.json
   ```

   The script verifies the version header, resolves the tag to a full commit,
   and checks that the monolith and public ABI header integration points still
   exist. It retains the existing depot_tools pin. To update tooling deliberately,
   add `--depot-tools-ref <commit-or-ref>`; even `HEAD` is resolved to a commit
   before writing. `--check` verifies the existing lock without writing it.

2. Inspect the new V8 `BUILD.gn`, `gni/v8.gni`, `DEPS`, and `include/v8config.h`.
   Check every argument in `scripts/build_v8.py`, the generated header location,
   C++ standard, minimum OS/SDKs, ICU data embedding, target architecture and
   host snapshot toolchains, and system link dependencies. Read the pinned
   Chromium `build/config/{win,mac,compiler}` changes too.

3. Use a **new build directory and workspace** for the first build. This avoids
   carrying modified Chromium build files or stale SDK/tool artifacts across a
   roll. Once gclient has fetched the new tree, verify the patches:

   ```sh
   git -C <v8-checkout> apply --check /absolute/path/to/patches/system-stl.patch
   git -C <v8-checkout> apply --check /absolute/path/to/patches/system-stl-callable.patch
   git -C <v8-checkout> apply --check /absolute/path/to/patches/system-stl-headers.patch
   git -C <v8-checkout> apply --check /absolute/path/to/patches/system-stl-atomic.patch
   git -C <v8-checkout>/build apply --check /absolute/path/to/patches/windows-runtime.patch
   ```

   The wrapper applies the CRT patch only on Windows. If upstream now supports
   CRT selection, remove that patch and use the setting. Otherwise refresh only the
   small CRT selection change; don't import unrelated modifications. Do not
   add V8 runtime patches to work around a toolchain or ABI mismatch. Recheck
   the standard type qualification, header dependencies, atomic initialization,
   optional fallback, and inherited callable
   fixes in the system-STL patches, removing each hunk once upstream includes
   an equivalent correction.

4. Run the offline suite and all real CI configurations:

   ```sh
   python3 -m unittest discover -s tests -v
   cmake -S . -B build-roll -G Ninja -DCMAKE_BUILD_TYPE=Release -DV8_BUILD_JOBS=4
   cmake --build build-roll
   ctest --test-dir build-roll --output-on-failure
   ```

   Required coverage: Linux x64, Linux arm64 cross-build plus execution on
   hardware or QEMU, macOS arm64, and Windows x64 Release and Debug. Exercise
   Windows dynamic and static CRT configurations when changing the patch.
   Build the example through `examples/fetchcontent` as well as standalone.
   Confirm a second build does not recompile V8 and an offline rebuild succeeds.
   The fixture tests verify CMake ordering, not real platform ABI compatibility.

5. Test `V8_ENABLE_I18N=OFF` in a separate build, and inspect the executable's
   runtime dependencies. It should not need external V8/ICU data files. Confirm
   that staged public definitions, compiler runtime, and CMake link dependencies
   still match. Test linking the archive into a shared library when changing
   relocation, symbol visibility, or allocator settings.

6. Update the README version, prerequisites and supported-platform claims with
   actual results. Record SDK/compiler versions and any untested configurations
   in the change description. Review the lock and patch diff together. Commit
   the lock, wrapper adjustments and docs in the same version roll.

Bootstrap failures can be retried in the same workspace if the lock did not
change; failed syncs are not marked complete. Do not manually edit managed
checkouts. For V8 development or local patches, use a separately prepared tree
with `V8_SOURCE_DIR`.
