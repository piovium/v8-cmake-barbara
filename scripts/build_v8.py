#!/usr/bin/env python3
"""Build upstream V8. All downloads and generated files live in the build tree."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

V8_URL = "https://chromium.googlesource.com/v8/v8.git"
DEPOT_URL = "https://chromium.googlesource.com/chromium/tools/depot_tools.git"


def run(args, *, cwd=None, env=None, capture=False):
    args = [str(arg) for arg in args]
    print("[v8-cmake] " + subprocess.list2cmdline(args), flush=True)
    return subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def enabled(value):
    return str(value).upper() in {"1", "ON", "TRUE", "YES"}


def run_download(args, **kwargs):
    """Retry interrupted transfers without retrying compilation failures."""
    for attempt in range(3):
        try:
            return run(args, **kwargs)
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            print("[v8-cmake] Download failed; retrying...", flush=True)
            time.sleep(5 * (attempt + 1))


def load_lock(path):
    lock = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("revision", "depot_tools_revision"):
        if not re.fullmatch(r"[0-9a-f]{40}", lock[key]):
            raise ValueError(f"{key} must be an immutable 40-character commit SHA")
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", lock["version"]):
        raise ValueError("version must have four numeric components")
    return lock


def write_if_changed(path, content):
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    temporary.replace(path)


@contextlib.contextmanager
def workspace_lock(workspace):
    """OS-owned lock: releases on crashes, serializes shared checkouts/configs."""
    workspace.mkdir(parents=True, exist_ok=True)
    with (workspace / ".v8-cmake.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        print(f"[v8-cmake] Acquiring workspace lock: {workspace}", flush=True)
        if os.name == "nt":
            import msvcrt
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def checkout_depot(path, revision, offline):
    if (path / ".git").exists():
        current = run(["git", "-C", path, "rev-parse", "HEAD"], capture=True).strip()
        if current == revision:
            return
    if offline:
        raise RuntimeError(f"Offline mode: pinned depot_tools is missing at {path}")
    if not (path / ".git").exists():
        path.mkdir(parents=True, exist_ok=True)
        run(["git", "init", path])
        run(["git", "-C", path, "remote", "add", "origin", DEPOT_URL])
    run_download(["git", "-C", path, "fetch", "--depth=1", "origin", revision])
    run(["git", "-C", path, "checkout", "--detach", revision])


def build_environment(depot, vs_install=""):
    env = os.environ.copy()
    # Keep the selected depot_tools revision; use the user's installed SDKs.
    env["DEPOT_TOOLS_UPDATE"] = "0"
    env["DEPOT_TOOLS_WIN_TOOLCHAIN"] = "0"
    env["DEPOT_TOOLS_METRICS"] = "0"
    if vs_install:
        # MSBuild supplies INCLUDE/LIB without necessarily setting VSINSTALLDIR.
        # Upstream vcvars setup only clears those inherited paths when it knows
        # a VS environment is active. Also honor CMake's selected VS instance.
        env["GYP_MSVS_OVERRIDE_PATH"] = vs_install
        env["VSINSTALLDIR"] = vs_install
    # Configure only child Git processes, leaving the user's global Git config
    # intact. Stable line endings keep the Windows patch applicable.
    count = int(env.get("GIT_CONFIG_COUNT", "0"))
    for key, value in (("core.autocrlf", "false"), ("core.longpaths", "true")):
        env[f"GIT_CONFIG_KEY_{count}"] = key
        env[f"GIT_CONFIG_VALUE_{count}"] = value
        count += 1
    env["GIT_CONFIG_COUNT"] = str(count)
    if depot:
        env["PATH"] = str(depot) + os.pathsep + env.get("PATH", "")
    return env


def check_version(source, expected):
    header = (source / "include/v8-version.h").read_text(encoding="utf-8")
    names = ("MAJOR_VERSION", "MINOR_VERSION", "BUILD_NUMBER", "PATCH_LEVEL")
    values = []
    for name in names:
        match = re.search(r"^#define V8_" + name + r"\s+(\d+)\s*$", header, re.M)
        if not match:
            raise RuntimeError(f"Cannot read V8_{name} from {source}")
        values.append(match[1])
    actual = ".".join(values)
    if actual != expected:
        raise RuntimeError(f"V8 checkout is {actual}; lock requires {expected}")


def prepare(config, lock, workspace):
    offline = enabled(config["offline"])
    external = bool(config["source"])
    source = Path(config["source"]).resolve() if external else workspace / "v8"
    depot = Path(config["depot_tools"]).resolve() if config["depot_tools"] else None
    if not external:
        if depot is None:
            depot = workspace / "depot_tools"
            checkout_depot(depot, lock["depot_tools_revision"], offline)
        elif not (depot / "gclient.py").is_file():
            raise RuntimeError(f"No gclient.py in V8_DEPOT_TOOLS_DIR: {depot}")
    env = build_environment(depot, config.get("vs_install", ""))
    if not external:
        # A separate solution directory avoids pulling unrelated Chromium trees.
        solution = {
            "name": "v8", "url": V8_URL, "managed": False,
            "custom_deps": {}, "custom_vars": {},
        }
        gclient = "solutions = " + repr([solution]) + "\n"
        gclient += "target_os = " + repr([config["target_os"]]) + "\n"
        gclient += "target_cpu = " + repr([config["target_cpu"]]) + "\n"
        stamp_value = json.dumps({"lock": lock, "gclient": gclient}, sort_keys=True)
        stamp = workspace / ".v8-cmake-sync.json"
        synced = stamp.exists() and stamp.read_text(encoding="utf-8") == stamp_value
        if not synced or not (source / "build/config/BUILDCONFIG.gn").is_file():
            if offline:
                raise RuntimeError("Offline mode: no completed sync for this V8 version/platform")
            write_if_changed(workspace / ".gclient", gclient)
            # Disabling depot_tools self-updates also skips Windows bootstrap.
            # git_cache.py requires the generated git.bat even with Git on PATH.
            if os.name == "nt" and not (depot / "git.bat").is_file():
                run_download([depot / "bootstrap/win_tools.bat"], cwd=depot, env=env)
            # Use the wrapper so depot_tools bootstraps its own Python packages.
            command = depot / ("gclient.bat" if os.name == "nt" else "gclient")
            run_download([command, "sync", "--no-history", "--shallow",
                 "--revision", "v8@" + lock["revision"]], cwd=workspace, env=env)
            write_if_changed(stamp, stamp_value)
        actual = run(["git", "-C", source, "rev-parse", "HEAD"], capture=True).strip()
        if actual != lock["revision"]:
            raise RuntimeError("Managed V8 checkout moved from the locked commit; use a fresh V8_WORKSPACE")
    check_version(source, lock["version"])
    if not (source / "build/config/BUILDCONFIG.gn").is_file():
        raise RuntimeError(f"V8 dependencies are missing under {source}; run gclient sync first")
    for name in ("system-stl.patch", "system-stl-callable.patch",
                 "system-stl-headers.patch", "system-stl-atomic.patch",
                 "system-stl-constexpr.patch", "system-stl-msvc.patch"):
        apply_patch(source, Path(config["patch"]).with_name(name), external)
    if config["target_os"] == "win":
        apply_runtime_patch(source, Path(config["patch"]), external)
    elif config["target_os"] == "linux":
        apply_patch(source / "build", Path(config["patch"]).with_name("linux-relocations.patch"), external)
    return source, env


def apply_runtime_patch(source, patch, external):
    apply_patch(source / "build", patch, external)


def apply_patch(repository, patch, external):
    base = ["git", "-C", str(repository), "apply"]
    already_applied = subprocess.run(base + ["--reverse", "--check", str(patch)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if already_applied.returncode == 0:
        return
    if external:
        raise RuntimeError(f"Prepared checkout needs {patch.name}; "
                           f"apply it with git -C {repository} apply {patch} first")
    run(base + ["--check", patch])
    run(base + [patch])


def gn_string(value):
    # GN interpolation and path separators differ from JSON.
    value = str(value).replace("\\", "/").replace("$", "\\$").replace('"', '\\"')
    if "\n" in value or "\r" in value:
        raise ValueError("GN string values cannot contain newlines")
    return '"' + value + '"'


def gn_args(config):
    debug = config["config"] == "Debug"
    args = {
        "target_os": config["target_os"], "target_cpu": config["target_cpu"],
        "v8_target_cpu": config["target_cpu"], "is_debug": debug,
        "is_component_build": False, "is_clang": True,
        "v8_monolithic": True, "v8_monolithic_for_shared_library": True,
        "v8_use_host_cpu_arm_features": False,
        "v8_use_external_startup_data": False,
        "v8_generate_external_defines_header": True,
        "v8_enable_i18n_support": enabled(config["i18n"]),
        "icu_use_data_file": False,
        "use_custom_libcxx": False, "use_custom_libcxx_for_host": False,
        # An embedded library must not replace the application's malloc/new.
        "v8_enable_partition_alloc": False,
        # The sandbox in this V8 version requires Chromium's private, hardened
        # libc++. System-STL consumers cannot share that ABI.
        "v8_enable_sandbox": False,
        "v8_enable_temporal_support": False,
        "use_rtti": True, "treat_warnings_as_errors": False,
        "use_remoteexec": False, "use_siso": False,
        "symbol_level": 1 if debug or config["config"] == "RelWithDebInfo" else 0,
    }
    if config["target_os"] == "linux":
        # Chromium enables GLib discovery while loading its Linux compiler
        # config, even though standalone V8 has no GLib dependency.
        args["use_glib"] = False
        # target_sysroot applies independently of use_sysroot. Keep Chromium's
        # implicit Debian sysroot off for host tools using the host libstdc++.
        args["use_sysroot"] = False
        if config["sysroot"]:
            args["target_sysroot"] = config["sysroot"]
    elif config["target_os"] == "mac":
        # Apple's linker understands the installed SDK's TAPI format, including
        # SDK releases newer than the LLVM bundled with this V8 revision.
        args["use_lld"] = False
        args["mac_deployment_target"] = config["deployment_target"] or "12.0"
        if config["mac_sdk"]:
            if Path(config["mac_sdk"]).is_absolute():
                args["mac_sdk_path"] = config["mac_sdk"]
            else:
                args["mac_sdk_name"] = config["mac_sdk"]
    elif config["target_os"] == "win":
        # Match the consumer's default MSVC Debug STL layout.
        args["enable_iterator_debugging"] = True
        runtime = config["runtime"]
        valid = {"MultiThreaded", "MultiThreadedDLL", "MultiThreadedDebug", "MultiThreadedDebugDLL"}
        if runtime not in valid or ("Debug" in runtime) != debug:
            raise ValueError("CMAKE_MSVC_RUNTIME_LIBRARY must match the configuration's Debug/Release CRT")
        args["v8_cmake_use_dynamic_crt"] = runtime.endswith("DLL")
    else:
        raise ValueError("Unsupported target OS")
    lines = []
    for key, value in args.items():
        if isinstance(value, bool):
            rendered = str(value).lower()
        elif isinstance(value, int):
            rendered = str(value)
        else:
            rendered = gn_string(value)
        lines.append(f"{key} = {rendered}\n")
    return "".join(lines)


def copy_if_changed(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        src_stat, dst_stat = source.stat(), destination.stat()
        if src_stat.st_size == dst_stat.st_size and src_stat.st_mtime_ns == dst_stat.st_mtime_ns:
            return
    shutil.copy2(source, destination)


def stage_headers(source, generated, stage):
    include = stage / "include"
    wanted = set()
    for header in (source / "include").rglob("*.h"):
        relative = header.relative_to(source / "include")
        wanted.add(relative)
        copy_if_changed(header, include / relative)
    wanted.add(Path("v8-gn.h"))
    copy_if_changed(generated, include / "v8-gn.h")
    # Prevent stale public headers when rolling V8 in the same build tree.
    for old in include.rglob("*.h"):
        if old.relative_to(include) not in wanted:
            old.unlink()


def build(config):
    if config.get("schema") != 1:
        raise ValueError("Unsupported build configuration schema")
    if config["config"] not in {"Debug", "Release", "RelWithDebInfo", "MinSizeRel"}:
        raise ValueError("Unsupported build configuration")
    arguments = gn_args(config)  # Fail before downloads for invalid settings.
    lock = load_lock(config["lock"])
    workspace = Path(config["workspace"]).resolve()
    output, stage = Path(config["output"]).resolve(), Path(config["stage"]).resolve()
    with workspace_lock(workspace):
        source, env = prepare(config, lock, workspace)
        platform_dir = {"linux": "linux64", "darwin": "mac", "win32": "win"}[sys.platform]
        suffix = ".exe" if os.name == "nt" else ""
        gn = Path(config["gn"] or source / "buildtools" / platform_dir / ("gn" + suffix))
        ninja = Path(config["ninja"] or source / "third_party/ninja" / ("ninja" + suffix))
        for tool in (gn, ninja):
            if not tool.is_file():
                raise RuntimeError(f"Missing tool {tool}; complete gclient sync or provide an executable override")
        write_if_changed(output / "args.gn", arguments)
        run([gn, "gen", output, "--fail-on-unused-args"], cwd=source, env=env)
        command = [ninja, "-C", output]
        if config["jobs"]:
            jobs = int(config["jobs"])
            if jobs < 1:
                raise ValueError("jobs must be positive")
            command += ["-j", jobs]
        run(command + ["v8_monolith"], cwd=source, env=env)
        library = "v8_monolith.lib" if config["target_os"] == "win" else "libv8_monolith.a"
        # A regular, complete archive is produced by upstream v8_static_library.
        copy_if_changed(output / "obj" / library, stage / "lib" / library)
        stage_headers(source, output / "gen/include/v8-gn.h", stage)
        for license_file in source.glob("LICENSE*"):
            if license_file.is_file():
                copy_if_changed(license_file, stage / "licenses" / license_file.name)
        write_if_changed(stage / "build-info.json", json.dumps({
            "requested_lock": lock, "managed_source": not bool(config["source"]),
            "depot_tools_override": config["depot_tools"],
            "configuration": config["config"], "gn_args": arguments,
            "args_sha256": hashlib.sha256(arguments.encode()).hexdigest(),
        }, indent=2) + "\n")
        print(f"[v8-cmake] Ready: {stage / 'lib' / library}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    options = parser.parse_args()
    try:
        build(json.loads(options.config.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"[v8-cmake] ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
