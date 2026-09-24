# Windows CRT selection

`windows-runtime.patch` applies to Chromium's **build repository** (the `build/`
dependency inside a V8 checkout), not to V8 itself. It was prepared against
`9b7e5bb55b71044930fcf31b3fe531ad63151813`, the build revision in V8 14.8.178.33.

It adds `v8_cmake_use_dynamic_crt` and uses that argument in the default CRT
selection and the release CRT selection for build tools. The implementation of
each CRT configuration remains upstream. The driver sets the argument from the
consumer's `CMAKE_MSVC_RUNTIME_LIBRARY` and enables standard Debug STL iterators.

No patch is needed on Linux or macOS. Managed Windows checkouts are patched once;
repeat builds detect the existing patch with a reverse applicability check.
Prepared Windows checkouts must have it applied before use:

```sh
git -C /path/to/v8/build apply --check /path/to/v8-cmake/patches/windows-runtime.patch
git -C /path/to/v8/build apply /path/to/v8-cmake/patches/windows-runtime.patch
```

Keep this change small during version rolls, and remove it if upstream exposes
an equivalent CRT argument. The patched file retains Chromium's BSD license.
