"""Validate the immutable Stage-AW reference used by micro-Clang Phase 0."""

from __future__ import annotations

import json
from pathlib import Path


REFERENCE = Path(__file__).with_name("reference.json")


def main() -> None:
    data = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert data["schema"] == "fenics-micro-clang-reference-v1"
    sources = data["source_identity"]
    assert sources["llvm_project_commit"] == sources["compiler_rt_commit"]
    assert len(sources["llvm_project_commit"]) == 40
    assert len(sources["mingw_w64_commit"]) == 40
    assert data["target_policy"]["target"] == "x86_64-w64-mingw32"
    assert data["target_policy"]["crt"] == "UCRT"

    categories = data["stage_aw_retained_categories"]
    category_bytes = sum(int(item["bytes"]) for item in categories.values())
    expected = int(data["stage_aw"]["retained_payload_bytes"])
    if category_bytes != expected:
        raise RuntimeError(
            f"Stage-AW category total changed: {category_bytes} != {expected}"
        )

    shared = int(categories["shared_compiler_runtime_dlls"]["bytes"])
    if shared / expected < 0.5:
        raise RuntimeError("Phase-0 conclusion invalid: compiler DLL closure is not dominant")

    largest = data["largest_retained_files"]
    if largest["bin/libLLVM-23.dll"] + largest["bin/libclang-cpp.dll"] <= expected / 2:
        raise RuntimeError("LLVM/Clang shared-library pair no longer explains the majority")

    baseline_mib = float(data["stage_aw"]["installed_package_mib"])
    gates = data["size_gates"]
    expected_gates = {
        "continuation_mib": baseline_mib * 0.5,
        "strong_mib": baseline_mib * 0.375,
        "stretch_mib": baseline_mib * 0.25,
    }
    for key, value in expected_gates.items():
        if abs(float(gates[key]) - value) > 1e-6:
            raise RuntimeError(f"Incorrect {key}: {gates[key]} != {value}")

    print("micro-Clang Phase-0 immutable reference validated")
    print(f"LLVM/Clang/LLD/compiler-rt commit: {sources['llvm_project_commit']}")
    print(f"mingw-w64 commit: {sources['mingw_w64_commit']}")
    print(f"llvm-mingw commit: {sources['llvm_mingw_commit']}")
    print(f"Stage-AW retained payload: {expected / 2**20:.3f} MiB")
    print(f"Stage-AW compiler DLL closure: {shared / 2**20:.3f} MiB")


if __name__ == "__main__":
    main()
