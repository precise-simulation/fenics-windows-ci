"""Phase 3 private broad qualification for the packaged micro-Clang backend."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Iterator

import pefile
import ufl
from mpi4py import MPI

_REQUIRED_DLL_CHARACTERISTICS = 0x20 | 0x40 | 0x100
_ACTIVE_CONFIG = None
_ACTIVE_BACKEND_ROOT: Path | None = None
_REFERENCE_ASSERT = None


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _reference_validator() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "llvm-mingw-jit"
        / "phase5-functional-validation.py"
    )
    return _load_module(path, "_micro_clang_phase3_reference_validator")


def _runtime_module(backend_root: Path) -> ModuleType:
    path = backend_root / "fenics_jit_runtime.py"
    if not path.is_file():
        raise RuntimeError(f"packaged micro-Clang runtime helper missing: {path}")
    return _load_module(path, "_micro_clang_phase3_runtime")


def _configure(backend_root: Path):
    runtime = _runtime_module(backend_root)
    return runtime.RuntimeConfig.discover(
        toolchain_root=backend_root,
        python_prefix=Path(sys.prefix),
    )


def _runtime_record() -> dict[str, object]:
    if _ACTIVE_CONFIG is None or _ACTIVE_BACKEND_ROOT is None:
        raise RuntimeError("micro-Clang Phase-3 runtime is not initialized")
    record = _ACTIVE_CONFIG.diagnostic_record()
    if Path(str(record["toolchain_root"])).resolve() != _ACTIVE_BACKEND_ROOT:
        raise RuntimeError(f"micro-Clang selected wrong backend root: {record!r}")
    if record["backend"] != "mingw32" or record["crt"] != "UCRT":
        raise RuntimeError(f"unexpected micro-Clang runtime configuration: {record!r}")
    target = str(record["clang_reported_target"])
    if not re.match(r"(?i)^x86_64-w64-(?:mingw32|windows-gnu)$", target):
        raise RuntimeError(f"unexpected micro-Clang target: {target!r}")
    return record


def _render_command(cmd: object) -> str:
    if isinstance(cmd, (list, tuple)):
        return subprocess.list2cmdline([str(part) for part in cmd])
    return str(cmd)


@contextlib.contextmanager
def _record_micro_calls(path: Path) -> Iterator[list[str]]:
    if _ACTIVE_CONFIG is None:
        raise RuntimeError("micro-Clang Phase-3 runtime is not initialized")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    calls: list[str] = []
    original = subprocess.check_call

    def logged(cmd, *args, **kwargs):  # noqa: ANN001
        rendered = _render_command(cmd)
        calls.append(rendered)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(rendered + "\n")
        return original(cmd, *args, **kwargs)

    with _ACTIVE_CONFIG.activate(
        diagnostics_dir=path.parent / f"{path.stem}-runtime",
        verbose=True,
    ):
        subprocess.check_call = logged
        try:
            yield calls
        finally:
            subprocess.check_call = original


def _assert_micro_commands(
    calls: list[str],
    record: dict[str, object],
    *,
    require_compile: bool,
) -> None:
    if _REFERENCE_ASSERT is None or _ACTIVE_BACKEND_ROOT is None:
        raise RuntimeError("micro-Clang command validator is not initialized")
    _REFERENCE_ASSERT(calls, record, require_compile=require_compile)
    text = "\n".join(calls).lower()
    if require_compile and str(_ACTIVE_BACKEND_ROOT).lower() not in text:
        raise RuntimeError("fresh JIT commands did not use the packaged micro-Clang root")
    normal = (
        Path(sys.prefix).resolve()
        / "Library"
        / "fenics-jit"
        / "backends"
        / "llvm-mingw"
    )
    if require_compile and str(normal).lower() in text:
        raise RuntimeError("micro-Clang JIT command leaked the normal LLVM-MinGW backend")


def _inspect_micro_pyds(cache_dirs: list[Path], diagnostics: Path) -> list[Path]:
    pyds = sorted(
        {path.resolve() for cache_dir in cache_dirs for path in cache_dir.rglob("*.pyd")}
    )
    if not pyds:
        raise RuntimeError("Phase-3 qualification produced no .pyd modules")

    unexpected = re.compile(
        r"(?i)^(?:python3\d{2}t?(?:_d)?\.dll|libgcc_s.*\.dll|libstdc\+\+.*\.dll|"
        r"libwinpthread.*\.dll|libclang_rt.*\.dll|clang_rt.*\.dll|libomp.*\.dll|cygwin1\.dll)$"
    )
    records: list[dict[str, object]] = []
    for path in pyds:
        pe = pefile.PE(str(path), fast_load=False)
        try:
            imports = sorted(
                entry.dll.decode("ascii", errors="replace").lower()
                for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
            )
            chars = int(pe.OPTIONAL_HEADER.DllCharacteristics)
            sections = {
                section.Name.rstrip(b"\0").decode("ascii", errors="replace"): int(
                    section.SizeOfRawData
                )
                for section in pe.sections
            }
        finally:
            pe.close()

        if "python3.dll" not in imports:
            raise RuntimeError(f"Stable-ABI python3.dll import missing from {path}: {imports}")
        bad = [name for name in imports if unexpected.match(name)]
        if bad:
            raise RuntimeError(f"unexpected compiler/version runtime imports in {path}: {bad}")
        if (chars & _REQUIRED_DLL_CHARACTERISTICS) != _REQUIRED_DLL_CHARACTERISTICS:
            raise RuntimeError(f"required PE mitigation bits missing from {path}: 0x{chars:x}")
        if not sections.get(".reloc") or not sections.get(".pdata"):
            raise RuntimeError(
                f"PE relocation/unwind metadata missing from {path}: "
                f"reloc={sections.get('.reloc', 0)}, pdata={sections.get('.pdata', 0)}"
            )
        records.append(
            {
                "path": str(path),
                "imports": imports,
                "dll_characteristics": chars,
                "reloc_size": sections[".reloc"],
                "pdata_size": sections[".pdata"],
            }
        )

    diagnostics.mkdir(parents=True, exist_ok=True)
    (diagnostics / "micro-clang-pyd-pe.json").write_text(
        json.dumps(records, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return pyds


def _normalized_source_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _verify_generated_c_contract(cache_root: Path, diagnostics: Path) -> dict[str, object]:
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "tests"
        / "tinycc"
        / "generated-corpus"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    version_record = manifest["python_versions"].get(version)
    if version_record is None:
        result = {
            "status": "informational-no-contract",
            "python": version,
            "manifest": str(manifest_path),
        }
    else:
        expected = version_record["modules"]
        actual_paths = {
            path.resolve().relative_to(cache_root).as_posix(): path.resolve()
            for path in cache_root.rglob("*.c")
        }
        expected_paths = {str(item["source_path"]) for item in expected}
        if set(actual_paths) != expected_paths:
            raise RuntimeError(
                "generated-C corpus path set changed: "
                f"missing={sorted(expected_paths - set(actual_paths))!r}, "
                f"unexpected={sorted(set(actual_paths) - expected_paths)!r}"
            )
        checked = []
        for item in expected:
            relative = str(item["source_path"])
            digest = _normalized_source_sha256(actual_paths[relative])
            expected_digest = str(item["normalized_source_sha256"])
            if digest != expected_digest:
                raise RuntimeError(
                    f"generated-C corpus hash mismatch for {relative}: "
                    f"{digest} != {expected_digest}"
                )
            checked.append(
                {
                    "source_path": relative,
                    "test_identity": item["test_identity"],
                    "normalized_source_sha256": digest,
                }
            )
        result = {
            "status": "pass",
            "python": version,
            "manifest": str(manifest_path),
            "module_count": len(checked),
            "modules": checked,
        }

    diagnostics.mkdir(parents=True, exist_ok=True)
    (diagnostics / "generated-corpus-check.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _numerical_metrics(config, cache: Path) -> dict[str, float]:
    from petsc4py import PETSc
    from dolfinx import fem, mesh
    from dolfinx.fem.petsc import assemble_matrix

    cache.mkdir(parents=True, exist_ok=True)
    with config.activate(diagnostics_dir=cache.parent / f"{cache.name}-runtime"):
        domain = mesh.create_unit_square(MPI.COMM_SELF, 5, 4)
        tdim = domain.topology.dim
        fdim = tdim - 1
        domain.topology.create_connectivity(fdim, tdim)
        one = fem.Constant(domain, PETSc.ScalarType(1.0))
        alpha = fem.Constant(domain, PETSc.ScalarType(2.75))
        V3 = fem.functionspace(domain, ("Lagrange", 3))
        q = fem.Function(V3)
        q.interpolate(lambda x: 0.5 + x[0] ** 3 + 0.25 * x[1] ** 2)
        u, v = ufl.TrialFunction(V3), ufl.TestFunction(V3)

        values = {
            "scalar_cell": float(
                fem.assemble_scalar(
                    fem.form(one * ufl.dx, jit_options={"cache_dir": cache})
                )
            ),
            "exterior_facet": float(
                fem.assemble_scalar(
                    fem.form(one * ufl.ds, jit_options={"cache_dir": cache})
                )
            ),
            "interior_facet": float(
                fem.assemble_scalar(
                    fem.form(one * ufl.dS, jit_options={"cache_dir": cache})
                )
            ),
            "p3_coefficient": float(
                fem.assemble_scalar(
                    fem.form((q * q + alpha * q) * ufl.dx, jit_options={"cache_dir": cache})
                )
            ),
        }
        matrix = assemble_matrix(
            fem.form(
                (ufl.inner(ufl.grad(u), ufl.grad(v)) + alpha * u * v) * ufl.dx,
                jit_options={"cache_dir": cache},
            )
        )
        matrix.assemble()
        values["p3_matrix_frobenius"] = float(
            matrix.norm(PETSc.NormType.FROBENIUS)
        )

    if not all(math.isfinite(value) for value in values.values()):
        raise RuntimeError(f"non-finite Phase-3 numerical metric: {values!r}")
    if values["p3_matrix_frobenius"] <= 0:
        raise RuntimeError(f"empty P3 matrix metric: {values!r}")
    return values


def _compare_metrics(reference: dict[str, float], actual: dict[str, float]) -> None:
    if set(reference) != set(actual):
        raise RuntimeError(
            f"numerical metric keys differ: reference={sorted(reference)}, "
            f"actual={sorted(actual)}"
        )
    for name, expected in reference.items():
        value = actual[name]
        if not math.isclose(value, expected, rel_tol=2e-10, abs_tol=2e-10):
            raise RuntimeError(
                f"micro-Clang/LLVM-MinGW numerical mismatch for {name}: "
                f"{value} != {expected}"
            )


def _cache_reload_child(
    backend_root: Path,
    cache: Path,
    diagnostics: Path,
) -> int:
    from petsc4py import PETSc
    from dolfinx import fem, mesh
    from dolfinx.jit import ffcx_jit

    global _ACTIVE_CONFIG, _ACTIVE_BACKEND_ROOT
    _ACTIVE_BACKEND_ROOT = backend_root
    _ACTIVE_CONFIG = _configure(backend_root)

    domain = mesh.create_unit_square(MPI.COMM_SELF, 2, 2)
    V = fem.functionspace(domain, ("Lagrange", 1))
    u, v = ufl.TrialFunction(V), ufl.TestFunction(V)
    form = (
        ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
        + PETSc.ScalarType(7.125) * u * v * ufl.dx
    )
    with _record_micro_calls(
        diagnostics / "new-process-cache-reload-commands.txt"
    ) as calls:
        ffcx_jit(
            MPI.COMM_SELF,
            form,
            jit_options={"cache_dir": cache, "cffi_verbose": True},
        )
    if calls:
        raise RuntimeError(
            "new-process cache reload unexpectedly invoked compiler/linker commands: "
            + "\n".join(calls)
        )
    return 0


def _concurrent_child(
    backend_root: Path,
    cache: Path,
    diagnostics: Path,
    scale: float,
) -> int:
    from dolfinx import fem, mesh

    config = _configure(backend_root)
    cache.mkdir(parents=True, exist_ok=True)
    diagnostics.mkdir(parents=True, exist_ok=True)
    with config.activate(diagnostics_dir=diagnostics):
        domain = mesh.create_unit_square(MPI.COMM_SELF, 3, 3)
        x = ufl.SpatialCoordinate(domain)
        value = float(
            fem.assemble_scalar(
                fem.form(
                    (scale + 0.125 * x[0]) * ufl.dx,
                    jit_options={"cache_dir": cache},
                )
            )
        )
    expected = scale + 0.0625
    if not math.isclose(value, expected, rel_tol=2e-10, abs_tol=2e-10):
        raise RuntimeError(f"concurrent process metric mismatch: {value} != {expected}")
    (diagnostics / "concurrent-summary.json").write_text(
        json.dumps(
            {"status": "pass", "scale": scale, "value": value},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def _install_validator_hooks(validator: ModuleType, backend_root: Path):
    global _ACTIVE_CONFIG, _ACTIVE_BACKEND_ROOT, _REFERENCE_ASSERT
    _ACTIVE_BACKEND_ROOT = backend_root
    _ACTIVE_CONFIG = _configure(backend_root)
    _REFERENCE_ASSERT = validator._assert_compiler_commands
    validator._runtime_record = _runtime_record
    validator._record_check_calls = _record_micro_calls
    validator._assert_compiler_commands = _assert_micro_commands
    validator._inspect_pyds = _inspect_micro_pyds
    return _ACTIVE_CONFIG


def _mpi_child(backend_root: Path, cache: Path, diagnostics: Path) -> int:
    validator = _reference_validator()
    _install_validator_hooks(validator, backend_root)
    try:
        validator._mpi_validation(cache, diagnostics)
    except BaseException:
        traceback.print_exc()
        sys.stderr.flush()
        try:
            MPI.COMM_WORLD.Abort(1)
        finally:
            os._exit(1)
    return 0


def _run_concurrency(
    backend_root: Path,
    work: Path,
    diagnostics: Path,
) -> dict[str, object]:
    script = Path(__file__).resolve()
    processes = []
    streams = []
    try:
        for index, scale in enumerate((2.0, 3.0), start=1):
            cache = work / f"concurrent process {index} cache with spaces"
            child_diag = diagnostics / f"concurrent-process-{index}"
            child_diag.mkdir(parents=True, exist_ok=True)
            stdout = (child_diag / "stdout.txt").open("w", encoding="utf-8")
            stderr = (child_diag / "stderr.txt").open("w", encoding="utf-8")
            streams.extend((stdout, stderr))
            command = [
                sys.executable,
                str(script),
                "--backend-root",
                str(backend_root),
                "--work-dir",
                str(work),
                "--diagnostics-dir",
                str(child_diag),
                "--child",
                "concurrent",
                "--cache-dir",
                str(cache),
                "--scale",
                str(scale),
            ]
            processes.append(
                (
                    index,
                    subprocess.Popen(
                        command,
                        stdout=stdout,
                        stderr=stderr,
                        text=True,
                    ),
                )
            )
        failures = []
        for index, process in processes:
            returncode = process.wait(timeout=180)
            if returncode != 0:
                failures.append((index, returncode))
        if failures:
            raise RuntimeError(
                f"concurrent micro-Clang subprocess qualification failed: {failures}"
            )
    finally:
        for stream in streams:
            stream.close()
    return {
        "status": "pass",
        "mode": "separate-process-concurrent-private-activation",
        "processes": len(processes),
        "shared_selector_thread_activation": (
            "deferred-to-phase5-before-selector-integration"
        ),
    }


def _run_mpi(
    backend_root: Path,
    work: Path,
    diagnostics: Path,
) -> dict[str, object]:
    helper = _load_module(
        Path(__file__).resolve().parents[1]
        / "tinycc-jit"
        / "phase4b-mpi-proof.py",
        "_micro_clang_phase3_mpi_helper",
    )
    mpiexec = helper.find_mpiexec()
    python_path = Path(sys.prefix).resolve() / "Lib/site-packages"
    cache = work / "two rank MPI cache with spaces"
    mpi_diag = diagnostics / "mpi"
    mpi_diag.mkdir(parents=True, exist_ok=True)
    command = [
        str(mpiexec),
        "-localonly",
        "-n",
        "2",
        "-env",
        "PATH",
        helper.mpi_path(),
        "-env",
        "PYTHONPATH",
        str(python_path),
        sys.executable,
        str(Path(__file__).resolve()),
        "--backend-root",
        str(backend_root),
        "--work-dir",
        str(work),
        "--diagnostics-dir",
        str(mpi_diag),
        "--child",
        "mpi",
        "--cache-dir",
        str(cache),
    ]
    (mpi_diag / "mpi-launch-command.txt").write_text(
        subprocess.list2cmdline(command) + "\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        command,
        check=False,
        timeout=helper.MPI_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"micro-Clang Phase-3 MPI qualification failed: {completed.returncode}"
        )
    summary = json.loads(
        (mpi_diag / "mpi-summary.json").read_text(encoding="utf-8")
    )
    compile_counts = summary.get("compile_commands_by_rank")
    if (
        not isinstance(compile_counts, list)
        or len(compile_counts) != 2
        or compile_counts[0] <= 0
        or compile_counts[1] != 0
    ):
        raise RuntimeError(f"unexpected micro-Clang MPI compile ownership: {summary!r}")
    return {
        "status": "pass",
        "ranks": 2,
        "compile_commands_by_rank": summary["compile_commands_by_rank"],
        "cache": str(cache),
    }


def _run_new_process_reload(
    backend_root: Path,
    cache: Path,
    work: Path,
    diagnostics: Path,
) -> dict[str, object]:
    child_diag = diagnostics / "new-process-reload"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--backend-root",
        str(backend_root),
        "--work-dir",
        str(work),
        "--diagnostics-dir",
        str(child_diag),
        "--child",
        "reload",
        "--cache-dir",
        str(cache),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    child_diag.mkdir(parents=True, exist_ok=True)
    (child_diag / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (child_diag / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"new-process micro-Clang cache reload failed: {completed.returncode}"
        )
    return {
        "status": "pass",
        "compiler_commands": 0,
        "cache": str(cache),
    }


def _verify_package_contract(backend_root: Path) -> dict[str, object]:
    required = [
        backend_root / "metadata.json",
        backend_root / "manifest.csv",
        backend_root / "size.txt",
        backend_root / "fenics_jit_runtime.py",
        backend_root / "provenance" / "build-provenance.json",
        backend_root / "provenance" / "retained-manifest.json",
        backend_root / "licenses" / "LLVM-LICENSE.TXT",
        backend_root / "licenses" / "llvm-mingw-LICENSE.txt",
        backend_root / "licenses" / "mingw-w64-COPYING",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Phase-3 installed package is incomplete: {missing}")
    metadata = json.loads(
        (backend_root / "metadata.json").read_text(encoding="utf-8-sig")
    )
    if metadata.get("production_selector_integrated") is not False:
        raise RuntimeError("Phase 3 must not integrate the production selector")
    return {
        "status": "pass",
        "metadata_phase": metadata.get("phase"),
        "production_selector_integrated": False,
        "required_files": len(required),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--diagnostics-dir", type=Path, required=True)
    parser.add_argument("--child", choices=("reload", "concurrent", "mpi"))
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args()

    backend_root = args.backend_root.resolve()
    work = args.work_dir.resolve()
    diagnostics = args.diagnostics_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    diagnostics.mkdir(parents=True, exist_ok=True)

    if args.child == "reload":
        if args.cache_dir is None:
            raise RuntimeError("--cache-dir is required for reload child")
        return _cache_reload_child(
            backend_root,
            args.cache_dir.resolve(),
            diagnostics,
        )
    if args.child == "concurrent":
        if args.cache_dir is None:
            raise RuntimeError("--cache-dir is required for concurrent child")
        return _concurrent_child(
            backend_root,
            args.cache_dir.resolve(),
            diagnostics,
            args.scale,
        )
    if args.child == "mpi":
        if args.cache_dir is None:
            raise RuntimeError("--cache-dir is required for MPI child")
        return _mpi_child(
            backend_root,
            args.cache_dir.resolve(),
            diagnostics,
        )

    for path in (Path(sys.prefix), backend_root, work):
        if " " not in str(path):
            raise RuntimeError(
                f"Phase-3 path-with-spaces contract not satisfied: {path}"
            )

    package_contract = _verify_package_contract(backend_root)
    validator = _reference_validator()
    micro_config = _install_validator_hooks(validator, backend_root)

    micro_cache = work / "micro clang broad cache with spaces"
    broad_diagnostics = diagnostics / "broad"
    validator._serial_validation(micro_cache, broad_diagnostics)

    corpus = _verify_generated_c_contract(
        micro_cache,
        diagnostics / "corpus",
    )
    new_process_reload = _run_new_process_reload(
        backend_root,
        micro_cache / "cache reload proof",
        work,
        diagnostics,
    )

    reference_root = (
        Path(sys.prefix).resolve()
        / "Library"
        / "fenics-jit"
        / "backends"
        / "llvm-mingw"
    )
    if not reference_root.is_dir():
        raise RuntimeError(
            f"installed LLVM-MinGW reference backend missing: {reference_root}"
        )
    reference_config = _configure(reference_root)
    reference_metrics = _numerical_metrics(
        reference_config,
        work / "llvm mingw numerical cache with spaces",
    )
    micro_metrics = _numerical_metrics(
        micro_config,
        work / "micro clang numerical cache with spaces",
    )
    _compare_metrics(reference_metrics, micro_metrics)

    concurrency = _run_concurrency(backend_root, work, diagnostics)
    mpi = _run_mpi(backend_root, work, diagnostics)

    result = {
        "schema": "fenics-jit-micro-clang-phase3-private-v1",
        "status": "pass",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "backend_root": str(backend_root),
        "production_selector_integrated": False,
        "default_backend_changed": False,
        "package_contract": package_contract,
        "generated_c_contract": corpus,
        "new_process_cache_reload": new_process_reload,
        "numerical_comparison": {
            "status": "pass",
            "reference_backend": "llvm-mingw",
            "reference": reference_metrics,
            "micro_clang": micro_metrics,
            "relative_tolerance": 2e-10,
            "absolute_tolerance": 2e-10,
        },
        "additional_coverage": [
            "higher-order P3",
            "interior facet dS",
            "exterior facet ds",
            "coefficient-heavy P3",
        ],
        "concurrency": concurrency,
        "mpi": mpi,
    }
    (diagnostics / "phase3-summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
