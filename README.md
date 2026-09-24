# v8-cmake

A CMake entry point for Google's V8, intended for `FetchContent_MakeAvailable`.
Link **`v8::v8`** to get the complete static library, public headers, generated ABI
definitions, C++20 requirement, and platform libraries. `v8::monolith` is an alias.

V8 still builds with its own GN/Ninja files. This repository carries no source
list, generated snapshot, or V8 runtime fork. It has one small Chromium build
patch for selecting the Windows C runtime. The pinned release is **14.8.178.33**;
both V8 and depot_tools commits are recorded in [v8-version.json](v8-version.json).

## Use with FetchContent

Replace the repository URL and commit placeholders with this wrapper's published
location and a full commit SHA:

```cmake
cmake_minimum_required(VERSION 3.24)
project(my_application LANGUAGES CXX)

include(FetchContent)
FetchContent_Declare(v8_wrapper
  GIT_REPOSITORY <URL-of-this-repository>
  GIT_TAG <full-wrapper-commit-sha>
)
FetchContent_MakeAvailable(v8_wrapper)

add_executable(my_application main.cc)
target_link_libraries(my_application PRIVATE v8::v8)
```

Include `<v8.h>` and `<libplatform/libplatform.h>` in your code. No additional
`v8_libplatform` or `v8_libbase` libraries are needed. See
[examples/hello.cc](examples/hello.cc) for initialization and cleanup.

To try the same integration using a local checkout:

```sh
cmake -S examples/fetchcontent -B build-consumer -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build-consumer --target hello
ctest --test-dir build-consumer --output-on-failure
```

Configuration does not download V8. The first build of a target linking V8
fetches depot_tools, V8, its DEPS, and upstream compiler/build tools, then builds
`v8_monolith`. Allow several GB of downloads and roughly 15–30 GB of free space.
Later builds delegate incremental work to Ninja. The wrapper's custom target
runs each time so deleted artifacts and local source edits are detected; unchanged
headers and archives retain their timestamps.

## Platforms and prerequisites

Every host needs CMake 3.24+, Python 3.9+, Git, and a C++20 consumer compiler.
Ninja is needed when selected as the CMake generator; V8's own GN and Ninja are
downloaded at the versions pinned in its DEPS.

| Target | Build host | Additional requirements |
| --- | --- | --- |
| Linux x64 | Linux x64 | glibc development headers, GCC/libstdc++ with C++20 support; Ubuntu 24.04 is the CI baseline |
| Linux arm64 | Linux x64 | arm64 cross GCC/libstdc++ and sysroot; example below |
| macOS arm64 | macOS arm64 | Full Xcode with macOS SDK 15+; deployment target 12+ |
| macOS x64 | macOS x64 or arm64 | Same Xcode requirements; set `CMAKE_OSX_ARCHITECTURES=x86_64` |
| Windows x64 | Windows x64 | Visual Studio 2022/2026 C++ tools and Windows SDK 10.0.26100; MSVC or clang-cl consumer |

The pinned upstream Linux LLVM binaries are x64 executables. Native Linux arm64
hosts are currently rejected; build arm64 artifacts on an x64 host. Android,
iOS, MinGW, musl, 32-bit targets, and cross-OS builds are outside the supported
configuration. macOS universal binaries require separate build trees.

V8 uses its pinned Clang internally, with the **system C++ standard library**.
The consumer compiler can differ provided its C++ ABI and standard library match.
CMake compiler flags, arbitrary toolchain settings, sanitizers and LTO settings
are not automatically translated into GN arguments. Linux consumers should use
libstdc++; macOS consumers use Apple's libc++; Windows consumers use MSVC's STL.

On macOS, select full Xcode with `xcode-select` before building. The wrapper
forwards `CMAKE_OSX_SYSROOT` and `CMAKE_OSX_DEPLOYMENT_TARGET`, and uses Apple's
linker so the installed SDK's TAPI format is understood.

On Windows, use an x64 developer shell for Ninja, or a Visual Studio generator:

```powershell
cmake -S examples/fetchcontent -B build-consumer -G "Visual Studio 17 2022" -A x64
cmake --build build-consumer --config Release --target hello
ctest --test-dir build-consumer -C Release --output-on-failure
```

`CMAKE_MSVC_RUNTIME_LIBRARY` is forwarded. Its default is `/MD` in Release and
`/MDd` in Debug. To use `/MT` and `/MTd`, set this **before** making V8 available
and before creating your application targets:

```cmake
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
```

All consumers must use the same runtime selection; per-target runtime overrides
cannot be inferred by the wrapper. Debug uses the usual MSVC checked iterators.
Keep Windows checkout/build paths short and enable Git long-path support if needed.

### Linux arm64 cross-compilation

On Debian/Ubuntu x64, install `g++-aarch64-linux-gnu`. The supplied toolchain uses
the distribution's cross-toolchain layout under `/usr`:

```sh
cmake -S examples/fetchcontent -B build-arm64 -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/linux-arm64.cmake" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-arm64 --target hello
```

Copy the result to an arm64 Linux system with a compatible libstdc++, or install
`qemu-user` and run `qemu-aarch64 -L /usr/aarch64-linux-gnu build-arm64/hello`.
For another sysroot, provide your own CMake toolchain with
`CMAKE_SYSTEM_PROCESSOR=aarch64` and `CMAKE_SYSROOT`; the latter is forwarded to
GN. GN builds and runs the snapshot generator on the host using V8's simulator.

## Build behavior and options

Defaults include ICU/`Intl`, WebAssembly, pointer compression, embedded startup
data and ICU data, and RTTI. No runtime `.bin` or `.dat` files are required.
ARM snapshots use target CPU features rather than the build machine's optional
instructions so the resulting library can be moved between target machines.
Chromium's process-wide allocator replacement is disabled for embedding.
The experimental Rust Temporal implementation is disabled.

**V8's memory sandbox is disabled.** This V8 revision requires Chromium's private
hardened libc++ for that feature, which is incompatible with the system-STL build
used here. This is a material limitation when choosing this configuration for
untrusted JavaScript. Pointer compression remains governed by upstream defaults.

Set cache options before `FetchContent_MakeAvailable` or with `-D`:

| Option | Default | Meaning |
| --- | --- | --- |
| `V8_ENABLE_I18N` | `ON` | Build ICU and JavaScript `Intl` |
| `V8_BUILD_JOBS` | empty | Inner Ninja parallelism; set e.g. `4` to limit memory use |
| `V8_WORKSPACE` | wrapper binary dir `/workspace` | Managed checkout/dependency cache; builds sharing it are serialized |
| `V8_SOURCE_DIR` | empty | Use an already synced checkout; skip fetching, syncing and hooks |
| `V8_DEPOT_TOOLS_DIR` | empty | Use existing depot_tools instead of the managed pinned checkout |
| `V8_OFFLINE` | `OFF` | Fail instead of downloading or running dependency hooks |
| `V8_GN_EXECUTABLE`, `V8_NINJA_EXECUTABLE` | empty | Override tools from V8 DEPS |
| `V8_BUILD_EXAMPLE` | top-level only | Build `v8_hello` |
| `V8_BUILD_TESTS` | top-level only | Register wrapper tests and, if built, the example |

Debug, Release, RelWithDebInfo and MinSizeRel have separate GN output, library,
and header directories. An empty single-config build type means Release for V8.
Debug uses upstream optimized debugging; RelWithDebInfo adds symbols. MinSizeRel
currently uses the same V8 optimization settings as Release. Parent options and
`BUILD_SHARED_LIBS` are not changed. The archive is usable in a shared library.
There is no `install()`/`find_package()` package yet; this is a build-tree wrapper.

### Existing checkouts and offline builds

Use `V8_SOURCE_DIR=/absolute/path/to/v8` for a checkout whose version header
matches the lock and whose DEPS/hooks have already completed. Such a checkout
is not synced or patched by this wrapper. On Windows, first apply
[patches/windows-runtime.patch](patches/windows-runtime.patch) in its `build`
repository. Supplied tools/checkouts are an explicit escape hatch from the
managed toolchain pins.

After a successful managed build, `V8_OFFLINE=ON` reuses the existing workspace.
A fresh offline build needs a prepared source tree and its GN/Ninja/compiler
dependencies. `FETCHCONTENT_FULLY_DISCONNECTED` controls fetching this wrapper;
use `V8_OFFLINE` separately to control its V8 bootstrap. depot_tools may use its
normal user-level CIPD/Python caches during the initial online setup.

## Validation and updates

```sh
python3 -m unittest discover -s tests -v
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
```

The Python suite tests failure handling and the actual FetchContent build graph
using a tiny stand-in library; it does **not** validate the V8 runtime. The C++
example links real V8, creates an isolate, executes JavaScript, and exercises
embedded ICU when enabled. CI defines real builds for Linux x64, Linux arm64
cross-compilation, macOS arm64, and Windows x64 Release/Debug. A configured CI
matrix is not evidence that every platform has already passed.
The initial macOS arm64 build and runtime results are recorded in
[docs/validation.md](docs/validation.md).

See [docs/updating-v8.md](docs/updating-v8.md) for the version-update procedure and
[docs/design.md](docs/design.md) for the build contract. Upstream references:
[GN build instructions](https://v8.dev/docs/build-gn) and
[embedding guide](https://v8.dev/docs/embed).

The wrapper is BSD-3-Clause licensed. V8 and its dependencies retain their own
licenses; redistribution must include the notices for the dependencies you ship.
Staged V8 license files are a convenience, not a complete third-party notice set.
