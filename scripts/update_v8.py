#!/usr/bin/env python3
"""Resolve a V8 release tag to immutable commits and update v8-version.json."""

import argparse
import base64
import json
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://chromium.googlesource.com/"


def get(repo, revision, path="", kind="JSON"):
    revision = urllib.parse.quote(revision, safe="/")
    suffix = "/" + path if path else ""
    url = f"{BASE}{repo}/+/{revision}{suffix}?format={kind}"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if kind == "TEXT":
        return base64.b64decode(data).decode("utf-8")
    return json.loads(data.removeprefix(b")]}'\n"))


def resolve(version, depot_ref):
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise ValueError("Use a full release version, for example 14.8.178.33")
    commit = get("v8/v8", "refs/tags/" + version)["commit"]
    header = get("v8/v8", commit, "include/v8-version.h", "TEXT")
    names = ("MAJOR_VERSION", "MINOR_VERSION", "BUILD_NUMBER", "PATCH_LEVEL")
    actual = ".".join(re.search(r"^#define V8_" + name + r"\s+(\d+)\s*$",
                                header, re.M)[1] for name in names)
    if actual != version:
        raise ValueError(f"Tag reports {actual}, expected {version}")
    # Check the two upstream integration points before changing the lock.
    build = get("v8/v8", commit, "BUILD.gn", "TEXT")
    for feature in ('v8_static_library("v8_monolith")', "v8_generate_external_defines_header"):
        if feature not in build:
            raise ValueError(f"Upstream integration point disappeared: {feature}")
    depot_commit = get("chromium/tools/depot_tools", depot_ref)["commit"]
    for revision in (commit, depot_commit):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Server did not return a full commit SHA")
    return {"version": version, "revision": commit, "depot_tools_revision": depot_commit}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Full V8 release tag")
    parser.add_argument("--depot-tools-ref", help="Commit or ref; defaults to the existing pin")
    parser.add_argument("--check", action="store_true", help="Verify the current lock without writing")
    parser.add_argument("--dry-run", action="store_true", help="Print the proposed lock without writing")
    parser.add_argument("--lock-file", type=Path, default=ROOT / "v8-version.json")
    args = parser.parse_args()
    try:
        current = json.loads(args.lock_file.read_text(encoding="utf-8"))
        new = resolve(args.version, args.depot_tools_ref or current["depot_tools_revision"])
        content = json.dumps(new, indent=2) + "\n"
        print(content, end="")
        if args.check:
            if current != new:
                raise ValueError("The current lock differs from the resolved upstream revisions")
        elif not args.dry_run:
            temporary = args.lock_file.with_suffix(".json.tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(args.lock_file)
            print("Updated lock. Follow docs/updating-v8.md and run the complete build matrix.")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"update_v8: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
