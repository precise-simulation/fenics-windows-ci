"""Phase-5 paired three-backend size and performance comparison."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import statistics
import sys
import time
from pathlib import Path
from types import ModuleType

import numpy as np
from mpi4py import MPI

_BACKENDS = ("llvm-mingw", "micro-clang", "tinycc")
_STAGE_AW = {
    "qualification_run": 34580520920,
    "installed_mib": 216.43,
    "compressed_mib": 51.34,
}
_STAGE_AW_INSTALLED_BYTES = int(_STAGE_AW["installed_mib"] * 1024 * 1024)
_SIZE_GATES = {
    "early_50_percent_bytes": int(_STAGE_AW_INSTALLED_BYTES * 0.50),
    "strong_37_5_percent_bytes": int(_STAGE_AW_INSTALLED_BYTES * 0.375),
    "stretch_25_percent_bytes": int(_STAGE_AW_INSTALLED_BYTES * 0.25),
}
_ORDER_CYCLE = (
    ("llvm-mingw", "micro-clang", "tinycc"),
    ("tinycc", "micro-clang", "llvm-mingw"),
    ("micro-clang", "llvm-mingw", "tinycc"),
    ("tinycc", "llvm-mingw", "micro-clang"),
    ("micro-clang", "tinycc", "llvm-mingw"),
    ("llvm-mingw", "tinycc", "micro-clang"),
)


def _load_base() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "tinycc-jit" / "phase6-benchmark.py"
    spec = importlib.util.spec_from_file_location("_micro_clang_phase5_benchmark_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load benchmark base: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _order(index: int) -> tuple[str, ...]:
    return _ORDER_CYCLE[index % len(_ORDER_CYCLE)]


def _scalar_summary(samples: list[float]) -> dict[str, object]:
    if not samples:
        raise RuntimeError("cannot summarize empty sample set")
    values = np.asarray(samples, dtype=np.float64)
    return {
        "samples": [float(value) for value in values],
        "count": int(values.size),
        "min": float(np.min(values)),
        "p25": float(np.percentile(values, 25)),
        "median": float(np.median(values)),
        "p75": float(np.percentile(values, 75)),
        "p90": float(np.percentile(values, 90)),
        "p95": float(np.percentile(values, 95)),
        "max": float(np.max(values)),
    }


def _identity(record: dict[str, object]) -> dict[str, object]:
    return {
        "name": record.get("name"),
        "version": record.get("version"),
        "build": record.get("build"),
        "build_number": record.get("build_number"),
        "channel": record.get("channel"),
        "subdir": record.get("subdir"),
        "url": record.get("url"),
    }


def _exact_package_record(prefix: Path, name: str) -> dict[str, object]:
    matches: list[tuple[Path, dict[str, object]]] = []
    for path in sorted((prefix / "conda-meta").glob(f"{name}-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and str(data.get("name", "")).lower() == name.lower():
            matches.append((path, data))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one exact installed {name} record, got {[path for path, _ in matches]}"
        )
    return matches[0][1]


def _archive_records(package_dir: Path, package: str) -> list[dict[str, object]]:
    return [
        {
            "path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "mib": path.stat().st_size / (1024 * 1024),
        }
        for path in sorted(package_dir.rglob(f"{package}-*.conda"))
    ]


def _footprint(base: ModuleType, package_dir: Path) -> dict[str, object]:
    prefix = Path(sys.prefix).resolve()
    package_names = {
        "runtime": "fenics-jit-runtime",
        "llvm-mingw": "fenics-jit-llvm-mingw",
        "micro-clang": "fenics-jit-micro-clang",
        "tinycc": "fenics-jit-tinycc",
    }
    records = {key: base._package_record(prefix, name) for key, name in package_names.items()}
    files = {key: base._owned_files(prefix, record) for key, record in records.items()}
    sizes = {key: sum(size for _, size in owned) for key, owned in files.items()}
    archives = {
        key: _archive_records(package_dir, package_names[key])
        for key in ("runtime", "micro-clang", "tinycc")
    }

    micro_bytes = sizes["micro-clang"]
    runtime_bytes = sizes["runtime"]
    llvm_bytes = sizes["llvm-mingw"]
    tiny_bytes = sizes["tinycc"]

    backend_records: dict[str, object] = {}
    for backend in _BACKENDS:
        backend_records[backend] = {
            "package_identity": _identity(records[backend]),
            "file_count": len(files[backend]),
            "installed_bytes": sizes[backend],
            "installed_mib": sizes[backend] / (1024 * 1024),
            "percent_of_stage_aw_installed": 100.0 * sizes[backend] / _STAGE_AW_INSTALLED_BYTES,
            "side_by_side_effective_install_increment_bytes": sizes[backend],
            "side_by_side_effective_install_increment_mib": sizes[backend] / (1024 * 1024),
            "standalone_incremental_bytes_with_common_runtime": runtime_bytes + sizes[backend],
            "standalone_incremental_mib_with_common_runtime": (
                runtime_bytes + sizes[backend]
            ) / (1024 * 1024),
        }

    backend_records["micro-clang"]["compressed_archives"] = archives["micro-clang"]
    backend_records["tinycc"]["compressed_archives"] = archives["tinycc"]
    backend_records["llvm-mingw"]["compressed_reference"] = {
        "qualification_run": _STAGE_AW["qualification_run"],
        "mib": _STAGE_AW["compressed_mib"],
        "method": "immutable Stage-AW reference; the pinned Phase-5 artifact does not rebuild LLVM-MinGW",
    }

    return {
        "stage_aw_reference": {
            **_STAGE_AW,
            "installed_bytes_from_rounded_mib": _STAGE_AW_INSTALLED_BYTES,
        },
        "common_runtime": {
            "package_identity": _identity(records["runtime"]),
            "file_count": len(files["runtime"]),
            "installed_bytes": runtime_bytes,
            "installed_mib": runtime_bytes / (1024 * 1024),
            "compressed_archives": archives["runtime"],
        },
        "backends": backend_records,
        "normal_install": {
            "llvm_mingw_remains_unconditional": True,
            "normal_install_footprint_reduction_claimed": False,
            "micro_clang_side_by_side_compiler_payload_bytes": llvm_bytes + micro_bytes,
            "micro_clang_side_by_side_compiler_payload_mib": (
                llvm_bytes + micro_bytes
            ) / (1024 * 1024),
            "backend_selected_profile_footprint": None,
            "backend_selected_profile_supported": False,
            "reason": (
                "recipes/dolfinx still declares fenics-jit-llvm-mingw unconditionally; "
                "a separately qualified profile/variant is required before a normal-install "
                "footprint reduction can be claimed"
            ),
        },
        "micro_clang_size_gates": {
            **_SIZE_GATES,
            "installed_bytes": micro_bytes,
            "early_50_percent_pass": micro_bytes <= _SIZE_GATES["early_50_percent_bytes"],
            "strong_37_5_percent_pass": micro_bytes <= _SIZE_GATES["strong_37_5_percent_bytes"],
            "stretch_25_percent_pass": micro_bytes <= _SIZE_GATES["stretch_25_percent_bytes"],
        },
        "informational_tinycc_installed_bytes": tiny_bytes,
    }


def _jit_benchmark(
    base: ModuleType,
    selector: ModuleType,
    forms: dict[str, object],
    base_cache: Path,
    diagnostics: Path,
    repeats: int,
) -> dict[str, object]:
    from dolfinx.jit import ffcx_jit

    runtimes = {backend: base._discover(selector, backend) for backend in _BACKENDS}
    physical = {backend: runtimes[backend].cache_root(base_cache) for backend in _BACKENDS}
    results: dict[str, object] = {}

    for form_index, (form_name, form) in enumerate(forms.items()):
        raw: dict[str, dict[str, list[dict[str, object]]]] = {
            backend: {"cold": [], "warm": []} for backend in _BACKENDS
        }
        sample_orders: list[list[str]] = []
        for repeat in range(repeats):
            order = _order(form_index * repeats + repeat)
            sample_orders.append(list(order))
            for backend in order:
                runtime = runtimes[backend]
                cache = physical[backend] / "p5cmp-jit" / form_name / f"r{repeat}"
                shutil.rmtree(cache, ignore_errors=True)
                cache.mkdir(parents=True, exist_ok=True)
                diag = diagnostics / "jit" / backend / form_name / f"r{repeat}"

                cold_probe = base._JITProbe(backend)
                with runtime.activate(
                    cache_root=physical[backend],
                    diagnostics_dir=diag / "cold",
                ):
                    with base._instrument_jit(cold_probe):
                        started = time.perf_counter()
                        ffcx_jit(MPI.COMM_SELF, form, jit_options={"cache_dir": cache})
                        total = time.perf_counter() - started
                cold = base._jit_record(total, cold_probe, cache)
                cold["repeat"] = repeat
                cold["order"] = list(order)
                if not cold_probe.compiler_commands or cold_probe.compiler_s <= 0:
                    raise RuntimeError(
                        f"cold {backend} JIT for {form_name} did not expose compiler timing"
                    )
                raw[backend]["cold"].append(cold)

                warm_probe = base._JITProbe(backend)
                with runtime.activate(
                    cache_root=physical[backend],
                    diagnostics_dir=diag / "warm",
                ):
                    with base._instrument_jit(warm_probe):
                        started = time.perf_counter()
                        ffcx_jit(MPI.COMM_SELF, form, jit_options={"cache_dir": cache})
                        total = time.perf_counter() - started
                warm = base._jit_record(total, warm_probe, cache)
                warm["repeat"] = repeat
                warm["order"] = list(order)
                if warm_probe.compiler_commands:
                    raise RuntimeError(
                        f"warm {backend} cache hit for {form_name} unexpectedly invoked compiler"
                    )
                raw[backend]["warm"].append(warm)

        fields = (
            "total_s",
            "ffcx_codegen_s",
            "cffi_compile_total_s",
            "compiler_link_s",
            "cffi_wrapper_build_overhead_s",
            "module_load_and_other_s",
        )
        backend_summaries: dict[str, object] = {}
        for backend in _BACKENDS:
            backend_summaries[backend] = {
                "backend_cache_id": runtimes[backend].backend_cache_id,
                "physical_cache_root": str(physical[backend]),
                "cold": {
                    field: base._summary([float(item[field]) for item in raw[backend]["cold"]])
                    for field in fields
                },
                "warm": {
                    field: base._summary([float(item[field]) for item in raw[backend]["warm"]])
                    for field in fields
                },
                "raw_cold": raw[backend]["cold"],
                "raw_warm": raw[backend]["warm"],
            }

        paired: dict[str, object] = {}
        for backend in ("micro-clang", "tinycc"):
            cold_ratios = [
                base._ratio(
                    float(raw[backend]["cold"][repeat]["total_s"]),
                    float(raw["llvm-mingw"]["cold"][repeat]["total_s"]),
                )
                for repeat in range(repeats)
            ]
            warm_ratios = [
                base._ratio(
                    float(raw[backend]["warm"][repeat]["total_s"]),
                    float(raw["llvm-mingw"]["warm"][repeat]["total_s"]),
                )
                for repeat in range(repeats)
            ]
            compiler_ratios = [
                base._ratio(
                    float(raw[backend]["cold"][repeat]["compiler_link_s"]),
                    float(raw["llvm-mingw"]["cold"][repeat]["compiler_link_s"]),
                )
                for repeat in range(repeats)
            ]
            paired[f"{backend}_over_llvm"] = {
                "cold_total": _scalar_summary(cold_ratios),
                "warm_total": _scalar_summary(warm_ratios),
                "compiler_link": _scalar_summary(compiler_ratios),
            }

        results[form_name] = {
            "sample_orders": sample_orders,
            "backends": backend_summaries,
            "paired_ratios": paired,
        }
    return results


def _compile_runtime_forms(
    base: ModuleType,
    selector: ModuleType,
    forms: dict[str, object],
    solve: dict[str, object],
    base_cache: Path,
    diagnostics: Path,
) -> dict[str, object]:
    from dolfinx import fem

    compiled: dict[str, object] = {}
    for backend in _BACKENDS:
        runtime = base._discover(selector, backend)
        physical = runtime.cache_root(base_cache)
        cache = physical / "p5cmp-runtime"
        shutil.rmtree(cache, ignore_errors=True)
        cache.mkdir(parents=True, exist_ok=True)
        with runtime.activate(
            cache_root=physical,
            diagnostics_dir=diagnostics / "runtime-compile" / backend,
        ):
            compiled_forms = {
                name: fem.form(form, jit_options={"cache_dir": cache})
                for name, form in forms.items()
            }
            compiled_a = fem.form(solve["a"], jit_options={"cache_dir": cache})
            compiled_l = fem.form(solve["L"], jit_options={"cache_dir": cache})
        compiled[backend] = {
            "forms": compiled_forms,
            "solve_a": compiled_a,
            "solve_L": compiled_l,
            "backend_cache_id": runtime.backend_cache_id,
            "cache": str(cache),
        }
    return compiled


def _assembly_benchmark(base: ModuleType, compiled: dict[str, object], repeats: int) -> dict[str, object]:
    results: dict[str, object] = {}
    for form_index, form_name in enumerate(compiled["llvm-mingw"]["forms"]):
        raw = {backend: [] for backend in _BACKENDS}
        for warmup in range(2):
            for backend in _order(form_index + warmup):
                base._assemble_matrix_once(compiled[backend]["forms"][form_name])

        orders: list[list[str]] = []
        for repeat in range(repeats):
            order = _order(form_index * repeats + repeat)
            orders.append(list(order))
            for backend in order:
                elapsed, norm = base._assemble_matrix_once(compiled[backend]["forms"][form_name])
                raw[backend].append(
                    {"repeat": repeat, "elapsed_s": elapsed, "matrix_norm": norm, "order": list(order)}
                )

        llvm_norm = statistics.median(item["matrix_norm"] for item in raw["llvm-mingw"])
        for backend in ("micro-clang", "tinycc"):
            norm = statistics.median(item["matrix_norm"] for item in raw[backend])
            if not math.isclose(llvm_norm, norm, rel_tol=1e-10, abs_tol=1e-11):
                raise RuntimeError(
                    f"assembly numerical mismatch for {form_name}: llvm={llvm_norm}, "
                    f"{backend}={norm}"
                )

        summaries = {
            backend: base._summary([float(item["elapsed_s"]) for item in raw[backend]])
            for backend in _BACKENDS
        }
        paired = {}
        for backend in ("micro-clang", "tinycc"):
            ratios = [
                base._ratio(
                    float(raw[backend][repeat]["elapsed_s"]),
                    float(raw["llvm-mingw"][repeat]["elapsed_s"]),
                )
                for repeat in range(repeats)
            ]
            paired[f"{backend}_over_llvm"] = _scalar_summary(ratios)

        results[form_name] = {
            "sample_orders": orders,
            "backends": summaries,
            "paired_ratios": paired,
            "matrix_norms": {
                backend: statistics.median(item["matrix_norm"] for item in raw[backend])
                for backend in _BACKENDS
            },
            "raw": raw,
        }
    return results


def _solve_benchmark(
    base: ModuleType,
    compiled: dict[str, object],
    bc,
    repeats: int,
) -> dict[str, object]:
    sample_count = max(5, repeats // 2)
    raw = {backend: [] for backend in _BACKENDS}
    for backend in _BACKENDS:
        base._solve_once(compiled[backend]["solve_a"], compiled[backend]["solve_L"], bc)

    orders: list[list[str]] = []
    for repeat in range(sample_count):
        order = _order(repeat)
        orders.append(list(order))
        for backend in order:
            sample = base._solve_once(
                compiled[backend]["solve_a"],
                compiled[backend]["solve_L"],
                bc,
            )
            sample["repeat"] = repeat
            sample["order"] = list(order)
            raw[backend].append(sample)

    llvm_norm = statistics.median(item["solution_norm"] for item in raw["llvm-mingw"])
    for backend in ("micro-clang", "tinycc"):
        norm = statistics.median(item["solution_norm"] for item in raw[backend])
        if not math.isclose(llvm_norm, norm, rel_tol=1e-10, abs_tol=1e-11):
            raise RuntimeError(f"Poisson solution mismatch: llvm={llvm_norm}, {backend}={norm}")

    summaries: dict[str, object] = {}
    for backend in _BACKENDS:
        summaries[backend] = {
            key: base._summary([float(item[key]) for item in raw[backend]])
            for key in ("assembly_s", "solver_s", "total_s")
        }

    paired: dict[str, object] = {}
    for backend in ("micro-clang", "tinycc"):
        paired_backend = {}
        for key in ("assembly_s", "solver_s", "total_s"):
            ratios = [
                base._ratio(
                    float(raw[backend][repeat][key]),
                    float(raw["llvm-mingw"][repeat][key]),
                )
                for repeat in range(sample_count)
            ]
            paired_backend[key] = _scalar_summary(ratios)
        paired[f"{backend}_over_llvm"] = paired_backend

    return {
        "sample_orders": orders,
        "backends": summaries,
        "paired_ratios": paired,
        "solution_norms": {
            backend: statistics.median(item["solution_norm"] for item in raw[backend])
            for backend in _BACKENDS
        },
        "raw": raw,
    }


def _environment_identities(base: ModuleType) -> dict[str, object]:
    prefix = Path(sys.prefix).resolve()
    names = (
        "fenics-dolfinx",
        "fenics-ffcx",
        "fenics-ufl",
        "fenics-basix",
        "petsc",
        "petsc4py",
        "numpy",
        "cffi",
    )
    result = {}
    for name in names:
        result[name] = _identity(_exact_package_record(prefix, name))
    return result


def _gate(
    footprint: dict[str, object],
    jit: dict[str, object],
    assembly: dict[str, object],
    solve: dict[str, object],
) -> dict[str, object]:
    assembly_ratios = [
        float(record["paired_ratios"]["micro-clang_over_llvm"]["median"])
        for record in assembly.values()
    ]
    cold_jit_ratios = [
        float(record["paired_ratios"]["micro-clang_over_llvm"]["cold_total"]["median"])
        for record in jit.values()
    ]
    assembly_aggregate = float(statistics.median(assembly_ratios))
    assembly_worst = max(assembly_ratios)
    cold_jit_worst = max(cold_jit_ratios)
    solve_total = float(solve["paired_ratios"]["micro-clang_over_llvm"]["total_s"]["median"])
    size_pass = bool(footprint["micro_clang_size_gates"]["early_50_percent_pass"])

    checks = {
        "size_early_50_percent": {
            "value_bytes": footprint["micro_clang_size_gates"]["installed_bytes"],
            "limit_bytes": footprint["micro_clang_size_gates"]["early_50_percent_bytes"],
            "pass": size_pass,
        },
        "assembly_family_aggregate_median": {
            "value_ratio": assembly_aggregate,
            "limit_ratio": 1.10,
            "pass": assembly_aggregate <= 1.10,
        },
        "assembly_worst_representative_form": {
            "value_ratio": assembly_worst,
            "limit_ratio": 1.20,
            "pass": assembly_worst <= 1.20,
        },
        "cold_jit_worst_representative_form": {
            "value_ratio": cold_jit_worst,
            "limit_ratio": 1.25,
            "pass": cold_jit_worst <= 1.25,
        },
        "end_to_end_poisson_total": {
            "value_ratio": solve_total,
            "limit_ratio": 1.20,
            "pass": solve_total <= 1.20,
            "policy": (
                "operational no-material-regression envelope for this harness; "
                "solver-only timing remains separately preserved"
            ),
        },
    }
    return {
        "pass": all(bool(item["pass"]) for item in checks.values()),
        "checks": checks,
        "assembly_form_ratios_micro_over_llvm": assembly_ratios,
        "cold_jit_form_ratios_micro_over_llvm": cold_jit_ratios,
        "note": (
            "micro-Clang is gated against paired same-run LLVM-MinGW measurements only; "
            "TinyCC is retained as the compact comparison and does not affect this gate"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--diagnostics-dir", required=True, type=Path)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--jit-repeats", type=int, default=5)
    parser.add_argument("--runtime-repeats", type=int, default=11)
    args = parser.parse_args()
    if args.jit_repeats < 3:
        raise RuntimeError("paired comparison requires at least 3 cold/warm JIT repetitions")
    if args.runtime_repeats < 5:
        raise RuntimeError("paired comparison requires at least 5 runtime repetitions")
    if MPI.COMM_WORLD.size != 1:
        raise RuntimeError("paired comparison must run in a single-rank process")

    diagnostics = args.diagnostics_dir.resolve()
    base_cache = args.cache_dir.resolve()
    package_dir = args.package_dir.resolve()
    diagnostics.mkdir(parents=True, exist_ok=True)
    base_cache.mkdir(parents=True, exist_ok=True)

    base = _load_base()
    selector = base._selector()
    model = base._build_forms()
    footprint = _footprint(base, package_dir)
    jit = _jit_benchmark(
        base,
        selector,
        model["forms"],
        base_cache,
        diagnostics,
        args.jit_repeats,
    )
    compiled = _compile_runtime_forms(
        base,
        selector,
        model["forms"],
        model["solve"],
        base_cache,
        diagnostics,
    )
    assembly = _assembly_benchmark(base, compiled, args.runtime_repeats)
    solve = _solve_benchmark(base, compiled, model["solve"]["bc"], args.runtime_repeats)
    gate = _gate(footprint, jit, assembly, solve)

    result = {
        "schema": 1,
        "kind": "micro-clang-phase5-three-backend-comparison",
        "status": "pass" if gate["pass"] else "performance-gate-failed",
        "python": {
            "version": sys.version,
            "major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
            "executable": sys.executable,
            "prefix": sys.prefix,
        },
        "runner": {
            "runner_os": os.environ.get("RUNNER_OS"),
            "runner_arch": os.environ.get("RUNNER_ARCH"),
            "runner_name": os.environ.get("RUNNER_NAME"),
            "image_os": os.environ.get("ImageOS"),
            "image_version": os.environ.get("ImageVersion"),
            "github_sha": os.environ.get("GITHUB_SHA"),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        },
        "measurement_policy": {
            "backends": list(_BACKENDS),
            "backend_order_cycle": [list(order) for order in _ORDER_CYCLE],
            "jit_repeats": args.jit_repeats,
            "runtime_repeats": args.runtime_repeats,
            "timing_clock": "time.perf_counter",
            "paired_denominator": "LLVM-MinGW sample from the same form/repetition on the same runner",
            "cold_cache": "unique cache per backend/form/repetition inside backend-owned namespace",
            "warm_cache": "immediate second lookup in the identical cache",
            "raw_distributions_preserved": True,
            "percentiles": [25, 50, 75, 90, 95],
        },
        "environment_packages": _environment_identities(base),
        "footprint": footprint,
        "jit_latency": jit,
        "assembly_runtime": assembly,
        "end_to_end_poisson": solve,
        "micro_clang_gate": gate,
    }
    output = diagnostics / "phase5-three-backend-summary.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": result["status"],
                "python": result["python"]["major_minor"],
                "micro_clang_installed_mib": footprint["backends"]["micro-clang"]["installed_mib"],
                "assembly_aggregate_ratio": gate["checks"]["assembly_family_aggregate_median"]["value_ratio"],
                "assembly_worst_ratio": gate["checks"]["assembly_worst_representative_form"]["value_ratio"],
                "cold_jit_worst_ratio": gate["checks"]["cold_jit_worst_representative_form"]["value_ratio"],
                "solve_total_ratio": gate["checks"]["end_to_end_poisson_total"]["value_ratio"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if gate["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
