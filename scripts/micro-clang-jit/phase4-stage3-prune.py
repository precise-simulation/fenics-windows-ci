#!/usr/bin/env python3
"""Build a reversible Phase-4 Stage-3 sysroot candidate from qualified closure traces."""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import re
from pathlib import Path, PurePosixPath

MIB = 1024 * 1024
TOOLCHAIN_MARKER = "/library/fenics-jit/backends/micro-clang/"
SYNTHETIC_MEMBER_RE = re.compile(
    r"(?<![a-z0-9_])(lib64_[a-z0-9_]+_a)-[^\s:]+", re.IGNORECASE
)

# Keep the C/UCRT/POSIX surface intentionally broader than the observed corpus.
# Stage 3 is allowed to remove optional Windows SDK surface, not core C runtime
# coverage merely to hit the numerical size gate.
HEADER_SAFETY_NAMES = {
    "include/assert.h",
    "include/complex.h",
    "include/ctype.h",
    "include/dirent.h",
    "include/direct.h",
    "include/dlfcn.h",
    "include/errno.h",
    "include/fcntl.h",
    "include/float.h",
    "include/getopt.h",
    "include/glob.h",
    "include/grp.h",
    "include/iconv.h",
    "include/inttypes.h",
    "include/io.h",
    "include/langinfo.h",
    "include/libgen.h",
    "include/limits.h",
    "include/locale.h",
    "include/malloc.h",
    "include/math.h",
    "include/memory.h",
    "include/poll.h",
    "include/process.h",
    "include/pthread.h",
    "include/pwd.h",
    "include/regex.h",
    "include/sched.h",
    "include/semaphore.h",
    "include/setjmp.h",
    "include/signal.h",
    "include/stdalign.h",
    "include/stdarg.h",
    "include/stdatomic.h",
    "include/stdbool.h",
    "include/stddef.h",
    "include/stdint.h",
    "include/stdio.h",
    "include/stdlib.h",
    "include/stdnoreturn.h",
    "include/string.h",
    "include/strings.h",
    "include/tar.h",
    "include/termios.h",
    "include/tgmath.h",
    "include/threads.h",
    "include/time.h",
    "include/uchar.h",
    "include/unistd.h",
    "include/utime.h",
    "include/wchar.h",
    "include/wctype.h",
    "include/wordexp.h",
    "include/windows.h",
    "include/basetsd.h",
    "include/guiddef.h",
    "include/minwindef.h",
    "include/windef.h",
    "include/winnt.h",
    "include/winbase.h",
    "include/winerror.h",
    "include/winapifamily.h",
}
HEADER_SAFETY_PREFIXES = (
    "include/_mingw",
    "include/crt",
    "include/corecrt",
    "include/sec_api/",
    "include/sys/",
    "include/bits/",
    "include/ssp/",
    "include/arpa/",
    "include/net/",
    "include/netinet/",
    "include/protocols/",
    "include/rpc/",
)
HEADER_SUFFIXES = {".h", ".hh", ".hpp", ".hxx", ".inc", ".inl"}

# Preserve startup/runtime/default desktop Windows libraries independently of
# whether this finite corpus happens to select them. Optional SDK import
# libraries are candidates only when no link trace selects them.
LIBRARY_SAFETY_NAMES = {
    "libadvapi32.a",
    "libbcrypt.a",
    "libcomctl32.a",
    "libcomdlg32.a",
    "libcrypt32.a",
    "libdbghelp.a",
    "libdelayimp.a",
    "libgdi32.a",
    "libimagehlp.a",
    "libiphlpapi.a",
    "libkernel32.a",
    "libmingw32.a",
    "libmingwex.a",
    "libmingwthrd.a",
    "libmoldname.a",
    "libmsvcrt.a",
    "libmsvcrt-os.a",
    "libntdll.a",
    "libole32.a",
    "liboleaut32.a",
    "libpsapi.a",
    "libpthread.a",
    "librpcrt4.a",
    "libsecur32.a",
    "libsetupapi.a",
    "libshell32.a",
    "libshlwapi.a",
    "libucrt.a",
    "libucrtbase.a",
    "libunwind.a",
    "libuser32.a",
    "libuuid.a",
    "libversion.a",
    "libwinmm.a",
    "libwinpthread.a",
    "libws2_32.a",
}
LIBRARY_SAFETY_PATTERNS = (
    "libapi-ms-win-crt-*.a",
    "libmingw*.a",
    "libucrt*.a",
    "libmsvcrt*.a",
    "libpthread*.a",
    "libwinpthread*.a",
    "libunwind*.a",
)


def _depfile_dependencies(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = text.replace("\\\r\n", " ").replace("\\\n", " ")
    separator = text.find(": ")
    if separator < 0:
        return []
    body = text[separator + 2 :]
    sentinel = "\0"
    body = body.replace("\\ ", sentinel)
    return [
        token.replace(sentinel, " ").replace("\\#", "#")
        for token in body.split()
        if token
    ]


def _toolchain_relative(raw: str) -> str | None:
    text = raw.strip().strip('"').replace("\\", "/")
    lower = text.lower()
    index = lower.find(TOOLCHAIN_MARKER)
    if index < 0:
        return None
    return text[index + len(TOOLCHAIN_MARKER) :].lstrip("/")


def _synthetic_marker(name: str) -> str:
    sanitized = re.sub(r"[^a-z0-9]", "_", name.lower())
    return f"lib64_{sanitized}"


def _header_is_safety(relative: str) -> bool:
    key = relative.lower()
    if key in HEADER_SAFETY_NAMES:
        return True
    return any(key.startswith(prefix) for prefix in HEADER_SAFETY_PREFIXES)


def _library_is_safety(name: str) -> bool:
    key = name.lower()
    if key in LIBRARY_SAFETY_NAMES:
        return True
    return any(fnmatch.fnmatch(key, pattern) for pattern in LIBRARY_SAFETY_PATTERNS)


def _stats(root: Path) -> tuple[int, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def _record(root: Path, path: Path, reason: str) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "reason": reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", required=True)
    parser.add_argument("--trace-root", required=True)
    parser.add_argument("--evidence-dir", required=True)
    args = parser.parse_args()

    root = Path(args.backend_root).resolve()
    traces = Path(args.trace_root).resolve()
    evidence = Path(args.evidence_dir).resolve()
    evidence.mkdir(parents=True, exist_ok=True)

    include = root / "include"
    target_lib = root / "x86_64-w64-mingw32" / "lib"
    if not include.is_dir() or not target_lib.is_dir():
        raise RuntimeError(f"target sysroot missing below {root}")

    depfiles = sorted(traces.rglob("*.d"))
    mapfiles = sorted(traces.rglob("*.map"))
    if len(depfiles) < 12:
        raise RuntimeError(f"too few broad compile dependency traces: {len(depfiles)}")
    if len(mapfiles) < 12:
        raise RuntimeError(f"too few broad LLD map traces: {len(mapfiles)}")

    observed_headers: set[str] = set()
    for depfile in depfiles:
        for raw in _depfile_dependencies(depfile):
            relative = _toolchain_relative(raw)
            if relative is not None and relative.lower().startswith("include/"):
                observed_headers.add(relative.lower())

    archives = sorted(target_lib.glob("*.a"))
    by_relative = {
        path.relative_to(root).as_posix().lower(): path for path in archives
    }
    by_marker: dict[str, list[str]] = {}
    for relative, path in by_relative.items():
        by_marker.setdefault(_synthetic_marker(path.name), []).append(relative)
    ambiguous = {key: value for key, value in by_marker.items() if len(value) != 1}
    if ambiguous:
        raise RuntimeError(f"ambiguous synthetic archive markers: {ambiguous!r}")

    observed_archives: set[str] = set()
    for mapfile in mapfiles:
        text = mapfile.read_text(encoding="utf-8", errors="replace").replace("\\", "/").lower()
        for match in SYNTHETIC_MEMBER_RE.finditer(text):
            paths = by_marker.get(match.group(1).lower())
            if paths:
                observed_archives.add(paths[0])
        for relative, path in by_relative.items():
            name = path.name.lower()
            if relative in text or re.search(
                rf"(?<![a-z0-9_.-]){re.escape(name)}(?![a-z0-9_.-])", text
            ):
                observed_archives.add(relative)

    observed_names = {PurePosixPath(path).name.lower() for path in observed_archives}
    required_observed = {"libmingw32.a", "libmingwex.a"}
    missing_observed = sorted(required_observed - observed_names)
    if missing_observed:
        raise RuntimeError(
            "LLD trace parsing missed required runtime archives: "
            + ", ".join(missing_observed)
        )

    header_candidates: list[Path] = []
    header_safety_unobserved: list[dict[str, object]] = []
    for path in sorted(include.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in HEADER_SUFFIXES:
            continue
        relative = path.relative_to(root).as_posix()
        key = relative.lower()
        if key in observed_headers:
            continue
        if _header_is_safety(relative):
            header_safety_unobserved.append(_record(root, path, "explicit-c-ucrt-posix-safety"))
            continue
        header_candidates.append(path)

    library_candidates: list[Path] = []
    library_safety_unobserved: list[dict[str, object]] = []
    for relative, path in sorted(by_relative.items()):
        if relative in observed_archives:
            continue
        if _library_is_safety(path.name):
            library_safety_unobserved.append(
                _record(root, path, "explicit-runtime-default-windows-safety")
            )
            continue
        library_candidates.append(path)

    if not header_candidates and not library_candidates:
        raise RuntimeError("closure-driven Stage-3 candidate removes no files")

    before_files, before_bytes = _stats(root)
    removed_headers = [
        _record(root, path, "unobserved-noncore-header") for path in header_candidates
    ]
    removed_libraries = [
        _record(root, path, "unobserved-optional-import-library")
        for path in library_candidates
    ]

    for path in header_candidates + library_candidates:
        path.unlink()

    required_headers = (
        "_mingw.h",
        "stdint.h",
        "stdio.h",
        "stdlib.h",
        "string.h",
        "math.h",
        "windows.h",
        "winnt.h",
    )
    for name in required_headers:
        if not (include / name).is_file():
            raise RuntimeError(f"required core header removed: {name}")

    required_libraries = (
        "libmingw32.a",
        "libmingwex.a",
        "libucrt.a",
        "libkernel32.a",
        "libunwind.a",
    )
    for name in required_libraries:
        if not (target_lib / name).is_file():
            raise RuntimeError(f"required runtime library removed: {name}")

    after_files, after_bytes = _stats(root)
    removed_bytes = before_bytes - after_bytes

    with (evidence / "phase4-stage3-header-candidates.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "bytes", "reason"])
        writer.writeheader()
        writer.writerows(removed_headers)

    with (evidence / "phase4-stage3-library-candidates.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "bytes", "reason"])
        writer.writeheader()
        writer.writerows(removed_libraries)

    report = {
        "schema": "fenics-jit-micro-clang-phase4-stage3-pruning-v1",
        "measurement_basis": "qualified Phase-4 Stage-2 Python 3.12-3.14 dependency and LLD-map traces",
        "compile_trace_count": len(depfiles),
        "link_trace_count": len(mapfiles),
        "observed_toolchain_header_count": len(observed_headers),
        "observed_target_archive_count": len(observed_archives),
        "before_file_count": before_files,
        "before_bytes": before_bytes,
        "before_mib": round(before_bytes / MIB, 4),
        "after_file_count": after_files,
        "after_bytes": after_bytes,
        "after_mib": round(after_bytes / MIB, 4),
        "removed_bytes": removed_bytes,
        "removed_mib": round(removed_bytes / MIB, 4),
        "removed_header_count": len(removed_headers),
        "removed_header_bytes": sum(int(item["bytes"]) for item in removed_headers),
        "removed_library_count": len(removed_libraries),
        "removed_library_bytes": sum(int(item["bytes"]) for item in removed_libraries),
        "retained_unobserved_header_safety_count": len(header_safety_unobserved),
        "retained_unobserved_library_safety_count": len(library_safety_unobserved),
        "required_observed_runtime_archives": sorted(required_observed),
        "production_selector_integrated": False,
        "removed_headers": removed_headers,
        "removed_libraries": removed_libraries,
        "retained_unobserved_header_safety": header_safety_unobserved,
        "retained_unobserved_library_safety": library_safety_unobserved,
    }
    (evidence / "phase4-stage3-pruning.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "compile_trace_count": len(depfiles),
        "link_trace_count": len(mapfiles),
        "removed_header_count": len(removed_headers),
        "removed_library_count": len(removed_libraries),
        "removed_mib": report["removed_mib"],
        "remaining_mib_before_package_refresh": report["after_mib"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
