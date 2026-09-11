"""Phase-2 qualification for the owned TinyCC CFFI adapter."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import threading
import time
from pathlib import Path

from cffi import FFI
from cffi import _shimmed_dist_utils as _dist

from tinycc_adapter import TinyCCConfig, activate, validate_cffi_integration

DEV_REVISION = "0fb54300b56512754221d80adda85ddb9815bceb"


def _find_python3_dll(prefix: Path) -> Path:
    for candidate in (prefix / "python3.dll", prefix / "DLLs" / "python3.dll"):
        if candidate.is_file():
            return candidate.resolve()
    matches = sorted(prefix.rglob("python3.dll"))
    if not matches:
        raise RuntimeError(f"python3.dll not found below {prefix}")
    return matches[0].resolve()


def _generate_python_def(config_root: Path, tcc: Path, python_dll: Path, output: Path) -> None:
    import subprocess

    subprocess.run(
        [str(tcc), "-B" + str(config_root), "-impdef", str(python_dll), "-o", str(output)],
        cwd=output.parent,
        check=True,
    )
    if not output.is_file():
        raise RuntimeError("python3.def generation failed")


def _load_extension(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_minimal(config: TinyCCConfig, build_dir: Path) -> Path:
    module_name = "_tinycc_phase2_space"
    ffi = FFI()
    ffi.cdef("int tinycc_phase2_value(void);")
    ffi.set_source(module_name, "int tinycc_phase2_value(void) { return 42; }")
    with activate(config):
        output = Path(ffi.compile(tmpdir=str(build_dir), verbose=True)).resolve()
    module = _load_extension(module_name, output)
    if module.lib.tinycc_phase2_value() != 42:
        raise RuntimeError("Phase-2 minimal CFFI result mismatch")
    return output


def _test_nested(config: TinyCCConfig) -> None:
    original = _dist.Distribution
    with activate(config):
        active = _dist.Distribution
        if active is original:
            raise RuntimeError("TinyCC Distribution interception did not activate")
        with activate(config):
            if _dist.Distribution is not active:
                raise RuntimeError("nested TinyCC activation replaced the owned Distribution")
        if _dist.Distribution is not active:
            raise RuntimeError("nested TinyCC activation restored too early")
    if _dist.Distribution is not original:
        raise RuntimeError("TinyCC Distribution interception was not restored")


def _test_conflicting_nested(config: TinyCCConfig, diagnostics: Path) -> None:
    other = TinyCCConfig.discover(
        root=config.root,
        python_def=config.python_def,
        diagnostics_dir=diagnostics / "conflicting-config",
        revision=config.revision + "-different-policy-instance",
    )
    with activate(config):
        try:
            with activate(other):
                pass
        except RuntimeError as exc:
            if "Conflicting nested" not in str(exc):
                raise
        else:
            raise RuntimeError("conflicting nested TinyCC activation unexpectedly succeeded")


def _test_exception_restoration(config: TinyCCConfig) -> None:
    original = _dist.Distribution
    try:
        with activate(config):
            raise ValueError("intentional restoration test")
    except ValueError:
        pass
    if _dist.Distribution is not original:
        raise RuntimeError("exception path failed to restore CFFI Distribution")


def _test_thread_serialization(config: TinyCCConfig) -> dict[str, float]:
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    timings: dict[str, float] = {}
    errors: list[BaseException] = []

    def first() -> None:
        try:
            with activate(config):
                timings["first_enter"] = time.monotonic()
                first_entered.set()
                if not release_first.wait(timeout=20):
                    raise RuntimeError("thread serialization release timeout")
                timings["first_exit"] = time.monotonic()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def second() -> None:
        try:
            if not first_entered.wait(timeout=20):
                raise RuntimeError("thread serialization start timeout")
            timings["second_attempt"] = time.monotonic()
            with activate(config):
                timings["second_enter"] = time.monotonic()
                second_entered.set()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=first, name="tinycc-phase2-first")
    t2 = threading.Thread(target=second, name="tinycc-phase2-second")
    t1.start()
    t2.start()
    if not first_entered.wait(timeout=20):
        raise RuntimeError("first activation thread did not enter")
    time.sleep(0.25)
    if second_entered.is_set():
        raise RuntimeError("second TinyCC activation interleaved instead of waiting")
    release_first.set()
    t1.join(timeout=20)
    t2.join(timeout=20)
    if t1.is_alive() or t2.is_alive():
        raise RuntimeError("thread serialization test did not terminate")
    if errors:
        raise errors[0]
    if timings["second_enter"] < timings["first_exit"]:
        raise RuntimeError(f"second activation entered before first restored state: {timings}")
    return timings


def _test_negative_metadata(config: TinyCCConfig, build_dir: Path) -> dict[str, str]:
    results: dict[str, str] = {}

    ffi_flag = FFI()
    ffi_flag.cdef("int x(void);")
    ffi_flag.set_source("_tinycc_phase2_badflag", "int x(void){return 1;}", extra_compile_args=["-fdefinitely-unsupported"])
    try:
        with activate(config):
            ffi_flag.compile(tmpdir=str(build_dir / "bad flag"), verbose=False)
    except Exception as exc:  # noqa: BLE001
        if "does not support compile argument" not in str(exc):
            raise
        results["unsupported_flag"] = str(exc)
    else:
        raise RuntimeError("unsupported important compile flag was silently accepted")

    ffi_lib = FFI()
    ffi_lib.cdef("int y(void);")
    ffi_lib.set_source("_tinycc_phase2_badlib", "int y(void){return 1;}", libraries=["python312"])
    try:
        with activate(config):
            ffi_lib.compile(tmpdir=str(build_dir / "bad library"), verbose=False)
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if "python312" not in text.lower() and "rejects CFFI libraries" not in text:
            raise
        results["versioned_python_library"] = text
    else:
        raise RuntimeError("versioned Python library was silently accepted")

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tinycc-root", required=True, type=Path)
    parser.add_argument("--python-prefix", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--diagnostics-dir", required=True, type=Path)
    args = parser.parse_args()

    root = args.tinycc_root.resolve()
    prefix = args.python_prefix.resolve()
    work = args.work_dir.resolve()
    diagnostics = args.diagnostics_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    diagnostics.mkdir(parents=True, exist_ok=True)

    tcc = (root / "tcc.exe").resolve()
    python_def = (work / "python3.def").resolve()
    _generate_python_def(root, tcc, _find_python3_dll(prefix), python_def)

    config = TinyCCConfig.discover(
        root=root,
        python_def=python_def,
        diagnostics_dir=diagnostics,
        revision=DEV_REVISION,
    )

    dependency_contract = validate_cffi_integration()
    _test_nested(config)
    _test_conflicting_nested(config, diagnostics)
    _test_exception_restoration(config)
    thread_timings = _test_thread_serialization(config)

    # Deliberately exercise spaces and a non-default nested temporary directory.
    build_dir = work / "non default temp" / "path with spaces"
    build_dir.mkdir(parents=True, exist_ok=True)
    extension = _build_minimal(config, build_dir)
    negatives = _test_negative_metadata(config, work / "negative cases")

    summary = {
        "status": "pass",
        "dependencies": dependency_contract,
        "backend_cache_id": config.backend_cache_id,
        "policy": config.policy_metadata(),
        "extension": str(extension),
        "path_with_spaces": " " in str(extension),
        "thread_serialization": thread_timings,
        "negative_tests": negatives,
        "external_config_policy": "suppressed by owned Distribution",
        "cross_backend_concurrency": "deferred until Phase 4B shared runtime integration as specified",
    }
    if not summary["path_with_spaces"]:
        raise RuntimeError(f"Phase-2 path-with-spaces proof did not use a spaced output path: {extension}")
    (diagnostics / "phase2-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
