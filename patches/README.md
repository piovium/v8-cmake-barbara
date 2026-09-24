# System STL compatibility

`system-stl.patch` applies to the V8 repository at the pinned revision. It
qualifies `std::nullptr_t` in the public template header (libstdc++ does not
provide the global alias) and makes the zero fallback for an optional byte
explicit (older system STLs cannot deduce `value_or({})`). These changes preserve
the types and runtime behavior. Apply it to prepared checkouts before building:

```sh
git -C /path/to/v8 apply /path/to/v8-cmake/patches/system-stl.patch
git -C /path/to/v8 apply /path/to/v8-cmake/patches/system-stl-callable.patch
git -C /path/to/v8 apply /path/to/v8-cmake/patches/system-stl-headers.patch
git -C /path/to/v8 apply /path/to/v8-cmake/patches/system-stl-atomic.patch
git -C /path/to/v8 apply /path/to/v8-cmake/patches/system-stl-constexpr.patch
git -C /path/to/v8 apply /path/to/v8-cmake/patches/system-stl-msvc.patch
```

`system-stl-callable.patch` allows V8's callable signature traits to recognize
an inherited call operator. MSVC's `std::function` declares its call operator
in a base class, so its member-pointer owner differs from the callable type.
The patch deduces that owner independently without changing the signature.

`system-stl-headers.patch` includes `<memory>` where bigint uses
`std::unique_ptr`, instead of relying on libc++'s transitive includes.

`system-stl-atomic.patch` initializes a warning flag with `ATOMIC_FLAG_INIT`.
Constructing `std::atomic_flag` from `false` is a libc++ extension; the standard
initializer preserves the same initially clear state with the MSVC STL.

`system-stl-constexpr.patch` increases Clang's constexpr evaluation budget for
`v8_base_without_compiler` in Windows Debug builds with the system STL. Sorting
V8's flag names with MSVC's checked iterators exceeds Clang's default budget.
This retains iterator checking and compile-time initialization.

`system-stl-msvc.patch` uses MSVC's `__assume(0)` for an unreachable path in
the public Debug headers. Clang and GCC retain `__builtin_unreachable()`.

# Windows CRT selection

`windows-runtime.patch` applies to Chromium's **build repository** (the `build/`
dependency inside a V8 checkout), not to V8 itself. It was prepared against
`9b7e5bb55b71044930fcf31b3fe531ad63151813`, the build revision in V8 14.8.178.33.

It adds `v8_cmake_use_dynamic_crt` and uses that argument in the default CRT
selection and the release CRT selection for build tools. The implementation of
each CRT configuration remains upstream. The driver sets the argument from the
consumer's `CMAKE_MSVC_RUNTIME_LIBRARY` and enables standard Debug STL iterators.

The CRT patch is only needed on Windows. Managed checkouts are patched once;
repeat builds detect the existing patch with a reverse applicability check.
Prepared Windows checkouts must have it applied before use:

```sh
git -C /path/to/v8/build apply --check /path/to/v8-cmake/patches/windows-runtime.patch
git -C /path/to/v8/build apply /path/to/v8-cmake/patches/windows-runtime.patch
```

Keep this change small during version rolls, and remove it if upstream exposes
an equivalent CRT argument. The patched file retains Chromium's BSD license.
