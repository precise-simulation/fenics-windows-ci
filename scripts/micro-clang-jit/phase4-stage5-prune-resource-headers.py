#!/usr/bin/env python3
"""Phase-4 Stage-5: remove non-x86 Clang resource-header families."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MIB = 1024 * 1024

# Derived from clang/lib/Headers/CMakeLists.txt at the pinned LLVM commit
# ea7d852a70e8bdfaf601d6626a760f9771b2c4b4. Keep core-resource-headers,
# x86-resource-headers, windows-resource-headers, and utility-resource-headers.
# FFCx emits ordinary host x86-64 C; these removed groups serve other targets
# or GPU/offload languages and are not part of that contract.
GROUPS: dict[str, tuple[str, ...]] = {
    "arm_aarch64": (
        "arm_acle.h", "arm_cmse.h", "armintr.h",
        "arm64_neon.h", "arm64intr.h", "arm_neon_sve_bridge.h",
    ),
    "cuda": (
        "__clang_cuda_builtin_vars.h", "__clang_cuda_math.h",
        "__clang_cuda_cmath.h", "__clang_cuda_complex_builtins.h",
        "__clang_cuda_device_functions.h", "__clang_cuda_intrinsics.h",
        "__clang_cuda_texture_intrinsics.h", "__clang_cuda_libdevice_declares.h",
        "__clang_cuda_math_forward_declares.h", "__clang_cuda_runtime_wrapper.h",
        "cuda_wrappers/algorithm", "cuda_wrappers/cmath",
        "cuda_wrappers/complex", "cuda_wrappers/new",
        "cuda_wrappers/bits/c++config.h", "cuda_wrappers/bits/shared_ptr_base.h",
        "cuda_wrappers/bits/basic_string.h", "cuda_wrappers/bits/basic_string.tcc",
        "cuda_wrappers/__utility/declval.h",
    ),
    "hexagon": (
        "hexagon_circ_brev_intrinsics.h", "hexagon_protos.h",
        "hexagon_types.h", "hvx_hexagon_protos.h",
    ),
    "hip": (
        "__clang_hip_libdevice_declares.h", "__clang_hip_cmath.h",
        "__clang_hip_math.h", "__clang_hip_stdlib.h",
        "__clang_hip_runtime_wrapper.h",
    ),
    "hlsl": (
        "hlsl_alias_intrinsics_gen.inc", "hlsl_inline_intrinsics_gen.inc",
    ),
    "loongarch": ("larchintrin.h", "lasxintrin.h", "lsxintrin.h"),
    "mips": ("msa.h",),
    "opencl": ("opencl-c.h", "opencl-c-base.h"),
    "powerpc": (
        "altivec.h", "amo.h", "htmintrin.h", "htmxlintrin.h",
        "ppc_wrappers/mmintrin.h", "ppc_wrappers/xmmintrin.h",
        "ppc_wrappers/mm_malloc.h", "ppc_wrappers/emmintrin.h",
        "ppc_wrappers/pmmintrin.h", "ppc_wrappers/tmmintrin.h",
        "ppc_wrappers/smmintrin.h", "ppc_wrappers/nmmintrin.h",
        "ppc_wrappers/bmiintrin.h", "ppc_wrappers/bmi2intrin.h",
        "ppc_wrappers/immintrin.h", "ppc_wrappers/x86intrin.h",
        "ppc_wrappers/x86gprintrin.h",
    ),
    "riscv": (
        "riscv_bitmanip.h", "riscv_crypto.h", "riscv_ntlh.h",
        "andes_vector.h", "riscv_corev_alu.h", "riscv_mips.h",
        "riscv_nds.h", "riscv_packed_simd.h", "sifive_vector.h",
    ),
    "spirv": (
        "__clang_spirv_builtins.h", "__clang_spirv_libdevice_declares.h",
        "__clang_spirv_math.h",
    ),
    "systemz_zos": (
        "s390intrin.h", "vecintrin.h",
        "zos_wrappers/builtins.h", "zos_wrappers/grp.h",
        "zos_wrappers/locale.h", "zos_wrappers/math.h",
        "zos_wrappers/poll.h", "zos_wrappers/stdlib.h",
        "zos_wrappers/string.h", "zos_wrappers/time.h",
        "zos_wrappers/variant.h",
    ),
    "ve": ("velintrin.h", "velintrin_gen.h", "velintrin_approx.h"),
    "webassembly": ("wasm_simd128.h",),
    "gpu": (
        "amdhsa_abi.h", "gpuintrin.h", "nvptxintrin.h", "amdgpuintrin.h",
        "spirvintrin.h", "__clang_gpu_builtin_vars.h",
        "__clang_gpu_device_functions.h", "__clang_gpu_intrinsics.h",
    ),
    "openmp_device": (
        "openmp_wrappers/math.h", "openmp_wrappers/cmath",
        "openmp_wrappers/complex", "openmp_wrappers/complex.h",
        "openmp_wrappers/__clang_openmp_device_functions.h",
        "openmp_wrappers/complex_cmath.h", "openmp_wrappers/new",
    ),
    "llvm_offload": (
        "llvm_offload_wrappers/__llvm_offload.h",
        "llvm_offload_wrappers/__llvm_offload_host.h",
        "llvm_offload_wrappers/__llvm_offload_device.h",
    ),
    "llvm_libc_wrappers": (
        "llvm_libc_wrappers/assert.h", "llvm_libc_wrappers/stdio.h",
        "llvm_libc_wrappers/stdlib.h", "llvm_libc_wrappers/string.h",
        "llvm_libc_wrappers/ctype.h", "llvm_libc_wrappers/inttypes.h",
        "llvm_libc_wrappers/time.h",
    ),
}

REQUIRED_RETAINED = (
    "stdint.h", "stddef.h", "stdarg.h", "float.h", "limits.h",
    "intrin.h", "intrin0.h", "vadefs.h", "yvals_core.h",
    "x86intrin.h", "immintrin.h", "xmmintrin.h", "emmintrin.h",
    "avxintrin.h", "avx2intrin.h", "cpuid.h", "mm_malloc.h",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", required=True)
    parser.add_argument("--evidence-dir", required=True)
    args = parser.parse_args()

    backend = Path(args.backend_root).resolve()
    resource = backend / "lib" / "clang" / "23" / "include"
    evidence = Path(args.evidence_dir).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    if not resource.is_dir():
        raise RuntimeError(f"Clang resource directory missing: {resource}")

    removed: list[dict[str, object]] = []
    group_summary: list[dict[str, object]] = []
    for group, paths in GROUPS.items():
        group_rows = []
        for relative in paths:
            path = resource / relative
            if not path.is_file():
                raise RuntimeError(
                    f"pinned LLVM resource header unexpectedly missing: {relative}"
                )
            size = path.stat().st_size
            row = {"path": relative, "bytes": size, "group": group}
            group_rows.append(row)
            removed.append(row)

        group_bytes = sum(int(row["bytes"]) for row in group_rows)
        group_summary.append({
            "group": group,
            "file_count": len(group_rows),
            "bytes": group_bytes,
            "mib": round(group_bytes / MIB, 4),
        })

    before = sum(p.stat().st_size for p in backend.rglob("*") if p.is_file())
    for row in removed:
        (resource / str(row["path"])).unlink()

    # Clean only directories made empty by the explicit pinned lists.
    for path in sorted(
        (p for p in resource.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            path.rmdir()
        except OSError:
            pass

    for relative in REQUIRED_RETAINED:
        if not (resource / relative).is_file():
            raise RuntimeError(f"required x86/core resource header removed: {relative}")

    after = sum(p.stat().st_size for p in backend.rglob("*") if p.is_file())
    removed_bytes = before - after
    expected_bytes = sum(int(row["bytes"]) for row in removed)
    if removed_bytes != expected_bytes:
        raise RuntimeError(
            f"Stage-5 resource accounting mismatch: expected {expected_bytes}, got {removed_bytes}"
        )

    report = {
        "schema": "fenics-jit-micro-clang-phase4-stage5-resource-pruning-v1",
        "llvm_commit": "ea7d852a70e8bdfaf601d6626a760f9771b2c4b4",
        "source_definition": "clang/lib/Headers/CMakeLists.txt",
        "policy": (
            "remove pinned non-x86 and GPU/offload language resource-header "
            "families; retain core, x86, Windows and utility resource headers"
        ),
        "before_bytes": before,
        "after_bytes": after,
        "removed_bytes": removed_bytes,
        "removed_mib": round(removed_bytes / MIB, 4),
        "removed_file_count": len(removed),
        "groups": group_summary,
        "removed_files": removed,
        "production_selector_integrated": False,
    }
    (evidence / "phase4-stage5-resource-pruning.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "removed_file_count": report["removed_file_count"],
        "removed_mib": report["removed_mib"],
        "remaining_mib_before_package_refresh": round(after / MIB, 4),
        "groups": group_summary,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
