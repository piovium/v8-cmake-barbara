"""Exercise the real CMake graph without downloading V8. Real V8 runs in CI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("cmake") and shutil.which("ninja"), "CMake and Ninja required")
class FetchContentTests(unittest.TestCase):
    def command(self, *args, cwd=None):
        result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def fixture(self, root):
        source = root / "prepared source"
        (source / "include").mkdir(parents=True)
        (source / "build/config/win").mkdir(parents=True)
        (source / "build/config/BUILDCONFIG.gn").touch()
        # Build just enough patched context for git apply --reverse --check.
        lines = (ROOT / "patches/windows-runtime.patch").read_text().splitlines()
        postimage = "\n".join(line[1:] for line in lines
                              if line.startswith((" ", "+")) and not line.startswith("+++")) + "\n"
        (source / "build/config/win/BUILD.gn").write_text(postimage)
        lines = (ROOT / "patches/linux-relocations.patch").read_text().splitlines()
        postimage = "\n".join(line[1:] for line in lines
                              if line.startswith((" ", "+")) and not line.startswith("+++")) + "\n"
        (source / "build/config/compiler").mkdir(parents=True)
        (source / "build/config/compiler/BUILD.gn").write_text(postimage)
        # Reconstruct patched context for each V8 system-STL patch target.
        target = None
        contents = []
        stl_patches = "".join(path.read_text() for path in sorted((ROOT / "patches").glob("system-stl*.patch")))
        for line in stl_patches.splitlines() + ["+++ "]:
            if line.startswith("+++ "):
                if target is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("\n".join(contents) + "\n")
                target = source / line[6:] if line[6:] else None
                contents = []
            elif line.startswith((" ", "+")):
                contents.append(line[1:])
        version = json.loads((ROOT / "v8-version.json").read_text())["version"]
        names = ("MAJOR_VERSION", "MINOR_VERSION", "BUILD_NUMBER", "PATCH_LEVEL")
        (source / "include/v8-version.h").write_text("".join(
            f"#define V8_{name} {value}\n" for name, value in zip(names, version.split("."))))
        (source / "include/v8.h").write_text(
            '#ifndef V8_GN_HEADER\n#error missing public definition\n#endif\n'
            '#include "v8-gn.h"\nint v8_fixture_answer();\n')
        tools = []
        for mode in ("gn", "ninja"):
            path = root / (mode + (".cmd" if os.name == "nt" else ""))
            if os.name == "nt":
                path.write_text(f'@"{sys.executable}" "{ROOT / "tests/fixtures/tool.py"}" {mode} %*\n')
            else:
                path.write_text('#!/usr/bin/env python3\nimport runpy, sys\n'
                                f'sys.argv.insert(1, {mode!r})\n'
                                f'runpy.run_path({str(ROOT / "tests/fixtures/tool.py")!r}, run_name="__main__")\n')
                path.chmod(0o755)
            tools.append(path)
        parent = root / "consumer"
        parent.mkdir()
        (parent / "CMakeLists.txt").write_text(
            'cmake_minimum_required(VERSION 3.24)\n'
            # Reproduce MSVC's default on every host, so the empty-build-type
            # test cannot accidentally depend on a compiler's initialization.
            'set(CMAKE_BUILD_TYPE_INIT Debug)\nproject(consumer LANGUAGES CXX)\n'
            'include(FetchContent)\n'
            f'set(V8_SOURCE_DIR "{source.as_posix()}" CACHE PATH "")\n'
            'set(V8_OFFLINE ON CACHE BOOL "")\n'
            f'set(V8_GN_EXECUTABLE "{tools[0].as_posix()}" CACHE FILEPATH "")\n'
            f'set(V8_NINJA_EXECUTABLE "{tools[1].as_posix()}" CACHE FILEPATH "")\n'
            f'FetchContent_Declare(v8_wrapper SOURCE_DIR "{ROOT.as_posix()}")\n'
            'FetchContent_MakeAvailable(v8_wrapper)\n'
            # A sibling subdirectory checks GLOBAL imported-target visibility.
            'add_subdirectory(app)\n')
        (parent / "app").mkdir()
        (parent / "app/CMakeLists.txt").write_text(
            'add_executable(consumer main.cc)\ntarget_link_libraries(consumer PRIVATE v8::v8)\n'
            'target_compile_definitions(consumer PRIVATE EXPECT_DEBUG=$<IF:$<CONFIG:Debug>,1,0>)\n')
        (parent / "app/main.cc").write_text(
            '#include <v8.h>\nstatic_assert(V8_FIXTURE_DEBUG == EXPECT_DEBUG);\n'
            'int main() { return v8_fixture_answer() == 42 + EXPECT_DEBUG ? 0 : 1; }\n')
        return parent

    def exercise(self, generator, configs, build_type=None):
        with tempfile.TemporaryDirectory(prefix="v8 cmake graph ") as temp:
            root = Path(temp)
            parent = self.fixture(root)
            build = root / "consumer build"
            args = ["cmake", "-S", str(parent), "-B", str(build), "-G", generator]
            if build_type is not None:
                args.append("-DCMAKE_BUILD_TYPE=" + build_type)
            self.command(*args)
            stage = build / "_deps/v8_wrapper-build/stage"
            self.assertFalse((stage / "Release/include/v8.h").exists(), "Configure downloaded or staged V8")
            for config in configs:
                self.command("cmake", "--build", str(build), "--config", config, "--target", "consumer")
                exe = build / "app"
                if generator == "Ninja Multi-Config":
                    exe /= config
                exe /= "consumer.exe" if os.name == "nt" else "consumer"
                self.command(str(exe))
                library = stage / config / "lib" / ("v8_monolith.lib" if os.name == "nt" else "libv8_monolith.a")
                self.assertTrue(library.is_file(), f"Missing staged library: {library}")
                timestamp = (stage / config / "include/v8.h").stat().st_mtime_ns
                self.command("cmake", "--build", str(build), "--config", config, "--target", "consumer")
                self.assertEqual(timestamp, (stage / config / "include/v8.h").stat().st_mtime_ns)
                library.unlink()
                self.command("cmake", "--build", str(build), "--config", config, "--target", "consumer")
                self.assertTrue(library.is_file(), "Deleted byproduct was not regenerated")

    def test_fetchcontent_single_config_default_release(self):
        self.exercise("Ninja", ["Release"], build_type="")

    def test_fetchcontent_single_config_initialized_debug(self):
        self.exercise("Ninja", ["Debug"])

    def test_fetchcontent_debug_and_release_do_not_mix(self):
        self.exercise("Ninja Multi-Config", ["Debug", "Release"])


if __name__ == "__main__":
    unittest.main()
