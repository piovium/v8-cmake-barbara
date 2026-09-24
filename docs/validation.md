# Validation record

## Windows x64 validation, 2026-09-24

The repaired wrapper was tested locally with Visual Studio Community 2026
(MSVC 19.51.36248), Windows SDK 10.0.26100.0, CMake 4.3.3, Python 3.14.6,
and V8's pinned Clang/Ninja:

- All 21 wrapper tests passed, including single- and multi-config FetchContent.
- The real Release library and consumer built with the Visual Studio generator.
- CTest passed; the executable printed `V8 14.8.178.33: 42`.
- Copying only the executable into a clean directory passed the same smoke test.
- An offline rebuild reported `ninja: no work to do`; archive, generated header,
  and executable timestamps were unchanged. CTest passed again.
- A focused callable-traits compile check failed before the inherited-call
  patch and passed afterward using the pinned Clang with MSVC's STL.
- WSL Ubuntu with GCC 15.2 reproduced the missing `<memory>` error; all bigint
  translation units passed syntax checks after applying the header patch.

Additional checks on **2026-09-25**:

- The static-CRT/no-Intl Release variant built with Ninja Multi-Config and passed
  CTest using the offline workspace.
- The real Debug archive linked to an MSVC consumer and executed JavaScript/Intl
  successfully after correcting the public-header unreachable intrinsic.

These local results supplement the full platform CI matrix; the WSL syntax
checks alone do not establish Linux runtime success.

## Initial macOS validation

Initial validation on **2026-09-24**, using the V8 14.8.178.33 lock in this
repository:

| Check | Result |
| --- | --- |
| 18 Python tests, including actual single-/multi-config FetchContent graphs with a stand-in library | Passed |
| Real V8 Release build, macOS arm64 | Passed |
| Real embedding executable, JavaScript result and embedded ICU | Passed: `V8 14.8.178.33: 42` |
| Executable copied to a clean directory without snapshot/ICU data files | Passed |
| Offline rebuild with unchanged inputs | Ninja reported no work; archive, headers and executable timestamps unchanged |
| Real GN generation for Debug, MinSizeRel and ICU-disabled configurations | Passed |
| Linux x64 and arm64 target GN generation, using the macOS GN host tool | Passed; this does not validate Linux compilation or execution |
| Windows runtime patch applicability against the pinned Chromium build revision | Passed |
| Version updater `--check` against upstream | Passed |
| Native Linux and Windows runtime tests | Not run locally; supplied in `.github/workflows/ci.yml` |

The full native build used macOS 26.6.2 arm64, the installed macOS 27.0 SDK,
AppleClang 21 as the consumer compiler, CMake 4.3.4, and Python 3.14.6. V8 itself
used its DEPS-pinned Clang 23 and Ninja, with Apple's linker. Release settings
included ICU, portable ARM snapshots, system libc++, and the allocator/sandbox
choices documented in the README.

The resulting executable depends on system frameworks, libc++ and libSystem;
it has no dynamic V8 or ICU library dependency. The wrapper's CTest suite passed
both registered tests (`v8_wrapper` and `v8_hello`). Debug and ICU-disabled
runtime behavior still need their full CI builds; successful GN generation
alone is not a runtime test.

## First CI run: regressions and fixes

[Run 35980746403](https://github.com/piovium/v8-cmake-barbara/actions/runs/35980746403)
exposed two platform differences:

- Linux GN generation tried to discover GLib through Chromium's default
  configuration. Standalone V8 does not need GLib; the wrapper now sets
  `use_glib=false`. Its exported Linux link interface also includes `atomic`,
  as required by the pinned Chromium configuration when using the system STL.
- All three Windows jobs failed a fixture assertion because MSVC initializes
  an unspecified CMake build type to Debug. The test for the wrapper's Release
  fallback now explicitly passes an empty build type; a separate test checks
  the initialized Debug case. Both behaviors are exercised on every test host.

After these fixes, all 19 Python tests passed on macOS arm64. Real Linux x64
and arm64 GN generation also passed with a script launcher that rejects every
pkg-config invocation; the same launcher reproduced both failures before the
fix. This guard matters because Chromium's pkg-config helper otherwise skips
discovery on macOS, so the original cross-target generation check missed the
Linux failure. These checks do not replace full Linux and Windows CI builds.
