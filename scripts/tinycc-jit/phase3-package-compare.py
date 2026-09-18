"""Compare TinyCC package builds and qualify Phase 4B JIT package ownership."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

EARLY_GATE_BYTES = int(216.43 * 1024 * 1024 * 0.25)
RUNTIME_PACKAGE = "fenics-jit-runtime"
LLVM_PACKAGE = "fenics-jit-llvm-mingw"
TINYCC_PACKAGE = "fenics-jit-tinycc"
PACKAGE_ROOTS = {
    RUNTIME_PACKAGE: "library/fenics-jit/runtime/",
    LLVM_PACKAGE: "library/fenics-jit/backends/llvm-mingw/",
    TINYCC_PACKAGE: "library/fenics-jit/backends/tinycc/",
}


def package_record(prefix: Path, name: str) -> dict:
    matches = sorted((prefix / "conda-meta").glob(f"{name}-*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {name} conda record below {prefix}, got {matches}")
    return json.loads(matches[0].read_text(encoding="utf-8"))


def maybe_package_record(prefix: Path, name: str) -> dict | None:
    matches = sorted((prefix / "conda-meta").glob(f"{name}-*.json"))
    if len(matches) > 1:
        raise RuntimeError(f"expected at most one {name} conda record below {prefix}, got {matches}")
    return json.loads(matches[0].read_text(encoding="utf-8")) if matches else None


def record_files(record: dict) -> list[str]:
    return sorted(str(item).replace("\\", "/") for item in record.get("files", []))


def payload(prefix: Path) -> tuple[dict[str, dict[str, object]], dict]:
    record = package_record(prefix, TINYCC_PACKAGE)
    files = record_files(record)
    if not files:
        raise RuntimeError("fenics-jit-tinycc package record has no files")
    forbidden = [path for path in files if path.lower().startswith("library/fenics-jit/runtime/")]
    if forbidden:
        raise RuntimeError(f"TinyCC package illegally owns shared runtime paths: {forbidden}")
    outside = [path for path in files if not path.lower().startswith(PACKAGE_ROOTS[TINYCC_PACKAGE])]
    if outside:
        raise RuntimeError(f"TinyCC package owns paths outside its backend root: {outside}")

    manifest: dict[str, dict[str, object]] = {}
    for relative in files:
        path = prefix / Path(relative)
        if not path.is_file():
            raise RuntimeError(f"installed package file missing: {path}")
        data = path.read_bytes()
        manifest[relative] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return manifest, record


def dependency_names(record: dict) -> set[str]:
    names: set[str] = set()
    for spec in record.get("depends", []):
        text = str(spec).strip()
        if text:
            names.add(text.split()[0].lower())
    return names


def package_manifest(prefix: Path, name: str) -> dict[str, str]:
    record = package_record(prefix, name)
    files = record_files(record)
    if not files:
        raise RuntimeError(f"{name} package record has no files")

    expected_root = PACKAGE_ROOTS[name]
    outside = [path for path in files if not path.lower().startswith(expected_root)]
    if outside:
        raise RuntimeError(f"{name} owns paths outside {expected_root}: {outside}")

    manifest: dict[str, str] = {}
    for relative in files:
        path = prefix / Path(relative)
        if not path.is_file():
            raise RuntimeError(f"{name} owned file is missing: {path}")
        manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def assert_manifest(prefix: Path, name: str, expected: dict[str, str]) -> None:
    actual = package_manifest(prefix, name)
    if actual != expected:
        keys = sorted(set(actual) | set(expected))
        differences = [key for key in keys if actual.get(key) != expected.get(key)]
        raise RuntimeError(f"{name} payload changed unexpectedly: {differences}")


def assert_package_absent(prefix: Path, name: str, owned_files: dict[str, str]) -> None:
    if maybe_package_record(prefix, name) is not None:
        raise RuntimeError(f"{name} conda record remains after uninstall")
    survivors = [relative for relative in owned_files if (prefix / Path(relative)).exists()]
    if survivors:
        raise RuntimeError(f"{name} owned files remain after uninstall: {survivors}")


def local_package(output_dir: Path, name: str) -> Path:
    matches = sorted(output_dir.glob(f"{name}-*.conda"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one local {name} package in {output_dir}, got {matches}")
    return matches[0].resolve()


def micromamba_executable() -> Path:
    configured = os.environ.get("MAMBA_EXE")
    if configured:
        candidate = Path(configured).resolve()
        if candidate.is_file():
            return candidate
    found = shutil.which("micromamba.exe") or shutil.which("micromamba")
    if found:
        return Path(found).resolve()
    raise RuntimeError("micromamba executable is unavailable for Phase 4B ownership qualification")


def run_mamba(mamba: Path, *args: str) -> None:
    subprocess.run([str(mamba), *args], check=True)


def verify_selector(prefix: Path, backend: str) -> None:
    selector = prefix / "Library/fenics-jit/runtime/fenics_jit_selector.py"
    if not selector.is_file():
        raise RuntimeError(f"shared runtime selector is missing after package transition: {selector}")
    python = prefix / "python.exe"
    if not python.is_file():
        raise RuntimeError(f"prefix Python is missing after package transition: {python}")

    probe = (
        "import importlib.util, pathlib, sys; "
        "p=pathlib.Path(sys.argv[1]).resolve(); "
        "s=importlib.util.spec_from_file_location('phase4b_ownership_selector', p); "
        "m=importlib.util.module_from_spec(s); "
        "sys.modules[s.name]=m; "
        "s.loader.exec_module(m); "
        "r=m.discover_runtime(); "
        "assert r.selected_backend == sys.argv[2], (r.selected_backend, sys.argv[2]); "
        "assert r.backend_root.is_dir(), r.backend_root; "
        "print(r.selected_backend, r.backend_cache_id, r.backend_root)"
    )
    env = dict(os.environ)
    env["FENICS_JIT_COMPILER"] = backend
    subprocess.run(
        [str(python), "-c", probe, str(selector), backend],
        check=True,
        env=env,
        cwd=prefix,
    )


def qualify_package_ownership(base_prefix: Path, package_dir: Path) -> dict[str, object]:
    local_packages = {
        name: local_package(package_dir, name)
        for name in (RUNTIME_PACKAGE, LLVM_PACKAGE, TINYCC_PACKAGE)
    }
    mamba = micromamba_executable()
    prefix = (base_prefix.parent / "phase4b ownership with spaces").resolve()
    if prefix.exists():
        shutil.rmtree(prefix)

    run_mamba(
        mamba,
        "create",
        "-y",
        "-p",
        str(prefix),
        "--override-channels",
        "--strict-channel-priority",
        "-c",
        "conda-forge",
        "python=3.12",
        "cffi=2.1.*",
        "setuptools=84.*",
        str(local_packages[RUNTIME_PACKAGE]),
        str(local_packages[LLVM_PACKAGE]),
        str(local_packages[TINYCC_PACKAGE]),
    )

    records = {
        name: package_record(prefix, name)
        for name in (RUNTIME_PACKAGE, LLVM_PACKAGE, TINYCC_PACKAGE)
    }
    manifests = {
        name: package_manifest(prefix, name)
        for name in (RUNTIME_PACKAGE, LLVM_PACKAGE, TINYCC_PACKAGE)
    }

    names = tuple(manifests)
    overlaps: dict[str, list[str]] = {}
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            overlap = sorted(set(manifests[left]) & set(manifests[right]))
            if overlap:
                overlaps[f"{left}::{right}"] = overlap
    if overlaps:
        raise RuntimeError(f"JIT package file ownership overlaps: {overlaps}")

    dependencies = {name: sorted(dependency_names(record)) for name, record in records.items()}
    runtime_dependencies = set(dependencies[RUNTIME_PACKAGE])
    forbidden_runtime_dependencies = runtime_dependencies & {LLVM_PACKAGE, TINYCC_PACKAGE}
    if forbidden_runtime_dependencies:
        raise RuntimeError(
            "fenics-jit-runtime depends on compiler backend(s): "
            f"{sorted(forbidden_runtime_dependencies)}"
        )
    if RUNTIME_PACKAGE not in dependencies[LLVM_PACKAGE]:
        raise RuntimeError("fenics-jit-llvm-mingw does not depend on fenics-jit-runtime")
    if RUNTIME_PACKAGE not in dependencies[TINYCC_PACKAGE]:
        raise RuntimeError("fenics-jit-tinycc does not depend on fenics-jit-runtime")
    if LLVM_PACKAGE in dependencies[TINYCC_PACKAGE]:
        raise RuntimeError("fenics-jit-tinycc unexpectedly depends on fenics-jit-llvm-mingw")
    if TINYCC_PACKAGE in dependencies[LLVM_PACKAGE]:
        raise RuntimeError("fenics-jit-llvm-mingw unexpectedly depends on fenics-jit-tinycc")

    run_mamba(mamba, "remove", "-y", "-p", str(prefix), TINYCC_PACKAGE)
    assert_manifest(prefix, RUNTIME_PACKAGE, manifests[RUNTIME_PACKAGE])
    assert_manifest(prefix, LLVM_PACKAGE, manifests[LLVM_PACKAGE])
    assert_package_absent(prefix, TINYCC_PACKAGE, manifests[TINYCC_PACKAGE])
    verify_selector(prefix, "llvm-mingw")

    run_mamba(mamba, "install", "-y", "-p", str(prefix), str(local_packages[TINYCC_PACKAGE]))
    for name in (RUNTIME_PACKAGE, LLVM_PACKAGE, TINYCC_PACKAGE):
        assert_manifest(prefix, name, manifests[name])

    run_mamba(mamba, "remove", "-y", "-p", str(prefix), LLVM_PACKAGE)
    assert_manifest(prefix, RUNTIME_PACKAGE, manifests[RUNTIME_PACKAGE])
    assert_manifest(prefix, TINYCC_PACKAGE, manifests[TINYCC_PACKAGE])
    assert_package_absent(prefix, LLVM_PACKAGE, manifests[LLVM_PACKAGE])
    verify_selector(prefix, "tinycc")

    run_mamba(mamba, "install", "-y", "-p", str(prefix), str(local_packages[LLVM_PACKAGE]))
    for name in (RUNTIME_PACKAGE, LLVM_PACKAGE, TINYCC_PACKAGE):
        assert_manifest(prefix, name, manifests[name])

    return {
        "status": "pass",
        "test_prefix": str(prefix),
        "package_roots": PACKAGE_ROOTS,
        "file_counts": {name: len(manifest) for name, manifest in manifests.items()},
        "dependencies": dependencies,
        "pairwise_overlap": {},
        "uninstall_reinstall": {
            "tinycc_removed_without_runtime_or_llvm_change": True,
            "llvm_removed_without_runtime_or_tinycc_change": True,
            "tinycc_only_selector_without_llvm": True,
            "llvm_selector_without_tinycc": True,
            "final_payloads_match_baseline": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix-a", required=True, type=Path)
    parser.add_argument("--prefix-b", required=True, type=Path)
    parser.add_argument("--package-a", required=True, type=Path)
    parser.add_argument("--package-b", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    prefix_a = args.prefix_a.resolve()
    prefix_b = args.prefix_b.resolve()
    manifest_a, record_a = payload(prefix_a)
    manifest_b, record_b = payload(prefix_b)
    if manifest_a != manifest_b:
        keys = sorted(set(manifest_a) | set(manifest_b))
        differences = [key for key in keys if manifest_a.get(key) != manifest_b.get(key)]
        raise RuntimeError(f"clean package rebuild payloads differ: {differences}")

    installed_bytes = sum(int(item["size"]) for item in manifest_a.values())
    if installed_bytes > EARLY_GATE_BYTES:
        raise RuntimeError(
            f"TinyCC installed payload {installed_bytes} bytes exceeds early footprint gate {EARLY_GATE_BYTES} bytes"
        )

    backend_metadata = json.loads(
        (prefix_a / "Library/fenics-jit/backends/tinycc/backend-metadata.json").read_text(encoding="utf-8")
    )
    for forbidden_fragment in (str(prefix_a).lower(), str(prefix_b).lower(), "microsoft visual studio", "windows kits"):
        if forbidden_fragment and forbidden_fragment in json.dumps(backend_metadata).lower():
            raise RuntimeError(f"runtime metadata contains forbidden build/host path fragment: {forbidden_fragment}")

    ownership = qualify_package_ownership(prefix_a, args.package_a.resolve().parent)

    result = {
        "status": "pass",
        "package": record_a.get("name"),
        "version": record_a.get("version"),
        "build": record_a.get("build"),
        "file_count": len(manifest_a),
        "installed_bytes": installed_bytes,
        "installed_mib": installed_bytes / (1024 * 1024),
        "early_gate_bytes": EARLY_GATE_BYTES,
        "early_gate_mib": EARLY_GATE_BYTES / (1024 * 1024),
        "compressed_a_bytes": args.package_a.stat().st_size,
        "compressed_b_bytes": args.package_b.stat().st_size,
        "payload_reproducible": True,
        "backend_cache_id": backend_metadata["backend_cache_id"],
        "tcc_sha256": backend_metadata["tcc_sha256"],
        "libtcc_sha256": backend_metadata["libtcc_sha256"],
        "phase4b_package_ownership": ownership,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
