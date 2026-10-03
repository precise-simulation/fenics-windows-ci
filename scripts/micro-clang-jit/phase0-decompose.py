"""Decompose the immutable Stage-AW LLVM-MinGW payload for micro-Clang Phase 0."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path

import zstandard


def category(path: str) -> str:
    p = path.replace("\\", "/")
    lower = p.lower()
    name = Path(p).name.lower()

    if lower.startswith("bin/") and lower.endswith(".exe"):
        return "host-executables"
    if lower.startswith("bin/") and lower.endswith(".dll"):
        return "host-dll-closure"
    if lower.startswith("lib/clang/") and "/include/" in lower:
        return "clang-resource-headers"
    if lower.startswith("lib/clang/") and "/lib/windows/" in lower:
        return "clang-resource-runtime"
    if lower.startswith("include/"):
        return "mingw-ucrt-headers"
    if lower.startswith("lib/python/"):
        return "python-stable-abi-imports"
    if lower.startswith("x86_64-w64-mingw32/bin/"):
        return "target-runtime-dlls"
    if lower.startswith("x86_64-w64-mingw32/lib/"):
        if lower.endswith(".o") or name.startswith(("crt", "dllcrt")):
            return "target-startup-objects"
        if name in {
            "libmingw32.a",
            "libmingwex.a",
            "libmingwthrd.a",
            "libmoldname.a",
            "libunwind.a",
        }:
            return "target-runtime-archives"
        if lower.endswith(".a"):
            return "target-import-libraries"
        return "target-libraries-other"
    if (
        name.startswith(("license", "copying", "versions"))
        or name.endswith((".json", ".csv"))
        or name == "size.txt"
        or "/share/" in lower
        or lower.startswith("share/")
    ):
        return "metadata-licenses"
    return "other"


def compressed_bytes(root: Path, paths: list[Path]) -> int:
    if not paths:
        return 0
    with tempfile.TemporaryDirectory(prefix="micro-clang-phase0-") as temp:
        temp_path = Path(temp)
        tar_path = temp_path / "category.tar"
        zst_path = temp_path / "category.tar.zst"
        with tarfile.open(tar_path, "w", format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(paths):
                relative = path.relative_to(root).as_posix()
                info = archive.gettarinfo(str(path), arcname=relative)
                # Normalize volatile metadata so this is a reproducible category
                # compression metric rather than a timestamp measurement.
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
        compressor = zstandard.ZstdCompressor(level=19, threads=1)
        with tar_path.open("rb") as source, zst_path.open("wb") as destination:
            compressor.copy_stream(source, destination)
        return zst_path.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--driver-evidence")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    identity_path = Path(args.identity).resolve()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    if not root.is_dir():
        raise RuntimeError(f"reference root not found: {root}")

    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    files = sorted(path for path in root.rglob("*") if path.is_file())
    groups: dict[str, list[Path]] = defaultdict(list)
    manifest: list[dict[str, object]] = []

    for path in files:
        relative = path.relative_to(root).as_posix()
        group = category(relative)
        groups[group].append(path)
        manifest.append(
            {
                "path": relative,
                "category": group,
                "bytes": path.stat().st_size,
            }
        )

    categories: list[dict[str, object]] = []
    for group in sorted(groups):
        paths = groups[group]
        installed = sum(path.stat().st_size for path in paths)
        categories.append(
            {
                "category": group,
                "file_count": len(paths),
                "installed_bytes": installed,
                "installed_mib": round(installed / (1024 * 1024), 4),
                "category_zstd_bytes": compressed_bytes(root, paths),
            }
        )

    total_bytes = sum(item["installed_bytes"] for item in categories)
    total_zstd = sum(item["category_zstd_bytes"] for item in categories)
    result: dict[str, object] = {
        "schema": "fenics-jit-micro-clang-phase0-breakdown-v1",
        "reference_identity": identity,
        "measurement": {
            "root": str(root),
            "file_count": len(files),
            "installed_bytes": total_bytes,
            "installed_mib": round(total_bytes / (1024 * 1024), 4),
            "sum_category_zstd_bytes": total_zstd,
            "sum_category_zstd_mib": round(total_zstd / (1024 * 1024), 4),
            "compressed_metric": (
                "sum of deterministic per-category tar+zstd(level=19) streams; "
                "used to compare category contribution, not as a conda package size"
            ),
        },
        "categories": categories,
    }

    if args.driver_evidence:
        evidence_path = Path(args.driver_evidence).resolve()
        result["driver_evidence"] = json.loads(evidence_path.read_text(encoding="utf-8"))

    (output / "reference-breakdown.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with (output / "reference-breakdown.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "category",
                "file_count",
                "installed_bytes",
                "installed_mib",
                "category_zstd_bytes",
            ],
        )
        writer.writeheader()
        writer.writerows(categories)

    with (output / "reference-manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "category", "bytes"])
        writer.writeheader()
        writer.writerows(manifest)

    print(json.dumps(result["measurement"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
