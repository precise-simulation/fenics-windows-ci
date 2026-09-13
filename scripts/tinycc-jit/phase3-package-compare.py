"""Compare two clean fenics-jit-tinycc package builds for Phase 3."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EARLY_GATE_BYTES = int(216.43 * 1024 * 1024 * 0.25)


def package_record(prefix: Path) -> dict:
    matches = sorted((prefix / "conda-meta").glob("fenics-jit-tinycc-*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one fenics-jit-tinycc conda record below {prefix}, got {matches}")
    return json.loads(matches[0].read_text(encoding="utf-8"))


def payload(prefix: Path) -> tuple[dict[str, dict[str, object]], dict]:
    record = package_record(prefix)
    files = [str(item).replace("\\", "/") for item in record.get("files", [])]
    if not files:
        raise RuntimeError("fenics-jit-tinycc package record has no files")
    forbidden = [path for path in files if path.lower().startswith("library/fenics-jit/runtime/")]
    if forbidden:
        raise RuntimeError(f"TinyCC package illegally owns shared runtime paths: {forbidden}")
    outside = [path for path in files if not path.lower().startswith("library/fenics-jit/backends/tinycc/")]
    if outside:
        raise RuntimeError(f"TinyCC package owns paths outside its backend root: {outside}")

    manifest: dict[str, dict[str, object]] = {}
    for relative in sorted(files):
        path = prefix / Path(relative)
        if not path.is_file():
            raise RuntimeError(f"installed package file missing: {path}")
        data = path.read_bytes()
        manifest[relative] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return manifest, record


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
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
