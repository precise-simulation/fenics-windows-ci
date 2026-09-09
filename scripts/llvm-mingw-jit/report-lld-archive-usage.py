#!/usr/bin/env python3
"""Measure target archive use from LLD map files, including MinGW synthetic member labels."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path, PurePosixPath

MIB = 1024 * 1024
SYNTHETIC_MEMBER_RE = re.compile(r"(?<![a-z0-9_])(lib64_[a-z0-9_]+_a)-[^\s:]+", re.IGNORECASE)
REQUIRED_RUNTIME_ARCHIVES = {"libmingw32.a", "libmingwex.a"}


def _synthetic_marker(basename: str) -> str:
    sanitized = re.sub(r"[^a-z0-9]", "_", basename.lower())
    return f"lib64_{sanitized}"


def _literal_archive_seen(text: str, relative: str, basename: str) -> bool:
    if relative in text:
        return True
    return re.search(
        rf"(?<![a-z0-9_.-]){re.escape(basename)}(?![a-z0-9_.-])", text
    ) is not None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase5-root", required=True)
    parser.add_argument("--retained-size-report", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    phase5_root = Path(args.phase5_root).resolve()
    size_path = Path(args.retained_size_report).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    size = json.loads(size_path.read_text(encoding="utf-8"))
    archives = [
        item
        for item in size["files"]
        if str(item["category"]) == "target_static_import_libraries"
        and str(item["path"]).lower().endswith(".a")
    ]
    traces = sorted(phase5_root.rglob("*.map"))
    if not traces:
        raise RuntimeError("Phase 5 archive observation found zero LLD map files")
    if not archives:
        raise RuntimeError("Retained size report contains zero target archives")

    by_marker: dict[str, list[str]] = {}
    by_key: dict[str, dict[str, object]] = {}
    for item in archives:
        relative = str(item["path"]).lower()
        basename = PurePosixPath(relative).name
        marker = _synthetic_marker(basename)
        by_marker.setdefault(marker, []).append(relative)
        by_key[relative] = item

    ambiguous_markers = {
        marker: paths for marker, paths in by_marker.items() if len(paths) != 1
    }
    if ambiguous_markers:
        raise RuntimeError(
            "Synthetic LLD archive markers are ambiguous: "
            + json.dumps(ambiguous_markers, sort_keys=True)
        )

    usage: Counter[str] = Counter()
    marker_hits: Counter[str] = Counter()
    unmatched_markers: Counter[str] = Counter()
    for trace in traces:
        text = trace.read_text(encoding="utf-8", errors="replace").replace("\\", "/").lower()
        selected: set[str] = set()

        for match in SYNTHETIC_MEMBER_RE.finditer(text):
            marker = match.group(1).lower()
            paths = by_marker.get(marker)
            if paths:
                selected.add(paths[0])
                marker_hits[marker] += 1
            else:
                unmatched_markers[marker] += 1

        for relative, item in by_key.items():
            basename = PurePosixPath(relative).name
            if _literal_archive_seen(text, relative, basename):
                selected.add(relative)

        for relative in selected:
            usage[relative] += 1

    rows = []
    for relative, item in by_key.items():
        count = usage[relative]
        if count == len(traces):
            usage_class = "always_required"
        elif count:
            usage_class = "conditionally_required"
        else:
            usage_class = "unobserved"
        rows.append(
            {
                "path": str(item["path"]),
                "bytes": int(item["bytes"]),
                "trace_count": count,
                "usage": usage_class,
                "synthetic_marker": _synthetic_marker(PurePosixPath(relative).name),
            }
        )

    observed = [row for row in rows if row["trace_count"]]
    if not observed:
        raise RuntimeError(
            "LLD maps were present but archive observation found zero used archives; "
            "refusing to classify all target archives as unobserved"
        )

    observed_names = {PurePosixPath(str(row["path"])).name.lower() for row in observed}
    missing_runtime = sorted(REQUIRED_RUNTIME_ARCHIVES - observed_names)
    if missing_runtime:
        raise RuntimeError(
            "LLD archive observation did not recover expected MinGW/UCRT runtime archives: "
            + ", ".join(missing_runtime)
        )

    usage_bytes: Counter[str] = Counter()
    usage_files: Counter[str] = Counter()
    for row in rows:
        usage = str(row["usage"])
        usage_bytes[usage] += int(row["bytes"])
        usage_files[usage] += 1

    report = {
        "measurement_only": True,
        "trace_format": "LLD -Map with literal paths and lib64_<archive>_a-member synthetic labels",
        "link_trace_count": len(traces),
        "target_archive_count": len(rows),
        "observed_archive_count": len(observed),
        "observed_archive_mib": round(sum(int(row["bytes"]) for row in observed) / MIB, 3),
        "required_runtime_archives_observed": sorted(REQUIRED_RUNTIME_ARCHIVES),
        "usage_summary": [
            {
                "usage": key,
                "file_count": usage_files[key],
                "bytes": usage_bytes[key],
                "mib": round(usage_bytes[key] / MIB, 3),
            }
            for key in sorted(usage_bytes)
        ],
        "observed_libraries": sorted(
            observed, key=lambda row: (-int(row["trace_count"]), str(row["path"]))
        ),
        "synthetic_marker_hits": dict(sorted(marker_hits.items())),
        "unmatched_synthetic_markers": dict(sorted(unmatched_markers.items())),
        "libraries": sorted(rows, key=lambda row: (str(row["usage"]), str(row["path"]))),
    }
    (output_dir / "library-usage-v2.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output_dir / "library-pruning-candidates-v2.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["path", "bytes", "trace_count", "usage", "synthetic_marker"]
        )
        writer.writeheader()
        writer.writerows(row for row in rows if row["usage"] == "unobserved")

    print(json.dumps({
        "link_trace_count": report["link_trace_count"],
        "target_archive_count": report["target_archive_count"],
        "observed_archive_count": report["observed_archive_count"],
        "observed_archive_mib": report["observed_archive_mib"],
        "required_runtime_archives_observed": report["required_runtime_archives_observed"],
        "unmatched_synthetic_markers": report["unmatched_synthetic_markers"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
