# Validation record

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
