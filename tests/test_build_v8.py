import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_v8 as driver
import update_v8


def config(**overrides):
    values = dict(config="Release", target_os="linux", target_cpu="x64", i18n="ON",
                  runtime="MultiThreadedDLL", deployment_target="", mac_sdk="", sysroot="")
    values.update(overrides)
    return values


class BuildContractTests(unittest.TestCase):
    def test_public_abi_and_self_contained_archive(self):
        args = driver.gn_args(config())
        for value in ("v8_generate_external_defines_header = true",
                      "v8_monolithic = true", "v8_use_external_startup_data = false",
                      "icu_use_data_file = false", "use_custom_libcxx = false"):
            self.assertIn(value, args)

    def test_linux_cross_sysroot_and_cpu(self):
        args = driver.gn_args(config(target_cpu="arm64", sysroot="/opt/arm sysroot"))
        self.assertIn('target_cpu = "arm64"', args)
        self.assertIn('v8_target_cpu = "arm64"', args)
        self.assertIn('target_sysroot = "/opt/arm sysroot"', args)
        self.assertIn('use_sysroot = false', args)

    def test_windows_crt_configurations(self):
        for debug in (False, True):
            for dynamic in (False, True):
                runtime = "MultiThreaded" + ("Debug" if debug else "") + ("DLL" if dynamic else "")
                args = driver.gn_args(config(target_os="win", config="Debug" if debug else "Release", runtime=runtime))
                self.assertIn("v8_cmake_use_dynamic_crt = " + str(dynamic).lower(), args)
        with self.assertRaisesRegex(ValueError, "must match"):
            driver.gn_args(config(target_os="win", config="Debug"))

    def test_mac_sdk_and_deployment(self):
        args = driver.gn_args(config(target_os="mac", target_cpu="arm64",
                                    deployment_target="14.0", mac_sdk="macosx"))
        self.assertIn('mac_deployment_target = "14.0"', args)
        self.assertIn('mac_sdk_name = "macosx"', args)

    def test_gn_quoting(self):
        self.assertEqual(driver.gn_string('C:\\a b\\$x"y'), '"C:/a b/\\$x\\"y"')
        with self.assertRaises(ValueError):
            driver.gn_string("/path\ninjected=true")

    def test_offline_never_starts_a_download(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(driver, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Offline mode"):
                driver.checkout_depot(Path(temp) / "depot", "a" * 40, True)
            run.assert_not_called()

    def test_child_environment_preserves_user_git_settings(self):
        original = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.proxy",
                    "GIT_CONFIG_VALUE_0": "http://example.invalid"}
        with patch.dict(os.environ, original, clear=True):
            env = driver.build_environment(Path("/tools"))
            self.assertEqual(env["GIT_CONFIG_VALUE_0"], original["GIT_CONFIG_VALUE_0"])
            self.assertEqual(env["GIT_CONFIG_COUNT"], "3")
            self.assertEqual(os.environ["GIT_CONFIG_COUNT"], "1")
            self.assertEqual(env["DEPOT_TOOLS_UPDATE"], "0")

    def test_visual_studio_instance_is_forwarded_to_upstream(self):
        with patch.dict(os.environ, {}, clear=True):
            env = driver.build_environment(None, "C:/VS/2026")
            self.assertEqual(env["GYP_MSVS_OVERRIDE_PATH"], "C:/VS/2026")
            self.assertEqual(env["VSINSTALLDIR"], "C:/VS/2026")
            self.assertNotIn("VSINSTALLDIR", os.environ)

    def test_sync_failure_does_not_leave_success_stamp(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            cfg = config(source="", depot_tools="", offline="OFF")
            lock = driver.load_lock(ROOT / "v8-version.json")
            with patch.object(driver, "checkout_depot"), patch.object(driver, "run_download", side_effect=subprocess.CalledProcessError(1, "gclient")):
                with self.assertRaises(subprocess.CalledProcessError):
                    driver.prepare(cfg, lock, workspace)
            self.assertFalse((workspace / ".v8-cmake-sync.json").exists())

    def test_download_retries_are_bounded(self):
        failure = subprocess.CalledProcessError(1, "fetch")
        with patch.object(driver, "run", side_effect=[failure, "done"]) as run, patch.object(driver.time, "sleep"):
            self.assertEqual(driver.run_download(["fetch"]), "done")
            self.assertEqual(run.call_count, 2)
        with patch.object(driver, "run", side_effect=failure) as run, patch.object(driver.time, "sleep"):
            with self.assertRaises(subprocess.CalledProcessError):
                driver.run_download(["fetch"])
            self.assertEqual(run.call_count, 3)

    def test_version_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / "include").mkdir()
            (source / "include/v8-version.h").write_text(
                "#define V8_MAJOR_VERSION 1\n#define V8_MINOR_VERSION 2\n"
                "#define V8_BUILD_NUMBER 3\n#define V8_PATCH_LEVEL 4\n")
            with self.assertRaisesRegex(RuntimeError, "lock requires"):
                driver.check_version(source, "1.2.3.5")

    def test_incremental_staging_and_deleted_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, stage = root / "source", root / "stage"
            (source / "include/cppgc").mkdir(parents=True)
            header = source / "include/cppgc/test.h"
            header.write_text("// test\n")
            generated = root / "v8-gn.h"
            generated.write_text("#define V8_COMPRESS_POINTERS\n")
            driver.stage_headers(source, generated, stage)
            staged = stage / "include/cppgc/test.h"
            timestamp = staged.stat().st_mtime_ns
            driver.stage_headers(source, generated, stage)
            self.assertEqual(timestamp, staged.stat().st_mtime_ns)
            header.unlink()
            driver.stage_headers(source, generated, stage)
            self.assertFalse(staged.exists())
            self.assertTrue((stage / "include/v8-gn.h").exists())

    def test_lock_rejects_floating_revisions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lock.json"
            path.write_text(json.dumps(dict(version="1.2.3.4", revision="main", depot_tools_revision="a" * 40)))
            with self.assertRaisesRegex(ValueError, "immutable"):
                driver.load_lock(path)


class UpdateTests(unittest.TestCase):
    def test_updater_resolves_and_checks_integration_points(self):
        header = "\n".join(f"#define V8_{name} {value}" for name, value in
                           zip(("MAJOR_VERSION", "MINOR_VERSION", "BUILD_NUMBER", "PATCH_LEVEL"), (1, 2, 3, 4)))
        values = [{"commit": "a" * 40}, header,
                  'v8_static_library("v8_monolith") v8_generate_external_defines_header',
                  {"commit": "b" * 40}]
        with patch.object(update_v8, "get", side_effect=values):
            result = update_v8.resolve("1.2.3.4", "HEAD")
        self.assertEqual(result["revision"], "a" * 40)
        self.assertEqual(result["depot_tools_revision"], "b" * 40)

    def test_updater_rejects_missing_integration(self):
        header = "#define V8_MAJOR_VERSION 1\n#define V8_MINOR_VERSION 2\n#define V8_BUILD_NUMBER 3\n#define V8_PATCH_LEVEL 4\n"
        with patch.object(update_v8, "get", side_effect=[{"commit": "a" * 40}, header, ""]):
            with self.assertRaisesRegex(ValueError, "disappeared"):
                update_v8.resolve("1.2.3.4", "HEAD")


if __name__ == "__main__":
    unittest.main()
