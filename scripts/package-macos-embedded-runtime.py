#!/usr/bin/env python3
"""Package a relocatable macOS FEniCS overlay from an exact locked prefix."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from typing import Any, Iterable
from urllib.parse import urlparse


SYSTEM_PREFIXES = ("/usr/lib/", "/System/Library/")
ALLOWED_SOURCE_TOP_LEVEL = {"etc", "include", "lib", "share", "ssl"}
PYTHON_NUMPY_PREFIXES = (
    "lib/python3.12/site-packages/numpy/",
    "lib/python3.12/site-packages/numpy.libs/",
)

EXCLUDED_PACKAGE_NAMES = {
    "_python_abi3_support",
    "cpython",
    "libpython",
    "numpy",
    "pip",
    "python",
    "python-gil",
    "python_abi",
    "tk",
    "wheel",
    # The final JIT compiler is the separately pinned Zig toolchain.  These
    # packages are producer-side compiler/linker inputs and are not runtime
    # ownership of the overlay.
    "cctools",
    "clang",
    "clang-23",
    "compiler-rt",
    "compiler-rt23",
    "ld64",
    "libclang-cpp23.1",
    "libcompiler-rt",
    "libllvm23",
    "libsigtool",
    "llvm-tools",
    "llvm-tools-23",
    "pkg-config",
    "sigtool-codesign",
    "tapi",
}
EXCLUDED_PACKAGE_PREFIXES = (
    "cctools_impl_osx-",
    "clang_impl_osx-",
    "compiler-rt23_osx-",
    "compiler-rt_osx-",
    "ld64_osx-",
)


def run(*argv: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(raw: str) -> PurePosixPath:
    value = raw.replace("\\", "/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "" in path.parts:
        raise SystemExit(f"unsafe package-owned path: {raw!r}")
    return path


def package_excluded(name: str) -> bool:
    return name in EXCLUDED_PACKAGE_NAMES or any(name.startswith(prefix) for prefix in EXCLUDED_PACKAGE_PREFIXES)


def numpy_owned_path(relative: PurePosixPath) -> bool:
    text = relative.as_posix()
    if text.startswith(PYTHON_NUMPY_PREFIXES):
        return True
    return bool(
        re.match(r"^lib/python3\.12/site-packages/numpy-[^/]+\.dist-info(?:/|$)", text)
    )


def overlay_path_exclusion_reason(relative: PurePosixPath) -> str | None:
    text = relative.as_posix()
    if text == "lib/python3.12/site-packages/petsc4py/lib/petsc.cfg":
        return "runtime-derived-petsc4py-config"
    if text.startswith(("lib/pkgconfig/", "lib/cmake/", "share/cmake/", "share/pkgconfig/")):
        return "developer-metadata"
    if text.startswith(("lib/petsc/conf/", "lib/petsc/bin/")):
        return "petsc-build-metadata"
    if relative.suffix == ".la":
        return "libtool-metadata"
    if relative.suffix == ".a":
        return "static-developer-archive"
    return None


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_lock(path: Path, architecture: str) -> dict[str, Any]:
    lock = read_json(path)
    if lock.get("format_version") != 1 or lock.get("architecture") != architecture:
        raise SystemExit(f"invalid package lock for {architecture}: {path}")
    packages = lock.get("packages")
    if not isinstance(packages, list) or lock.get("record_count") != len(packages):
        raise SystemExit("package lock record count is invalid")
    return lock


def installed_records(prefix: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted((prefix / "conda-meta").glob("*.json")):
        record = read_json(path)
        name = str(record.get("name", ""))
        if not name or name in records:
            raise SystemExit(f"ambiguous installed package metadata: {path}")
        records[name] = record
    return records


def package_owned_paths(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return validated package-owned paths, preferring conda paths_data."""

    entries: list[dict[str, Any]] = []
    paths_data = record.get("paths_data")
    raw_paths = paths_data.get("paths") if isinstance(paths_data, dict) else None
    if isinstance(raw_paths, list) and raw_paths:
        for item in raw_paths:
            if not isinstance(item, dict) or not item.get("_path"):
                raise SystemExit(f"invalid paths_data entry for {record.get('name')}: {item!r}")
            entries.append(
                {
                    "path": str(item["_path"]),
                    "path_type": item.get("path_type"),
                    "sha256_in_prefix": item.get("sha256_in_prefix"),
                    "size_in_bytes": item.get("size_in_bytes"),
                }
            )
    else:
        files = record.get("files")
        if not isinstance(files, list):
            raise SystemExit(f"package metadata has neither paths_data nor files: {record.get('name')}")
        entries = [
            {
                "path": str(item),
                "path_type": None,
                "sha256_in_prefix": None,
                "size_in_bytes": None,
            }
            for item in files
        ]

    seen: set[str] = set()
    validated = []
    for entry in entries:
        relative = safe_relative(entry["path"])
        normalized = relative.as_posix()
        if normalized in seen:
            raise SystemExit(f"package metadata repeats an owned path: {record.get('name')}: {normalized}")
        seen.add(normalized)
        entry = dict(entry)
        entry["relative"] = relative
        validated.append(entry)
    return validated


def verify_locked_prefix(lock: dict[str, Any], records: dict[str, dict[str, Any]]) -> None:
    locked = {str(record["name"]): record for record in lock["packages"]}
    if set(locked) != set(records):
        raise SystemExit(
            "locked prefix package-set mismatch: "
            f"missing={sorted(set(locked) - set(records))!r} "
            f"extra={sorted(set(records) - set(locked))!r}"
        )
    fields = ("version", "build", "build_number", "subdir", "channel", "url", "sha256", "md5")
    mismatches = []
    for name in sorted(locked):
        expected = locked[name]
        actual = records[name]
        bad = {}
        for field in fields:
            exp = expected.get(field)
            got = actual.get(field)
            if field in {"sha256", "md5"}:
                exp = str(exp or "").lower()
                got = str(got or "").lower()
            if exp != got:
                bad[field] = {"expected": exp, "actual": got}
        if bad:
            mismatches.append({"name": name, "fields": bad})
    if mismatches:
        raise SystemExit("locked prefix does not match package lock:\n" + json.dumps(mismatches, indent=2))


def verify_package_archives(lock: dict[str, Any], package_cache: Path) -> list[dict[str, Any]]:
    verified = []
    for record in lock["packages"]:
        filename = Path(urlparse(str(record["url"])).path).name
        archive = package_cache / filename
        if not archive.is_file():
            raise SystemExit(f"locked package archive is missing from cache: {archive}")
        actual = sha256_file(archive)
        expected = str(record["sha256"]).lower()
        if actual != expected:
            raise SystemExit(f"locked package archive hash mismatch: {filename}: {actual} != {expected}")
        verified.append(
            {
                "name": record["name"],
                "filename": filename,
                "bytes": archive.stat().st_size,
                "sha256": actual,
            }
        )
    return verified


def copy_path(source: Path, destination: Path, source_prefix: Path, private_prefix: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        raw_target = os.readlink(source)
        target_path = Path(raw_target)
        resolved_target = (
            target_path.resolve(strict=False)
            if target_path.is_absolute()
            else (source.parent / target_path).resolve(strict=False)
        )
        try:
            relative_target = resolved_target.relative_to(source_prefix)
        except ValueError as exc:
            raise SystemExit(f"package symlink escapes producer prefix: {source} -> {raw_target}") from exc
        staged_target = private_prefix / relative_target
        target = os.path.relpath(staged_target, destination.parent)
        if destination.exists() or destination.is_symlink():
            if not destination.is_symlink() or os.readlink(destination) != target:
                raise SystemExit(f"conflicting package ownership at symlink: {destination}")
            return
        os.symlink(target, destination)
        return

    if not source.is_file():
        raise SystemExit(f"package-owned path is not a file/symlink: {source}")
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or sha256_file(source) != sha256_file(destination):
            raise SystemExit(f"conflicting package ownership at file: {destination}")
        return
    shutil.copy2(source, destination, follow_symlinks=False)


def find_cache_record(package_cache: Path, record: dict[str, Any]) -> Path | None:
    expected = (str(record["name"]), str(record["version"]), str(record["build"]))
    direct = package_cache / "-".join(expected)
    candidates: Iterable[Path]
    if (direct / "info" / "index.json").is_file():
        candidates = (direct,)
    else:
        candidates = (path for path in package_cache.iterdir() if path.is_dir())
    for candidate in candidates:
        index = candidate / "info" / "index.json"
        if not index.is_file():
            continue
        try:
            meta = read_json(index)
        except Exception:
            continue
        identity = (str(meta.get("name")), str(meta.get("version")), str(meta.get("build")))
        if identity == expected:
            return candidate
    return None


def collect_package_licenses(
    package_cache: Path,
    records: dict[str, dict[str, Any]],
    retained_packages: list[str],
    stage_root: Path,
    owners: dict[str, list[str]],
) -> dict[str, Any]:
    license_root = stage_root / "fenics-runtime" / "licenses"
    inventory = []
    for name in retained_packages:
        record = records[name]
        cache_record = find_cache_record(package_cache, record)
        copied = []
        metadata = {}
        if cache_record is not None:
            destination_root = license_root / f"{name}-{record['version']}-{record['build']}"
            info_root = cache_record / "info"
            about_path = info_root / "about.json"
            if about_path.is_file():
                about = read_json(about_path)
                metadata = {
                    key: about.get(key)
                    for key in ("license", "license_family", "license_file", "home", "dev_url", "doc_url")
                    if about.get(key) is not None
                }

            sources: list[tuple[Path, Path]] = []
            source_root = info_root / "licenses"
            if source_root.is_dir():
                for source in sorted(source_root.rglob("*")):
                    if source.is_file() and not source.is_symlink():
                        sources.append((source, Path("licenses") / source.relative_to(source_root)))
            for source in sorted(info_root.glob("license*")):
                if source.is_file() and not source.is_symlink():
                    sources.append((source, Path(source.name)))

            seen_sources: set[Path] = set()
            for source, rel in sources:
                resolved = source.resolve()
                if resolved in seen_sources:
                    continue
                seen_sources.add(resolved)
                destination = destination_root / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                overlay_rel = destination.relative_to(stage_root).as_posix()
                owners[overlay_rel] = [name]
                copied.append(overlay_rel)

        def authoritative_license_path(relative: str) -> bool:
            path = PurePosixPath(relative)
            lowered_parts = [part.lower() for part in path.parts]
            basename = path.name.lower()
            return (
                "licenses" in lowered_parts
                or basename.startswith(("license", "copying", "notice", "copyright"))
            )

        staged_license_paths = sorted(
            relative
            for relative, path_owners in owners.items()
            if name in path_owners and authoritative_license_path(relative)
        )
        if not copied and not staged_license_paths:
            raise SystemExit(
                f"retained package has no auditable license material in cache or staged payload: {name}"
            )
        inventory.append(
            {
                "name": name,
                "version": record.get("version"),
                "build": record.get("build"),
                "license": record.get("license"),
                "license_family": record.get("license_family"),
                "about": metadata,
                "license_files": copied,
                "staged_license_paths": staged_license_paths,
            }
        )
    return {"format_version": 1, "packages": inventory}


def copy_tree(source: Path, destination: Path, stage_root: Path, owners: dict[str, list[str]], owner: str) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            raw_link = os.readlink(path)
            link_path = Path(raw_link)
            resolved_link = (
                link_path.resolve(strict=False)
                if link_path.is_absolute()
                else (path.parent / link_path).resolve(strict=False)
            )
            try:
                inside = resolved_link.relative_to(source)
            except ValueError as exc:
                raise SystemExit(f"symlink escapes copied tree: {path} -> {raw_link}") from exc
            link = os.path.relpath(destination / inside, target.parent)
            os.symlink(link, target)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target, follow_symlinks=False)
        else:
            continue
        owners[target.relative_to(stage_root).as_posix()] = [owner]


def verify_symlink_closure(stage_root: Path) -> None:
    root = stage_root.resolve()
    for path in sorted(stage_root.rglob("*")):
        if not path.is_symlink():
            continue
        raw_target = os.readlink(path)
        target = Path(raw_target)
        resolved = (
            target.resolve(strict=False)
            if target.is_absolute()
            else (path.parent / target).resolve(strict=False)
        )
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise SystemExit(f"staged overlay symlink escapes payload: {path} -> {raw_target}") from exc
        if not resolved.exists():
            raise SystemExit(f"staged overlay contains dangling symlink: {path} -> {raw_target}")


def is_macho(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    result = run("file", "-b", str(path), check=False)
    return result.returncode == 0 and "Mach-O" in result.stdout


def macho_dependencies(path: Path) -> list[str]:
    output = run("otool", "-L", str(path)).stdout.splitlines()[1:]
    dependencies = []
    for line in output:
        stripped = line.strip()
        if not stripped:
            continue
        dependencies.append(stripped.split(" (compatibility version", 1)[0].strip())
    return dependencies


def macho_rpaths(path: Path) -> list[str]:
    lines = run("otool", "-l", str(path)).stdout.splitlines()
    rpaths = []
    for index, line in enumerate(lines):
        if line.strip() != "cmd LC_RPATH":
            continue
        for probe in lines[index + 1 : index + 8]:
            stripped = probe.strip()
            if stripped.startswith("path "):
                rpaths.append(stripped.removeprefix("path ").split(" (offset", 1)[0])
                break
    return rpaths


def macho_minos(path: Path) -> str | None:
    lines = run("otool", "-l", str(path)).stdout.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("minos "):
            return stripped.split()[1]
    for index, line in enumerate(lines):
        if line.strip() == "cmd LC_VERSION_MIN_MACOSX":
            for probe in lines[index + 1 : index + 8]:
                stripped = probe.strip()
                if stripped.startswith("version "):
                    return stripped.split()[1]
    return None


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def staged_target_for_dependency(
    dependency: str,
    binary: Path,
    source_prefix: Path,
    private_prefix: Path,
    rpaths: list[str],
) -> Path | None:
    if dependency.startswith(str(source_prefix) + os.sep):
        return private_prefix / Path(dependency).relative_to(source_prefix)
    if dependency.startswith("@loader_path/"):
        return (binary.parent / dependency.removeprefix("@loader_path/")).resolve(strict=False)
    if dependency.startswith("@rpath/"):
        suffix = dependency.removeprefix("@rpath/")
        candidates = []
        for rpath in rpaths:
            if rpath == "@loader_path":
                base = binary.parent
            elif rpath.startswith("@loader_path/"):
                base = binary.parent / rpath.removeprefix("@loader_path/")
            elif rpath.startswith(str(source_prefix)):
                base = private_prefix / Path(rpath).relative_to(source_prefix)
            else:
                continue
            candidates.append((base / suffix).resolve(strict=False))
        existing = [candidate for candidate in candidates if candidate.exists()]
        if len(existing) == 1:
            return existing[0]
    if dependency.startswith("@executable_path/") or dependency.startswith("@rpath/"):
        basename = Path(dependency).name
        matches = [path for path in private_prefix.rglob(basename) if path.is_file() or path.is_symlink()]
        real = sorted({path.resolve(strict=False) for path in matches})
        if len(real) == 1:
            return real[0]
    return None


def loader_reference(binary: Path, target: Path) -> str:
    relative = os.path.relpath(target, binary.parent).replace(os.sep, "/")
    return f"@loader_path/{relative}"


def relocate_and_audit_macho(
    stage_root: Path,
    private_prefix: Path,
    source_prefix: Path,
    architecture: str,
) -> dict[str, Any]:
    macho_files = [path for path in sorted(stage_root.rglob("*")) if is_macho(path)]
    rewritten: set[Path] = set()

    for binary in macho_files:
        rpaths = macho_rpaths(binary)
        changes = []
        for dependency in macho_dependencies(binary):
            if dependency.startswith(SYSTEM_PREFIXES):
                continue
            target = staged_target_for_dependency(dependency, binary, source_prefix, private_prefix, rpaths)
            if target is None or not target.exists():
                raise SystemExit(f"cannot resolve private Mach-O dependency: {binary} -> {dependency}")
            try:
                target.resolve().relative_to(stage_root.resolve())
            except ValueError as exc:
                raise SystemExit(f"Mach-O dependency escapes staged overlay: {binary} -> {dependency} -> {target}") from exc
            replacement = loader_reference(binary, target)
            if dependency != replacement:
                changes.append((dependency, replacement))

        mode = stat.S_IMODE(binary.stat().st_mode)
        if changes:
            binary.chmod(mode | stat.S_IWUSR)
            for old, new in changes:
                run("install_name_tool", "-change", old, new, str(binary))
            rewritten.add(binary)

        for rpath in rpaths:
            if rpath.startswith(str(source_prefix)) or rpath.startswith(("/opt/homebrew", "/usr/local", "/Users/")):
                binary.chmod(stat.S_IMODE(binary.stat().st_mode) | stat.S_IWUSR)
                run("install_name_tool", "-delete_rpath", rpath, str(binary))
                rewritten.add(binary)

        if binary.suffix == ".dylib":
            identity_output = run("otool", "-D", str(binary), check=False).stdout.splitlines()
            identity = identity_output[1].strip() if len(identity_output) > 1 else ""
            desired = f"@rpath/{binary.name}"
            if identity and identity != desired:
                binary.chmod(stat.S_IMODE(binary.stat().st_mode) | stat.S_IWUSR)
                run("install_name_tool", "-id", desired, str(binary))
                rewritten.add(binary)

        # Sign every shipped Mach-O after relocation.  This is stronger and
        # simpler than preserving heterogeneous producer signatures.
        binary.chmod(stat.S_IMODE(binary.stat().st_mode) | stat.S_IWUSR)
        run("codesign", "--force", "--sign", "-", "--timestamp=none", str(binary))
        binary.chmod(mode)

    census = []
    max_minos: str | None = None
    for binary in macho_files:
        archs = run("lipo", "-archs", str(binary)).stdout.strip().split()
        if archs != [architecture]:
            raise SystemExit(f"unexpected Mach-O architectures for {binary}: {archs!r}")
        minos = macho_minos(binary)
        if minos is None:
            raise SystemExit(f"Mach-O has no measurable minimum macOS version: {binary}")
        if version_tuple(minos) > version_tuple("14.0"):
            raise SystemExit(f"Mach-O requires macOS newer than 14.0: {binary}: {minos}")
        if max_minos is None or version_tuple(minos) > version_tuple(max_minos):
            max_minos = minos

        rpaths = macho_rpaths(binary)
        for rpath in rpaths:
            if rpath.startswith((str(source_prefix), "/opt/homebrew", "/usr/local", "/Users/")):
                raise SystemExit(f"forbidden Mach-O rpath remains after relocation: {binary}: {rpath}")

        dependencies = macho_dependencies(binary)
        for dependency in dependencies:
            if dependency.startswith(SYSTEM_PREFIXES):
                continue
            target = staged_target_for_dependency(dependency, binary, source_prefix, private_prefix, rpaths)
            if target is None or not target.exists():
                raise SystemExit(f"relocated Mach-O dependency is unresolved: {binary} -> {dependency}")
            try:
                target.resolve().relative_to(stage_root.resolve())
            except ValueError as exc:
                raise SystemExit(f"relocated Mach-O dependency escapes overlay: {binary} -> {dependency}") from exc

        verification = run("codesign", "--verify", "--strict", str(binary), check=False)
        if verification.returncode != 0:
            raise SystemExit(f"ad-hoc signature verification failed for {binary}: {verification.stdout}")
        detail = run("codesign", "-dv", "--verbose=4", str(binary), check=False).stdout
        census.append(
            {
                "path": binary.relative_to(stage_root).as_posix(),
                "architecture": architecture,
                "minos": minos,
                "dependencies": dependencies,
                "rpaths": rpaths,
                "rewritten": binary in rewritten,
                "codesign": "adhoc" if "Signature=adhoc" in detail else "valid",
            }
        )

    return {
        "format_version": 1,
        "architecture": architecture,
        "macho_count": len(census),
        "measured_max_minos": max_minos,
        "system_library_allowlist": list(SYSTEM_PREFIXES),
        "mach_o": census,
    }


def verify_no_runtime_prefix_leaks(stage_root: Path, source_prefix: Path) -> None:
    needle = str(source_prefix).encode("utf-8")
    leaks = []
    for path in sorted(stage_root.rglob("*")):
        if path.is_symlink() or not path.is_file() or is_macho(path):
            continue
        data = path.read_bytes()
        if b"\x00" in data:
            continue
        if needle in data:
            leaks.append(path.relative_to(stage_root).as_posix())
    if leaks:
        raise SystemExit(f"producer prefix remains in staged runtime text/configuration: {leaks!r}")


def rewrite_text_prefixes(stage_root: Path, source_prefix: Path) -> list[dict[str, Any]]:
    """Remove installed conda prefixes from relocatable text/config payloads.

    Conda legitimately substitutes its installation prefix into text files at
    link time.  Those absolute producer paths cannot survive in a relocatable
    overlay.  Runtime-critical roots are supplied by ``fenics_embed_runtime``;
    developer/config metadata that is retained for package completeness gets a
    conspicuous non-absolute marker instead of the producer path.
    """

    needle = str(source_prefix).encode("utf-8")
    marker = b"@FENICS_RUNTIME_PREFIX@"
    rewritten = []
    for path in sorted(stage_root.rglob("*")):
        if path.is_symlink() or not path.is_file() or is_macho(path):
            continue
        data = path.read_bytes()
        if b"\x00" in data or needle not in data:
            continue
        count = data.count(needle)
        before_sha256 = sha256_bytes(data)
        mode = stat.S_IMODE(path.stat().st_mode)
        rewritten_data = data.replace(needle, marker)
        path.write_bytes(rewritten_data)
        path.chmod(mode)
        rewritten.append(
            {
                "path": path.relative_to(stage_root).as_posix(),
                "occurrences": count,
                "replacement": marker.decode("ascii"),
                "before_sha256": before_sha256,
                "after_sha256": sha256_bytes(rewritten_data),
            }
        )
    return rewritten


def file_entry(path: Path, stage_root: Path, owners: dict[str, list[str]]) -> dict[str, Any]:
    relative = path.relative_to(stage_root).as_posix()
    if relative not in owners or not owners[relative]:
        raise SystemExit(f"staged overlay file has no explicit owner: {relative}")
    mode = stat.S_IMODE(os.lstat(path).st_mode)
    if path.is_symlink():
        data = os.readlink(path).encode("utf-8")
        kind = "symlink"
    else:
        data = path.read_bytes()
        kind = "file"
    return {
        "path": relative,
        "kind": kind,
        "mode": oct(mode),
        "size": len(data),
        "sha256": sha256_bytes(data),
        "owners": sorted(set(owners[relative])),
    }


def deterministic_zip(stage_root: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage_root.rglob("*")):
            if path.is_dir() and not path.is_symlink():
                continue
            relative = path.relative_to(stage_root).as_posix()
            mode = stat.S_IMODE(os.lstat(path).st_mode)
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            if path.is_symlink():
                info.external_attr = (stat.S_IFLNK | mode) << 16
                data = os.readlink(path).encode("utf-8")
                archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            else:
                info.external_attr = (stat.S_IFREG | mode) << 16
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


parser = argparse.ArgumentParser()
parser.add_argument("--prefix", required=True)
parser.add_argument("--lock", required=True)
parser.add_argument("--package-cache", required=True)
parser.add_argument("--zig-root", required=True)
parser.add_argument("--zig-archive", required=True)
parser.add_argument("--zig-sha256", required=True)
parser.add_argument("--arch", required=True, choices=("arm64", "x86_64"))
parser.add_argument("--output", required=True)
parser.add_argument("--version", default="0.1.0")
parser.add_argument("--producer-revision", required=True)
args = parser.parse_args()

if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
    raise SystemExit(f"overlay version must be X.Y.Z: {args.version!r}")

prefix = Path(args.prefix).resolve()
lock_path = Path(args.lock).resolve()
package_cache = Path(args.package_cache).resolve()
zig_root = Path(args.zig_root).resolve()
output = Path(args.output).resolve()
bootstrap_source = Path(__file__).resolve().with_name("fenics-embed-bootstrap-macos.py")

for required in (prefix / "conda-meta", lock_path, package_cache, zig_root / "zig", bootstrap_source):
    if not required.exists():
        raise SystemExit(f"required producer input is missing: {required}")
if not re.fullmatch(r"[0-9a-f]{64}", args.zig_sha256.lower()):
    raise SystemExit("invalid Zig SHA-256")

lock = load_lock(lock_path, args.arch)
records = installed_records(prefix)
verify_locked_prefix(lock, records)
verified_archives = verify_package_archives(lock, package_cache)

required_versions = {
    "fenics-dolfinx": "0.11.0",
    "petsc": "3.25.6",
    "petsc4py": "3.25.6",
    "mpi4py": "4.1.2",
    "mpich": "5.0.1",
    "fenics-basix": "0.11.0",
    "fenics-ffcx": "0.11.0",
    "fenics-ufl": "2026.1.0",
    "numpy": "2.5.2",
    "python": "3.12.16",
}
for name, version in required_versions.items():
    if str(records.get(name, {}).get("version")) != version:
        raise SystemExit(f"locked prefix has unexpected {name} version: {records.get(name, {}).get('version')!r}")

output.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix=f"fenics-macos-overlay-{args.arch}-"))
stage_root = work / "stage"
private_prefix = stage_root / "fenics-runtime" / "conda"
stage_root.mkdir(parents=True)
owners: dict[str, list[str]] = defaultdict(list)
retained_packages: list[str] = []
excluded_packages: list[str] = []
not_staged_packages: list[str] = []
excluded_owned_paths: list[dict[str, str]] = []

try:
    for lock_record in lock["packages"]:
        name = str(lock_record["name"])
        record = records[name]
        if package_excluded(name):
            excluded_packages.append(name)
            continue
        contributed = False
        for owned in package_owned_paths(record):
            relative = owned["relative"]
            if numpy_owned_path(relative):
                raise SystemExit(f"non-NumPy package unexpectedly owns a NumPy path: {name}: {relative}")
            exclusion_reason = overlay_path_exclusion_reason(relative)
            if exclusion_reason is not None:
                excluded_owned_paths.append(
                    {"package": name, "path": relative.as_posix(), "reason": exclusion_reason}
                )
                continue
            if not relative.parts or relative.parts[0] not in ALLOWED_SOURCE_TOP_LEVEL:
                continue
            source = prefix.joinpath(*relative.parts)
            if not source.exists() and not source.is_symlink():
                raise SystemExit(f"package-owned source file is missing: {name}: {relative}")
            destination = private_prefix.joinpath(*relative.parts)
            destination_relative = destination.relative_to(stage_root).as_posix()
            if destination_relative in owners and name not in owners[destination_relative]:
                raise SystemExit(
                    "ambiguous multi-package overlay ownership: "
                    f"{destination_relative}: existing={owners[destination_relative]!r} new={name!r}"
                )
            expected_prefix_sha = owned.get("sha256_in_prefix")
            if expected_prefix_sha and source.is_file() and not source.is_symlink():
                actual_prefix_sha = sha256_file(source)
                if actual_prefix_sha != str(expected_prefix_sha).lower():
                    raise SystemExit(
                        f"installed package-owned file hash mismatch: {name}: {relative}: "
                        f"{actual_prefix_sha} != {expected_prefix_sha}"
                    )
            copy_path(source, destination, prefix, private_prefix)
            owners[destination_relative].append(name)
            contributed = True
        if contributed:
            retained_packages.append(name)
        else:
            not_staged_packages.append(name)

    # The bridge-owned NumPy distribution and producer CPython must never be
    # represented anywhere in the emitted overlay.
    staged_numpy = [
        path.relative_to(stage_root).as_posix()
        for path in stage_root.rglob("*")
        if "site-packages/numpy" in path.as_posix()
    ]
    if staged_numpy:
        raise SystemExit(f"overlay contains forbidden producer NumPy paths: {staged_numpy[:20]!r}")

    bootstrap_destination = (
        stage_root
        / "Python.framework"
        / "Versions"
        / "3.12"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "fenics_embed_runtime.py"
    )
    bootstrap_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bootstrap_source, bootstrap_destination)
    owners[bootstrap_destination.relative_to(stage_root).as_posix()] = ["fenics-windows-ci"]

    zig_destination = stage_root / "fenics-runtime" / "zig"
    copy_tree(zig_root, zig_destination, stage_root, owners, "zig-0.15.2")

    provenance = stage_root / "fenics-runtime" / "provenance"
    provenance.mkdir(parents=True, exist_ok=True)
    lock_copy = provenance / f"macos-{args.arch}-package-lock.json"
    shutil.copy2(lock_path, lock_copy)
    owners[lock_copy.relative_to(stage_root).as_posix()] = ["fenics-windows-ci"]

    license_inventory = collect_package_licenses(
        package_cache, records, retained_packages, stage_root, owners
    )
    license_inventory["zig"] = {
        "version": "0.15.2",
        "archive": args.zig_archive,
        "sha256": args.zig_sha256.lower(),
        "license_path": "fenics-runtime/zig/LICENSE",
    }
    licenses_path = provenance / "third-party-licenses.json"
    licenses_path.write_text(json.dumps(license_inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    owners[licenses_path.relative_to(stage_root).as_posix()] = ["fenics-windows-ci"]

    text_rewrites = rewrite_text_prefixes(stage_root, prefix)
    text_rewrites_path = provenance / "text-prefix-rewrites.json"
    text_rewrites_path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "producer_prefix_sha256": sha256_bytes(str(prefix).encode("utf-8")),
                "replacement": "@FENICS_RUNTIME_PREFIX@",
                "files": text_rewrites,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    owners[text_rewrites_path.relative_to(stage_root).as_posix()] = ["fenics-windows-ci"]

    census = relocate_and_audit_macho(stage_root, private_prefix, prefix, args.arch)
    census_path = provenance / "native-census.json"
    census_path.write_text(json.dumps(census, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    owners[census_path.relative_to(stage_root).as_posix()] = ["fenics-windows-ci"]

    verify_symlink_closure(stage_root)
    verify_no_runtime_prefix_leaks(stage_root, prefix)

    files = [
        file_entry(path, stage_root, owners)
        for path in sorted(stage_root.rglob("*"))
        if path.is_symlink() or path.is_file()
    ]
    package_summary = []
    for lock_record in lock["packages"]:
        name = str(lock_record["name"])
        if package_excluded(name):
            ownership = "excluded-policy"
        elif name in retained_packages:
            ownership = "retained"
        else:
            ownership = "not-staged"
        package_summary.append(
            {
                key: lock_record.get(key)
                for key in ("name", "version", "build", "build_number", "subdir", "url", "sha256", "md5")
            }
            | {"overlay_ownership": ownership}
        )

    asset_arch = "arm64" if args.arch == "arm64" else "x64"
    asset_name = f"fenics-embed-runtime-v{args.version}-macos-{asset_arch}-cp312.zip"
    manifest = {
        "format_version": 1,
        "artifact": asset_name.removesuffix(".zip"),
        "version": args.version,
        "platform": f"macos-{asset_arch}",
        "architecture": args.arch,
        "python_abi": "cp312",
        "consumer_python": "3.12.10",
        "producer_python": "3.12.16",
        "numpy": {
            "version": "2.5.2",
            "ownership": "bridge-phase03",
            "producer_payload_excluded": True,
        },
        "producer": {
            "repository": "precise-simulation/fenics-windows-ci",
            "revision": args.producer_revision,
            "package_lock": lock_copy.relative_to(stage_root).as_posix(),
            "package_lock_sha256": sha256_file(lock_path),
            "package_count": len(lock["packages"]),
            "package_archive_hash_verification": "pass",
            "package_archive_count": len(verified_archives),
            "retained_packages": retained_packages,
            "excluded_packages": excluded_packages,
            "not_staged_packages": not_staged_packages,
            "excluded_owned_paths": excluded_owned_paths,
        },
        "zig": {
            "version": "0.15.2",
            "archive": args.zig_archive,
            "sha256": args.zig_sha256.lower(),
            "target": "aarch64-macos.14.0" if args.arch == "arm64" else "x86_64-macos.14.0",
        },
        "layout": {
            "private_prefix": "fenics-runtime/conda",
            "private_site_packages": "fenics-runtime/conda/lib/python3.12/site-packages",
            "zig_root": "fenics-runtime/zig",
            "bootstrap": "Python.framework/Versions/3.12/lib/python3.12/site-packages/fenics_embed_runtime.py",
        },
        "native": {
            "census": census_path.relative_to(stage_root).as_posix(),
            "census_sha256": sha256_file(census_path),
            "macho_count": census["macho_count"],
            "measured_max_minos": census["measured_max_minos"],
            "signing": "adhoc-all-shipped-macho",
        },
        "relocation": {
            "text_prefix_rewrites": text_rewrites_path.relative_to(stage_root).as_posix(),
            "text_prefix_rewrites_sha256": sha256_file(text_rewrites_path),
            "text_prefix_rewrite_count": len(text_rewrites),
        },
        "licenses": {
            "inventory": licenses_path.relative_to(stage_root).as_posix(),
            "inventory_sha256": sha256_file(licenses_path),
        },
        "files": files,
    }
    manifest_path = stage_root / "fenics-embed-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    zip_path = output / asset_name
    if zip_path.exists():
        zip_path.unlink()
    deterministic_zip(stage_root, zip_path)
    manifest_hash = sha256_file(manifest_path)
    zip_hash = sha256_file(zip_path)
    summary = {
        "format_version": 1,
        "artifact": asset_name,
        "artifact_bytes": zip_path.stat().st_size,
        "sha256": zip_hash,
        "manifest_sha256": manifest_hash,
        "package_lock_sha256": sha256_file(lock_path),
        "overlay_file_count": len(files) + 1,
        "macho_count": census["macho_count"],
    }
    summary_path = output / f"{asset_name}.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / f"{asset_name}.sha256").write_text(f"{zip_hash}  {asset_name}\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
finally:
    shutil.rmtree(work, ignore_errors=True)
