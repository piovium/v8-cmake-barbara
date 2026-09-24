"""Offline stand-in for GN/Ninja; compiles a tiny real library, never V8."""
from pathlib import Path
import subprocess
import sys

mode = sys.argv[1]
output = Path(sys.argv[3]).resolve()
args = (output / "args.gn").read_text()
debug = "is_debug = true" in args
if mode == "gn":
    header = output / "gen/include/v8-gn.h"
    header.parent.mkdir(parents=True, exist_ok=True)
    content = f"#define V8_FIXTURE_DEBUG {int(debug)}\n"
    if not header.exists() or header.read_text() != content:
        header.write_text(content)
else:
    source = output / "fixture-source"
    source.mkdir(exist_ok=True)
    content = 'int v8_fixture_answer() { return ' + str(43 if debug else 42) + '; }\n'
    cpp = source / "stub.cc"
    if not cpp.exists() or cpp.read_text() != content:
        cpp.write_text(content)
    (source / "CMakeLists.txt").write_text(
        'cmake_minimum_required(VERSION 3.24)\nproject(stub LANGUAGES CXX)\n'
        'add_library(v8_monolith STATIC stub.cc)\n'
        f'set_target_properties(v8_monolith PROPERTIES ARCHIVE_OUTPUT_DIRECTORY "{output.as_posix()}/obj")\n')
    subprocess.run(["cmake", "-S", str(source), "-B", str(output / "fixture-build"),
                    "-G", "Ninja", "-DCMAKE_BUILD_TYPE=" + ("Debug" if debug else "Release")], check=True)
    subprocess.run(["cmake", "--build", str(output / "fixture-build")], check=True)
