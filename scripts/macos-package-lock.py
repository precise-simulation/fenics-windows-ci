#!/usr/bin/env python3
"""Render and verify the immutable macOS conda package locks.

The producer lock is deliberately separate from an environment solver.  The
``explicit`` subcommand turns the checked-in records into a CEP-23-style
``@EXPLICIT`` transaction containing exact URLs and SHA-256 digests.  The
``verify-prefix`` subcommand proves that a prefix created from that transaction
contains exactly the locked package identities before overlay packaging starts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


REQUIRED_FIELDS = (
    "name",
    "version",
    "build",
    "build_number",
    "subdir",
    "channel",
    "url",
    "sha256",
    "md5",
)

QUALIFIED_EXPLICIT_SHA256 = {
    "arm64": "0dfcbf4405646de8a0b96470483ad1371e55e4538d2e6b27bfcfebcc96126547",
    "x86_64": "af133bac1d322cc266e9781e36b920ffbe9afb8af7e462b015946d5f78b58c3f",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lock(path: Path, architecture: str | None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format_version") != 1:
        raise SystemExit(f"unsupported package-lock format: {payload.get('format_version')!r}")
    locked_arch = payload.get("architecture")
    if locked_arch not in {"arm64", "x86_64"}:
        raise SystemExit(f"invalid package-lock architecture: {locked_arch!r}")
    if architecture is not None and locked_arch != architecture:
        raise SystemExit(f"package-lock architecture mismatch: {locked_arch} != {architecture}")
    target_subdir = "osx-arm64" if locked_arch == "arm64" else "osx-64"
    packages = payload.get("packages")
    if not isinstance(packages, list) or not packages:
        raise SystemExit("package lock has no packages")
    if payload.get("record_count") != len(packages):
        raise SystemExit(
            f"package-lock record_count mismatch: {payload.get('record_count')!r} != {len(packages)}"
        )

    seen: set[tuple[str, str, str, str]] = set()
    for index, record in enumerate(packages):
        if not isinstance(record, dict):
            raise SystemExit(f"package-lock record {index} is not an object")
        missing = [field for field in REQUIRED_FIELDS if record.get(field) in (None, "")]
        if missing:
            raise SystemExit(f"package-lock record {index} is missing fields: {missing!r}")
        sha = str(record["sha256"]).lower()
        md5 = str(record["md5"]).lower()
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise SystemExit(f"invalid SHA-256 in package-lock record {index}: {sha!r}")
        if len(md5) != 32 or any(ch not in "0123456789abcdef" for ch in md5):
            raise SystemExit(f"invalid MD5 in package-lock record {index}: {md5!r}")
        url = str(record["url"])
        if not url.startswith("https://conda.anaconda.org/conda-forge/"):
            raise SystemExit(f"package-lock record {index} has unexpected URL: {url!r}")
        if record["subdir"] not in {target_subdir, "noarch"}:
            raise SystemExit(
                f"package-lock record {index} has cross-target subdir: "
                f"{record['subdir']!r} not in {{{target_subdir!r}, 'noarch'}}"
            )
        key = (str(record["name"]), str(record["version"]), str(record["build"]), url)
        if key in seen:
            raise SystemExit(f"duplicate package-lock identity: {key!r}")
        seen.add(key)
    return payload


def qualified_url_order(lock: dict[str, Any], source_explicit: Path) -> list[str]:
    actual_sha = sha256_file(source_explicit)
    expected_sha = QUALIFIED_EXPLICIT_SHA256[lock["architecture"]]
    if actual_sha != expected_sha:
        raise SystemExit(
            f"qualified explicit transaction digest mismatch: {actual_sha} != {expected_sha}"
        )
    urls = [
        line.strip()
        for line in source_explicit.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("https://")
    ]
    locked_urls = [str(record["url"]) for record in lock["packages"]]
    if len(urls) != len(set(urls)):
        raise SystemExit("qualified explicit transaction contains duplicate package URLs")
    if len(locked_urls) != len(set(locked_urls)):
        raise SystemExit("checked-in package lock contains duplicate package URLs")
    if len(urls) != len(locked_urls) or set(urls) != set(locked_urls):
        raise SystemExit("qualified explicit package URL set differs from the checked-in package lock")
    return urls


def render_explicit(lock: dict[str, Any], source_explicit: Path) -> str:
    platform = "osx-arm64" if lock["architecture"] == "arm64" else "osx-64"
    records_by_url = {str(record["url"]): record for record in lock["packages"]}
    urls = qualified_url_order(lock, source_explicit)
    lines = [
        "# Generated from the qualified producer explicit URL order plus checked-in SHA-256 locks.",
        "# Dependency solving is forbidden for this transaction.",
        f"# qualified-explicit-sha256: {sha256_file(source_explicit)}",
        f"# platform: {platform}",
        "@EXPLICIT",
    ]
    for url in urls:
        record = records_by_url[url]
        lines.append(f"{record['url']}#sha256:{str(record['sha256']).lower()}")
    return "\n".join(lines) + "\n"


def normalize_installed_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": record.get("name"),
        "version": record.get("version"),
        "build": record.get("build"),
        "build_number": record.get("build_number"),
        "subdir": record.get("subdir"),
        "channel": record.get("channel"),
        "url": record.get("url"),
        "sha256": record.get("sha256"),
        "md5": record.get("md5"),
    }


def verify_prefix(
    lock: dict[str, Any],
    lock_path: Path,
    prefix: Path,
    package_cache: Path,
    evidence: Path,
) -> None:
    conda_meta = prefix / "conda-meta"
    if not conda_meta.is_dir():
        raise SystemExit(f"locked prefix has no conda metadata: {conda_meta}")

    installed: list[dict[str, Any]] = []
    for path in sorted(conda_meta.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        installed.append(normalize_installed_record(record))

    expected = [normalize_installed_record(record) for record in lock["packages"]]
    expected_by_name = {str(record["name"]): record for record in expected}
    installed_by_name = {str(record["name"]): record for record in installed}
    if len(expected_by_name) != len(expected):
        raise SystemExit("package lock contains duplicate package names; prefix verification is ambiguous")
    if len(installed_by_name) != len(installed):
        raise SystemExit("installed prefix contains duplicate package names; prefix verification is ambiguous")

    missing = sorted(set(expected_by_name) - set(installed_by_name))
    extra = sorted(set(installed_by_name) - set(expected_by_name))
    if missing or extra:
        raise SystemExit(f"locked-prefix package-set mismatch: missing={missing!r} extra={extra!r}")

    mismatches: list[dict[str, Any]] = []
    for name in sorted(expected_by_name):
        exp = expected_by_name[name]
        got = installed_by_name[name]
        differing: dict[str, Any] = {}
        for field in REQUIRED_FIELDS:
            exp_value = exp.get(field)
            got_value = got.get(field)
            if field in {"sha256", "md5"}:
                exp_value = str(exp_value or "").lower()
                got_value = str(got_value or "").lower()
            if exp_value != got_value:
                differing[field] = {"expected": exp_value, "actual": got_value}
        if differing:
            mismatches.append({"name": name, "fields": differing})
    if mismatches:
        raise SystemExit("locked-prefix identity mismatch:\n" + json.dumps(mismatches, indent=2))

    evidence.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 1,
        "architecture": lock["architecture"],
        "lock_record_count": len(expected),
        "installed_record_count": len(installed),
        "lock_sha256": sha256_file(lock_path),
        "package_hash_verification": "micromamba-explicit-sha256-plus-installed-record-match",
        "solver_used": False,
        "packages": [installed_by_name[name] for name in sorted(installed_by_name)],
    }
    evidence.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(dest="command", required=True)

explicit_parser = subparsers.add_parser("explicit", help="render a solver-free @EXPLICIT transaction")
explicit_parser.add_argument("--lock", required=True)
explicit_parser.add_argument("--source-explicit", required=True)
explicit_parser.add_argument("--output", required=True)
explicit_parser.add_argument("--arch", choices=("arm64", "x86_64"))

verify_parser = subparsers.add_parser("verify-prefix", help="verify an installed prefix against the lock")
verify_parser.add_argument("--lock", required=True)
verify_parser.add_argument("--prefix", required=True)
verify_parser.add_argument("--package-cache", required=True)
verify_parser.add_argument("--evidence", required=True)
verify_parser.add_argument("--arch", choices=("arm64", "x86_64"))

args = parser.parse_args()
lock_path = Path(args.lock).resolve()
lock = load_lock(lock_path, args.arch)

if args.command == "explicit":
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_explicit = Path(args.source_explicit).resolve()
    output.write_text(render_explicit(lock, source_explicit), encoding="utf-8")
    print(f"package_lock_sha256={sha256_file(lock_path)}")
    print(f"qualified_explicit_sha256={sha256_file(source_explicit)}")
    print(f"explicit_records={len(lock['packages'])}")
    print("dependency_solver=disabled")
elif args.command == "verify-prefix":
    verify_prefix(
        lock,
        lock_path,
        Path(args.prefix).resolve(),
        Path(args.package_cache).resolve(),
        Path(args.evidence).resolve(),
    )
    print(f"package_lock_sha256={sha256_file(lock_path)}")
    print(f"verified_records={len(lock['packages'])}")
    print("package_hash_verification=micromamba-explicit-sha256-plus-installed-record-match")
else:  # pragma: no cover
    raise AssertionError(args.command)
