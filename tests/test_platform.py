from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("cmake"), "CMake required")
class PlatformTests(unittest.TestCase):
    def check(self, system, processor, expected=None, **settings):
        values = dict(CMAKE_SYSTEM_NAME=system, CMAKE_SYSTEM_PROCESSOR=processor,
                      CMAKE_HOST_SYSTEM_NAME=system, CMAKE_HOST_SYSTEM_PROCESSOR="x86_64",
                      CMAKE_SIZEOF_VOID_P=8)
        values.update(settings)
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "platform.cmake"
            script.write_text(''.join(f'set({key} [==[{value}]==])\n' for key, value in values.items()) +
                              f'include("{ROOT.as_posix()}/cmake/V8Platform.cmake")\n'
                              'v8_cmake_platform(os cpu)\nmessage("RESULT=${os}/${cpu}")\n')
            result = subprocess.run(["cmake", "-P", str(script)], text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if expected:
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("RESULT=" + expected, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def test_supported_targets(self):
        self.check("Linux", "x86_64", "linux/x64")
        self.check("Linux", "aarch64", "linux/arm64", CMAKE_CROSSCOMPILING="ON", CMAKE_SYSROOT="/")
        self.check("Darwin", "arm64", "mac/arm64")
        self.check("Windows", "AMD64", "win/x64", MSVC="ON", CMAKE_GENERATOR_PLATFORM="x64")

    def test_architecture_overrides(self):
        self.check("Darwin", "arm64", "mac/x64", CMAKE_OSX_ARCHITECTURES="x86_64")
        self.assertIn("universal", self.check("Darwin", "arm64", CMAKE_OSX_ARCHITECTURES="x86_64;arm64"))
        self.assertIn("x64 MSVC", self.check("Windows", "AMD64", MSVC="ON", CMAKE_GENERATOR_PLATFORM="ARM64"))

    def test_invalid_cross_configuration(self):
        self.assertIn("requires CMAKE_SYSROOT", self.check("Linux", "aarch64", CMAKE_CROSSCOMPILING="ON"))
        self.assertIn("cross-OS", self.check("Linux", "x64", CMAKE_HOST_SYSTEM_NAME="Darwin"))
        self.assertIn("64 bits", self.check("Linux", "x64", CMAKE_SIZEOF_VOID_P=4))
        self.assertIn("unsupported system", self.check("Android", "arm64"))


if __name__ == "__main__":
    unittest.main()
