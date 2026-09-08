#!/usr/bin/env python3
"""Aggregate LLVM-MinGW retained-size and Phase 5 closure measurements."""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import re
from collections import Counter
from pathlib import Path, PurePosixPath


MIB = 1024 * 1024
TOOLCHAIN_MARKER = "/library/fenics-jit/"

HEADER_SAFETY_SET = (
    "include/assert.h",
    "include/complex.h",
    "include/ctype.h",
    "include/errno.h",
    "include/float.h",
    "include/inttypes.h",
    "include/io.h",
    "include/limits.h",
    "include/locale.h",
    "include/malloc.h",
    "include/math.h",
    "include/memory.h",
    "include/process.h",
    "include/setjmp.h",
    "include/signal.h",
    "include/stdarg.h",
    "include/stdbool.h",
    "include/stddef.h",
    "include/stdint.h",
    "include/stdio.h",
    "include/stdlib.h",
    "include/string.h",
    "include/time.h",
    "include/wchar.h",
    "include/wctype.h",
    "include/windows.h",
    "include/basetsd.h",
    "include/minwindef.h",
    "include/windef.h",
    "include/winnt.h",
    "include/winbase.h",
)

HEADER_CANDIDATE_FAMILIES = {
    "html_mshtml": ("include/mshtml*",),
    "direct3d_dxgi": ("include/d3d*", "include/dxgi*", "include/dxcore*"),
    "direct2d_directwrite": ("include/d2d*", "include/dwrite*"),
    "ui_automation": ("include/uiautomation*",),
    "windows_runtime_metadata": (
        "include/windows.applicationmodel*",
        "include/windows.data*",
        "include/windows.devices*",
        "include/windows.foundation*",
        "include/windows.gaming*",
        "include/windows.globalization*",
        "include/windows.graphics*",
        "include/windows.management*",
        "include/windows.media*",
        "include/windows.networking*",
        "include/windows.security*",
        "include/windows.services*",
        "include/windows.storage*",
        "include/windows.system*",
        "include/windows.ui*",
        "include/windows.web*",
    ),
}

LIBRARY_SAFETY_SET = {
    "libadvapi32.a",
    "libkernel32.a",
    "libmingw32.a",
    "libmingwex.a",
    "libmsvcrt.a",
    "libpthread.a",
    "libshell32.a",
    "libucrt.a",
    "libucrtbase.a",
    "libunwind.a",
    "libuser32.a",
    "libwinpthread.a",
}

ONECORE_RE = re.compile(
    r"(?i)(onecore|onecoreuap|nanosrv|windowscoreheadless|api-ms-win-.*-l1-[2-9]|uwp)"
)
OLD_MSVC_RE = re.compile(
    r"(?i)^lib(?:msvcr(?:80|90|100|110|120)|msvcp(?:80|90|100|110|120)|vcruntime(?:140)?|ucrtapp).*\.a$"
)
OPTIONAL_WINDOWS_API_RE = re.compile(
    r"(?i)^lib(?:d3d|dxgi|dxcore|d2d|dwrite|uiautomation|mfplat|mfreadwrite|mfuuid).*\.a$"
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _category(relative: str) -> str:
    rel = relative.lower()
    name = PurePosixPath(rel).name
    if rel.startswith("bin/"):
        if name.endswith(".exe"):
            return "compiler_executables"
        if name.endswith(".dll"):
            return "shared_compiler_runtime_dlls"
        return "compiler_bin_other"
    if rel.startswith("include/"):
        return "root_headers"
    if rel.startswith("lib/clang/") and "/include/" in rel:
        return "clang_resource_headers"
    if rel.startswith("lib/clang/") and "/lib/" in rel:
        return "clang_resource_runtime"
    if rel.startswith("x86_64-w64-mingw32/include/"):
        return "target_headers"
    if rel.startswith("x86_64-w64-mingw32/lib/"):
        return "target_static_import_libraries"
    if rel.startswith("x86_64-w64-mingw32/bin/"):
        return "target_runtime_files"
    if rel.startswith("lib/python/"):
        return "python_import_libraries"
    if rel.startswith("runtime/") or name in {
        "manifest.csv",
        "metadata.json",
        "size.txt",
    } or name.startswith("minimization-"):
        return "metadata_scripts"
    return "other"


def _toolchain_relative(raw: str) -> str | None:
    text = raw.strip().strip('"').replace("\\", "/")
    lower = text.lower()
    index = lower.find(TOOLCHAIN_MARKER)
    if index >= 0:
        return text[index + len(TOOLCHAIN_MARKER):].lstrip("/")
    if lower.startswith("library/fenics-jit/"):
        return text[len("Library/fenics-jit/"):]
    return None


def build_size_report(toolchain_root: Path, output_dir: Path) -> None:
    root = toolchain_root.resolve()
    if not root.is_dir():
        raise RuntimeError(f"toolchain root not found: {root}")

    files: list[dict[str, object]] = []
    category_bytes: Counter[str] = Counter()
    category_files: Counter[str] = Counter()
    directory_bytes: Counter[str] = Counter()

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        category = _category(relative)
        record = {"path": relative, "bytes": size, "category": category}
        files.append(record)
        category_bytes[category] += size
        category_files[category] += 1

        parts = PurePosixPath(relative).parts[:-1]
        for depth in range(1, min(3, len(parts)) + 1):
            directory_bytes["/".join(parts[:depth]) + "/"] += size

    total_bytes = sum(int(item["bytes"]) for item in files)
    categories = [
        {
            "category": category,
            "file_count": category_files[category],
            "bytes": category_bytes[category],
            "mib": round(category_bytes[category] / MIB, 3),
        }
        for category in sorted(category_bytes)
    ]
    top_files = sorted(files, key=lambda item: int(item["bytes"]), reverse=True)[:50]
    top_directories = [
        {"path": path, "bytes": size, "mib": round(size / MIB, 3)}
        for path, size in directory_bytes.most_common(50)
    ]

    payload = {
        "toolchain_root": str(root),
        "total_file_count": len(files),
        "total_bytes": total_bytes,
        "total_mib": round(total_bytes / MIB, 3),
        "categories": categories,
        "top_files": top_files,
        "top_directories": top_directories,
        "files": files,
    }
    _write_json(output_dir / "retained-size-report.json", payload)
    _write_csv(
        output_dir / "retained-files.csv",
        ["path", "bytes", "category"],
        files,
    )
    print(f"Retained LLVM-MinGW payload: {total_bytes / MIB:.2f} MiB across {len(files)} files")
    for row in sorted(categories, key=lambda item: int(item["bytes"]), reverse=True):
        print(f"  {row['category']}: {row['mib']:.2f} MiB")


def _load_size_report(output_dir: Path) -> dict[str, object]:
    path = output_dir / "retained-size-report.json"
    if not path.is_file():
        raise RuntimeError(f"retained size report missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _match_family(relative: str, patterns: tuple[str, ...]) -> bool:
    lowered = relative.lower()
    return any(fnmatch.fnmatch(lowered, pattern.lower()) for pattern in patterns)


def _header_report(phase5_root: Path, output_dir: Path, size: dict[str, object]) -> dict[str, object]:
    retained = {
        str(item["path"]).lower(): item
        for item in size["files"]
        if str(item["category"]) in {"root_headers", "clang_resource_headers", "target_headers"}
    }
    root_headers = {
        path: item for path, item in retained.items() if str(item["category"]) == "root_headers"
    }

    direct: set[str] = set()
    transitive: set[str] = set()
    trace_files = sorted(phase5_root.rglob("*-header-trace.txt"))
    for trace in trace_files:
        for line in trace.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^\s*(\.+)\s+(.+?)\s*$", line)
            if not match:
                continue
            relative = _toolchain_relative(match.group(2))
            if relative is None:
                continue
            key = relative.lower()
            if key not in retained:
                continue
            if len(match.group(1)) == 1:
                direct.add(key)
            else:
                transitive.add(key)

    transitive.difference_update(direct)
    observed = direct | transitive

    safety = []
    safety_keys = {path.lower() for path in HEADER_SAFETY_SET}
    for path in HEADER_SAFETY_SET:
        key = path.lower()
        item = root_headers.get(key)
        safety.append(
            {
                "path": path,
                "present": item is not None,
                "observed": key in observed,
                "bytes": int(item["bytes"]) if item else 0,
            }
        )

    unobserved_root = [
        item for key, item in root_headers.items() if key not in observed
    ]
    pruning_candidates = [
        item for item in unobserved_root if str(item["path"]).lower() not in safety_keys
    ]

    families: list[dict[str, object]] = []
    for name, patterns in HEADER_CANDIDATE_FAMILIES.items():
        matches = [
            item for item in pruning_candidates if _match_family(str(item["path"]), patterns)
        ]
        family_bytes = sum(int(item["bytes"]) for item in matches)
        families.append(
            {
                "family": name,
                "patterns": list(patterns),
                "file_count": len(matches),
                "bytes": family_bytes,
                "mib": round(family_bytes / MIB, 3),
                "top_files": sorted(matches, key=lambda item: int(item["bytes"]), reverse=True)[:25],
            }
        )

    direct_rows = sorted((retained[key] for key in direct), key=lambda item: str(item["path"]))
    transitive_rows = sorted(
        (retained[key] for key in transitive), key=lambda item: str(item["path"])
    )
    observed_rows = direct_rows + transitive_rows

    report = {
        "compile_trace_count": len(trace_files),
        "observed_header_count": len(observed),
        "observed_header_bytes": sum(int(item["bytes"]) for item in observed_rows),
        "direct_observed_count": len(direct_rows),
        "direct_observed": direct_rows,
        "transitive_observed_count": len(transitive_rows),
        "transitive_observed": transitive_rows,
        "explicit_safety_set": safety,
        "root_header_total_count": len(root_headers),
        "root_header_total_bytes": sum(int(item["bytes"]) for item in root_headers.values()),
        "unobserved_root_header_count": len(unobserved_root),
        "unobserved_root_header_bytes": sum(int(item["bytes"]) for item in unobserved_root),
        "candidate_unrelated_families": families,
    }
    _write_json(output_dir / "header-closure.json", report)
    _write_csv(
        output_dir / "header-pruning-candidates.csv",
        ["path", "bytes", "category"],
        sorted(pruning_candidates, key=lambda item: int(item["bytes"]), reverse=True),
    )
    return report


def _library_family(name: str) -> str:
    lowered = name.lower()
    if lowered in LIBRARY_SAFETY_SET:
        return "mingw_ucrt_startup_runtime_safety"
    if ONECORE_RE.search(lowered):
        return "onecore_uwp_server_candidate"
    if OLD_MSVC_RE.match(lowered):
        return "old_msvc_compatibility_candidate"
    if OPTIONAL_WINDOWS_API_RE.match(lowered):
        return "optional_windows_api_candidate"
    return "other"


def _library_report(phase5_root: Path, output_dir: Path, size: dict[str, object]) -> dict[str, object]:
    archives = [
        item
        for item in size["files"]
        if str(item["category"]) == "target_static_import_libraries"
        and str(item["path"]).lower().endswith(".a")
    ]
    traces = sorted(phase5_root.rglob("*-linker-trace.txt"))
    usage: Counter[str] = Counter()

    for trace in traces:
        text = trace.read_text(encoding="utf-8", errors="replace").replace("\\", "/").lower()
        selected: set[str] = set()
        for item in archives:
            relative = str(item["path"]).lower()
            basename = PurePosixPath(relative).name
            if relative in text or re.search(
                rf"(?<![a-z0-9_.-]){re.escape(basename)}(?![a-z0-9_.-])", text
            ):
                selected.add(relative)
        for relative in selected:
            usage[relative] += 1

    rows: list[dict[str, object]] = []
    for item in archives:
        relative = str(item["path"])
        key = relative.lower()
        count = usage[key]
        if traces and count == len(traces):
            usage_class = "always_required"
        elif count:
            usage_class = "conditionally_required"
        else:
            usage_class = "unobserved"
        name = PurePosixPath(relative).name
        rows.append(
            {
                "path": relative,
                "bytes": int(item["bytes"]),
                "trace_count": count,
                "usage": usage_class,
                "family": _library_family(name),
                "explicit_safety_set": name.lower() in LIBRARY_SAFETY_SET,
            }
        )

    family_bytes: Counter[str] = Counter()
    family_files: Counter[str] = Counter()
    usage_bytes: Counter[str] = Counter()
    usage_files: Counter[str] = Counter()
    for row in rows:
        family = str(row["family"])
        use = str(row["usage"])
        family_bytes[family] += int(row["bytes"])
        family_files[family] += 1
        usage_bytes[use] += int(row["bytes"])
        usage_files[use] += 1

    report = {
        "link_trace_count": len(traces),
        "target_archive_count": len(rows),
        "usage_summary": [
            {
                "usage": key,
                "file_count": usage_files[key],
                "bytes": usage_bytes[key],
                "mib": round(usage_bytes[key] / MIB, 3),
            }
            for key in sorted(usage_bytes)
        ],
        "family_summary": [
            {
                "family": key,
                "file_count": family_files[key],
                "bytes": family_bytes[key],
                "mib": round(family_bytes[key] / MIB, 3),
            }
            for key in sorted(family_bytes)
        ],
        "libraries": sorted(
            rows,
            key=lambda row: (
                {"always_required": 0, "conditionally_required": 1, "unobserved": 2}[str(row["usage"])],
                -int(row["bytes"]),
                str(row["path"]),
            ),
        ),
    }
    _write_json(output_dir / "library-usage.json", report)
    _write_csv(
        output_dir / "library-pruning-candidates.csv",
        ["path", "bytes", "trace_count", "usage", "family", "explicit_safety_set"],
        sorted(
            (row for row in rows if row["usage"] == "unobserved" and not row["explicit_safety_set"]),
            key=lambda row: int(row["bytes"]),
            reverse=True,
        ),
    )
    return report


def build_closure_report(phase5_root: Path, output_dir: Path) -> None:
    if not phase5_root.is_dir():
        raise RuntimeError(f"Phase 5 diagnostics root not found: {phase5_root}")
    size = _load_size_report(output_dir)
    headers = _header_report(phase5_root, output_dir, size)
    libraries = _library_report(phase5_root, output_dir, size)

    summary = {
        "measurement_only": True,
        "phase5_root": str(phase5_root.resolve()),
        "retained_payload_mib": size["total_mib"],
        "headers": {
            "compile_trace_count": headers["compile_trace_count"],
            "observed_count": headers["observed_header_count"],
            "observed_mib": round(int(headers["observed_header_bytes"]) / MIB, 3),
            "root_total_count": headers["root_header_total_count"],
            "root_total_mib": round(int(headers["root_header_total_bytes"]) / MIB, 3),
            "unobserved_root_count": headers["unobserved_root_header_count"],
            "unobserved_root_mib": round(int(headers["unobserved_root_header_bytes"]) / MIB, 3),
        },
        "libraries": {
            "link_trace_count": libraries["link_trace_count"],
            "target_archive_count": libraries["target_archive_count"],
            "usage_summary": libraries["usage_summary"],
            "family_summary": libraries["family_summary"],
        },
    }
    _write_json(output_dir / "closure-summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--toolchain-root")
    parser.add_argument("--phase5-root")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.toolchain_root and not args.phase5_root:
        parser.error("at least one of --toolchain-root or --phase5-root is required")

    if args.toolchain_root:
        build_size_report(Path(args.toolchain_root), output_dir)
    if args.phase5_root:
        build_closure_report(Path(args.phase5_root), output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
