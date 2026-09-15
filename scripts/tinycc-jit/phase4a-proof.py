"""Broad installed-package qualification for TinyCC Phase 4A / shared Phase 4B lifecycle.

The broad numerical/ABI qualification still uses either the existing LLVM-MinGW
runtime helper or the installed TinyCC backend's private adapter. In the
side-by-side LLVM reference process, this script also qualifies the installed
shared selector's real backend lifecycle and cross-backend serialization.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import threading
from pathlib import Path

import numpy as np
import pefile
from cffi import FFI

REVISION = "0fb54300b56512754221d80adda85ddb9815bceb"
REQUIRED_DLL_CHARACTERISTICS = 0x40 | 0x20 | 0x100
LIFECYCLE_SENTINEL = "FENICS_JIT_PHASE4B_LIFECYCLE_SENTINEL"


def load_module(path: Path, name: str):
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


def command_count(diagnostics: Path) -> int:
    path = diagnostics / "compiler-commands.jsonl"
    if not path.is_file():
        return 0
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])


def inspect_tinycc_modules(cache: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(cache.rglob("*.pyd")):
        pe = pefile.PE(str(path), fast_load=False)
        imports = sorted(
            entry.dll.decode("ascii", errors="replace").lower()
            for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
        )
        chars = int(pe.OPTIONAL_HEADER.DllCharacteristics)
        reloc = any(section.Name.rstrip(b"\0") == b".reloc" and section.SizeOfRawData for section in pe.sections)
        pdata = any(section.Name.rstrip(b"\0") == b".pdata" and section.SizeOfRawData for section in pe.sections)
        if "python3.dll" not in imports:
            raise RuntimeError(f"Stable-ABI python3.dll missing from {path}: {imports}")
        if any(name.startswith(("python312", "python313", "python314", "python315")) for name in imports):
            raise RuntimeError(f"minor-version Python import in {path}: {imports}")
        if (chars & REQUIRED_DLL_CHARACTERISTICS) != REQUIRED_DLL_CHARACTERISTICS:
            raise RuntimeError(f"required PE mitigation bits missing from {path}: 0x{chars:x}")
        if not reloc or not pdata:
            raise RuntimeError(f"relocation/unwind metadata missing from {path}: reloc={reloc}, pdata={pdata}")
        records.append(
            {
                "path": str(path),
                "imports": imports,
                "dll_characteristics": chars,
                "reloc": reloc,
                "pdata": pdata,
            }
        )
    if not records:
        raise RuntimeError(f"no generated TinyCC .pyd files found below {cache}")
    return records


def runtime_context(mode: str, backend_root: Path, diagnostics: Path):
    if mode == "tinycc":
        adapter = load_module(backend_root / "tinycc_adapter.py", "phase4a_tinycc_adapter")
        config = adapter.TinyCCConfig.discover(
            root=backend_root,
            python_def=backend_root / "python3.def",
            diagnostics_dir=diagnostics,
            revision=REVISION,
        )
        return adapter.activate(config), config.backend_cache_id

    runtime_path = Path(sys.prefix) / "Library/fenics-jit/runtime/fenics_jit_runtime.py"
    runtime = load_module(runtime_path, "phase4a_llvm_runtime")
    config = runtime.RuntimeConfig.discover(
        python_prefix=Path(sys.prefix),
    )
    return config.activate(diagnostics_dir=diagnostics), "llvm-mingw-stage-aw-reference"


class ObservedRLock:
    """RLock wrapper exposing when another thread reaches the shared lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._meta = threading.Lock()
        self._owner: int | None = None
        self._depth = 0
        self.waiter_attempted = threading.Event()

    def __enter__(self):
        thread_id = threading.get_ident()
        with self._meta:
            if self._owner is not None and self._owner != thread_id:
                self.waiter_attempted.set()
        self._lock.acquire()
        with self._meta:
            if self._owner is None:
                self._owner = thread_id
            elif self._owner != thread_id:
                raise RuntimeError("observed shared RLock owner invariant violated")
            self._depth += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        with self._meta:
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
        self._lock.release()
        return False


def load_shared_selector():
    path = Path(sys.prefix) / "Library/fenics-jit/runtime/fenics_jit_selector.py"
    if not path.is_file():
        raise RuntimeError(f"installed shared JIT selector is missing: {path}")
    return load_module(path, "phase4b_shared_jit_selector")


def discover_shared_backend(selector, backend: str):
    had = "FENICS_JIT_COMPILER" in os.environ
    old = os.environ.get("FENICS_JIT_COMPILER")
    os.environ["FENICS_JIT_COMPILER"] = backend
    try:
        runtime = selector.discover_runtime()
    finally:
        if had:
            assert old is not None
            os.environ["FENICS_JIT_COMPILER"] = old
        else:
            os.environ.pop("FENICS_JIT_COMPILER", None)
    if runtime.selected_backend != backend:
        raise RuntimeError(
            f"shared selector returned {runtime.selected_backend!r}, expected {backend!r}"
        )
    return runtime


@contextlib.contextmanager
def selected_backend(backend: str):
    had = "FENICS_JIT_COMPILER" in os.environ
    old = os.environ.get("FENICS_JIT_COMPILER")
    os.environ["FENICS_JIT_COMPILER"] = backend
    try:
        yield
    finally:
        if had:
            assert old is not None
            os.environ["FENICS_JIT_COMPILER"] = old
        else:
            os.environ.pop("FENICS_JIT_COMPILER", None)


def assert_shared_active(runtime, cache: Path) -> None:
    expected = {
        "FENICS_JIT_COMPILER": runtime.selected_backend,
        "FENICS_JIT_BACKEND_CACHE_ID": runtime.backend_cache_id,
        "FENICS_JIT_CACHE_ROOT": str(cache.resolve()),
        "FENICS_JIT_BACKEND_ROOT": str(runtime.backend_root.resolve()),
    }
    actual = {key: os.environ.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError(
            f"shared activation identity mismatch for {runtime.selected_backend}: "
            f"expected={expected!r}, actual={actual!r}"
        )


def assert_shared_record(
    diagnostics: Path,
    runtime,
    cache: Path,
    expected_depth: int,
) -> dict[str, object]:
    path = diagnostics / "shared-runtime.json"
    if not path.is_file():
        raise RuntimeError(f"shared runtime diagnostics missing: {path}")
    record = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "selected_backend": runtime.selected_backend,
        "backend_cache_id": runtime.backend_cache_id,
        "backend_root": str(runtime.backend_root.resolve()),
        "cache_root": str(cache.resolve()),
        "activation_depth": expected_depth,
    }
    actual = {key: record.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError(
            f"shared runtime diagnostics mismatch: expected={expected!r}, actual={actual!r}"
        )
    return record


def assert_shared_idle(selector, baseline: dict[str, str]) -> None:
    if selector._ACTIVE_BACKEND is not None:
        raise RuntimeError(f"shared runtime backend remained active: {selector._ACTIVE_BACKEND}")
    if selector._ACTIVE_OWNER_THREAD is not None:
        raise RuntimeError(
            f"shared runtime owner remained active: {selector._ACTIVE_OWNER_THREAD}"
        )
    if selector._ACTIVE_DEPTH != 0:
        raise RuntimeError(f"shared runtime depth did not restore: {selector._ACTIVE_DEPTH}")
    if dict(os.environ) != baseline:
        raise RuntimeError("process environment did not restore to the lifecycle baseline")


def qualify_same_backend_nesting(
    selector,
    runtime,
    base_cache: Path,
    diagnostics_root: Path,
) -> dict[str, object]:
    cache = runtime.cache_root(base_cache)
    outer_diagnostics = diagnostics_root / f"nested-{runtime.selected_backend}-outer"
    inner_diagnostics = diagnostics_root / f"nested-{runtime.selected_backend}-inner"
    baseline = dict(os.environ)
    with runtime.activate(cache_root=cache, diagnostics_dir=outer_diagnostics):
        assert_shared_active(runtime, cache)
        assert_shared_record(outer_diagnostics, runtime, cache, 1)
        outer_environment = dict(os.environ)
        with runtime.activate(cache_root=cache, diagnostics_dir=inner_diagnostics):
            assert_shared_active(runtime, cache)
            assert_shared_record(inner_diagnostics, runtime, cache, 2)
        if dict(os.environ) != outer_environment:
            raise RuntimeError(
                f"nested {runtime.selected_backend} activation did not restore outer environment"
            )
    assert_shared_idle(selector, baseline)
    return {
        "backend": runtime.selected_backend,
        "backend_cache_id": runtime.backend_cache_id,
        "cache_root": str(cache),
        "status": "pass",
    }


def qualify_conflicting_nested_backends(
    selector,
    outer,
    inner,
    base_cache: Path,
    diagnostics_root: Path,
) -> dict[str, object]:
    outer_cache = outer.cache_root(base_cache)
    baseline = dict(os.environ)
    message = ""
    with outer.activate(
        cache_root=outer_cache,
        diagnostics_dir=diagnostics_root / f"conflict-{outer.selected_backend}-outer",
    ):
        assert_shared_active(outer, outer_cache)
        outer_environment = dict(os.environ)
        try:
            with inner.activate(
                cache_root=inner.cache_root(base_cache),
                diagnostics_dir=diagnostics_root / f"conflict-{inner.selected_backend}-inner",
            ):
                raise RuntimeError("conflicting nested backend unexpectedly entered")
        except RuntimeError as exc:
            message = str(exc)
            if "Conflicting nested FEniCS JIT activation" not in message:
                raise
        else:
            raise RuntimeError("conflicting nested backend was accepted")
        if dict(os.environ) != outer_environment:
            raise RuntimeError("conflicting nested activation changed the outer environment")
    assert_shared_idle(selector, baseline)
    return {
        "outer": outer.selected_backend,
        "inner": inner.selected_backend,
        "error": message,
        "status": "pass",
    }


def qualify_exception_restoration(
    selector,
    runtime,
    base_cache: Path,
    diagnostics_root: Path,
) -> dict[str, object]:
    cache = runtime.cache_root(base_cache)
    baseline = dict(os.environ)
    try:
        with runtime.activate(
            cache_root=cache,
            diagnostics_dir=diagnostics_root / f"exception-{runtime.selected_backend}",
        ):
            assert_shared_active(runtime, cache)
            os.environ[LIFECYCLE_SENTINEL] = f"inside-{runtime.selected_backend}"
            raise ValueError("intentional shared-runtime lifecycle exception")
    except ValueError as exc:
        if "intentional shared-runtime lifecycle exception" not in str(exc):
            raise
    else:
        raise RuntimeError("intentional shared-runtime lifecycle exception did not propagate")
    assert_shared_idle(selector, baseline)

    with runtime.activate(
        cache_root=cache,
        diagnostics_dir=diagnostics_root / f"post-exception-{runtime.selected_backend}",
    ):
        assert_shared_active(runtime, cache)
    assert_shared_idle(selector, baseline)
    return {"backend": runtime.selected_backend, "status": "pass"}


def qualify_thread_serialization(
    selector,
    first,
    second,
    base_cache: Path,
    diagnostics_root: Path,
) -> dict[str, object]:
    baseline = dict(os.environ)
    original_lock = selector._ACTIVATION_LOCK
    observed_lock = ObservedRLock()
    selector._ACTIVATION_LOCK = observed_lock

    first_cache = first.cache_root(base_cache)
    second_cache = second.cache_root(base_cache)
    worker_entered = threading.Event()
    worker_errors: list[str] = []
    worker_observed: dict[str, str | None] = {}

    def worker() -> None:
        try:
            worker_diagnostics = (
                diagnostics_root
                / f"thread-{first.selected_backend}-then-{second.selected_backend}-second"
            )
            with second.activate(
                cache_root=second_cache,
                diagnostics_dir=worker_diagnostics,
            ):
                assert_shared_active(second, second_cache)
                assert_shared_record(worker_diagnostics, second, second_cache, 1)
                worker_observed["compiler"] = os.environ.get("FENICS_JIT_COMPILER")
                worker_observed["cache_id"] = os.environ.get("FENICS_JIT_BACKEND_CACHE_ID")
                worker_entered.set()
        except BaseException as exc:  # noqa: BLE001
            worker_errors.append(repr(exc))

    try:
        first_diagnostics = (
            diagnostics_root
            / f"thread-{first.selected_backend}-then-{second.selected_backend}-first"
        )
        with first.activate(
            cache_root=first_cache,
            diagnostics_dir=first_diagnostics,
        ):
            assert_shared_active(first, first_cache)
            assert_shared_record(first_diagnostics, first, first_cache, 1)
            thread = threading.Thread(
                target=worker,
                name=f"phase4b-{first.selected_backend}-to-{second.selected_backend}",
            )
            thread.start()
            if not observed_lock.waiter_attempted.wait(10):
                raise RuntimeError("worker did not reach the shared activation lock")
            if worker_entered.is_set():
                raise RuntimeError(
                    "second backend entered while the first backend still owned the shared lock"
                )
            assert_shared_active(first, first_cache)

        thread.join(20)
        if thread.is_alive():
            raise RuntimeError("worker did not finish after shared lock release")
        if worker_errors:
            raise RuntimeError(f"worker activation failed: {worker_errors}")
        if not worker_entered.is_set():
            raise RuntimeError("worker never completed its serialized activation")
        if worker_observed != {
            "compiler": second.selected_backend,
            "cache_id": second.backend_cache_id,
        }:
            raise RuntimeError(f"worker observed wrong backend identity: {worker_observed!r}")
        assert_shared_idle(selector, baseline)
    finally:
        selector._ACTIVATION_LOCK = original_lock

    return {
        "first": first.selected_backend,
        "second": second.selected_backend,
        "first_cache_root": str(first_cache),
        "second_cache_root": str(second_cache),
        "status": "pass",
    }


def pyd_snapshot(root: Path) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}
    if not root.is_dir():
        return snapshot
    for path in sorted(root.rglob("*.pyd")):
        relative = str(path.relative_to(root)).replace("\\", "/")
        stat = path.stat()
        snapshot[relative] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return snapshot


def clean_cache_base(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def shared_cache_probe(selector, backend: str, base_cache: Path) -> float:
    import ufl
    from dolfinx import fem, mesh
    from mpi4py import MPI

    runtime = discover_shared_backend(selector, backend)
    cache = runtime.cache_root(base_cache)
    diagnostics = (
        base_cache
        / "probe diagnostics"
        / backend
        / runtime.backend_cache_id
    )
    with runtime.activate(cache_root=cache, diagnostics_dir=diagnostics):
        domain = mesh.create_unit_square(MPI.COMM_WORLD, 2, 2)
        form = fem.form(
            fem.Constant(domain, 1.0) * ufl.dx,
            jit_options={"cache_dir": cache},
        )
        value = float(fem.assemble_scalar(form))
    if not math.isclose(value, 1.0, rel_tol=2e-10, abs_tol=2e-10):
        raise RuntimeError(f"{backend} shared-cache probe mismatch: {value}")
    return value


def qualify_switch_direction(
    selector,
    first_backend: str,
    second_backend: str,
    work: Path,
) -> dict[str, object]:
    base_cache = clean_cache_base(
        work / f"shared cache switch {first_backend} then {second_backend} with spaces"
    )
    first = discover_shared_backend(selector, first_backend)
    second = discover_shared_backend(selector, second_backend)
    first_root = first.cache_root(base_cache)
    second_root = second.cache_root(base_cache)
    if first_root == second_root:
        raise RuntimeError(
            f"backend switch shares one physical cache root: {first_backend} -> {second_backend}"
        )
    if pyd_snapshot(first_root) or pyd_snapshot(second_root):
        raise RuntimeError("fresh backend-switch cache roots were not empty")

    first_value = shared_cache_probe(selector, first_backend, base_cache)
    first_fresh = pyd_snapshot(first_root)
    if not first_fresh:
        raise RuntimeError(f"{first_backend} switch probe did not produce a compiled module")
    shared_cache_probe(selector, first_backend, base_cache)
    first_reuse = pyd_snapshot(first_root)
    if first_reuse != first_fresh:
        raise RuntimeError(f"{first_backend} same-identity cache reuse rewrote compiled modules")
    if pyd_snapshot(second_root):
        raise RuntimeError(
            f"{second_backend} cache root was populated before switching to that backend"
        )

    second_value = shared_cache_probe(selector, second_backend, base_cache)
    second_fresh = pyd_snapshot(second_root)
    if not second_fresh:
        raise RuntimeError(f"{second_backend} switch probe did not produce a compiled module")
    shared_cache_probe(selector, second_backend, base_cache)
    second_reuse = pyd_snapshot(second_root)
    if second_reuse != second_fresh:
        raise RuntimeError(f"{second_backend} same-identity cache reuse rewrote compiled modules")

    common_modules = sorted(
        {Path(path).name for path in first_fresh}
        & {Path(path).name for path in second_fresh}
    )
    if not common_modules:
        raise RuntimeError(
            "backend switch did not produce a common FFCx module name in the isolated roots"
        )

    return {
        "status": "pass",
        "sequence": [first_backend, second_backend],
        "base_cache": str(base_cache),
        "first": {
            "backend_cache_id": first.backend_cache_id,
            "cache_root": str(first_root),
            "fresh_module_count": len(first_fresh),
            "same_identity_reuse_unchanged": True,
            "value": first_value,
        },
        "second": {
            "backend_cache_id": second.backend_cache_id,
            "cache_root": str(second_root),
            "fresh_module_count": len(second_fresh),
            "same_identity_reuse_unchanged": True,
            "value": second_value,
        },
        "common_module_names": common_modules,
    }


def qualify_llvm_identity_change(selector, work: Path) -> dict[str, object]:
    base_cache = clean_cache_base(work / "shared cache llvm identity change with spaces")
    original = discover_shared_backend(selector, "llvm-mingw")
    original_root = original.cache_root(base_cache)
    metadata_path = original.backend_root / "metadata.json"
    original_bytes = metadata_path.read_bytes()

    original_value = shared_cache_probe(selector, "llvm-mingw", base_cache)
    original_fresh = pyd_snapshot(original_root)
    if not original_fresh:
        raise RuntimeError("LLVM-MinGW original identity did not produce a compiled module")
    shared_cache_probe(selector, "llvm-mingw", base_cache)
    if pyd_snapshot(original_root) != original_fresh:
        raise RuntimeError("LLVM-MinGW original same-identity cache reuse rewrote compiled modules")

    changed = None
    changed_root = None
    changed_fresh: dict[str, dict[str, object]] = {}
    changed_value = None
    try:
        metadata = json.loads(original_bytes.decode("utf-8-sig"))
        release = str(
            metadata.get("llvm_mingw_release")
            or metadata.get("package_version")
            or "unknown"
        )
        metadata["llvm_mingw_release"] = f"{release}-phase4b-identity-probe"
        encoding = "utf-8-sig" if original_bytes.startswith(b"\xef\xbb\xbf") else "utf-8"
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding=encoding,
        )

        changed = discover_shared_backend(selector, "llvm-mingw")
        changed_root = changed.cache_root(base_cache)
        if changed.backend_cache_id == original.backend_cache_id:
            raise RuntimeError("LLVM-MinGW metadata identity change did not change backend-cache-id")
        if changed_root == original_root:
            raise RuntimeError("LLVM-MinGW metadata identity change reused the original cache root")
        if pyd_snapshot(changed_root):
            raise RuntimeError("changed LLVM-MinGW identity cache root was not initially empty")

        changed_value = shared_cache_probe(selector, "llvm-mingw", base_cache)
        changed_fresh = pyd_snapshot(changed_root)
        if not changed_fresh:
            raise RuntimeError("changed LLVM-MinGW identity did not force a fresh compilation")
        shared_cache_probe(selector, "llvm-mingw", base_cache)
        if pyd_snapshot(changed_root) != changed_fresh:
            raise RuntimeError("changed LLVM-MinGW same-identity reuse rewrote compiled modules")
    finally:
        metadata_path.write_bytes(original_bytes)

    restored = discover_shared_backend(selector, "llvm-mingw")
    if restored.backend_cache_id != original.backend_cache_id:
        raise RuntimeError(
            "LLVM-MinGW backend-cache-id did not restore after the identity-change probe"
        )
    if restored.cache_root(base_cache) != original_root:
        raise RuntimeError("LLVM-MinGW original cache root did not restore after identity probe")
    if changed is None or changed_root is None or changed_value is None:
        raise RuntimeError("LLVM-MinGW identity-change probe did not complete")

    common_modules = sorted(
        {Path(path).name for path in original_fresh}
        & {Path(path).name for path in changed_fresh}
    )
    if not common_modules:
        raise RuntimeError(
            "LLVM-MinGW identity change did not compile a common FFCx module in the new namespace"
        )

    return {
        "status": "pass",
        "base_cache": str(base_cache),
        "original": {
            "backend_cache_id": original.backend_cache_id,
            "cache_root": str(original_root),
            "fresh_module_count": len(original_fresh),
            "same_identity_reuse_unchanged": True,
            "value": original_value,
        },
        "changed": {
            "backend_cache_id": changed.backend_cache_id,
            "cache_root": str(changed_root),
            "fresh_module_count": len(changed_fresh),
            "same_identity_reuse_unchanged": True,
            "value": changed_value,
        },
        "metadata_restored": True,
        "common_module_names": common_modules,
    }


def qualify_shared_cache_isolation(selector, work: Path) -> dict[str, object]:
    switches = [
        qualify_switch_direction(selector, "llvm-mingw", "tinycc", work),
        qualify_switch_direction(selector, "tinycc", "llvm-mingw", work),
    ]
    identity_change = qualify_llvm_identity_change(selector, work)
    return {
        "status": "pass",
        "switch_directions": switches,
        "identity_change": identity_change,
    }


def qualify_shared_runtime_lifecycle(work: Path) -> dict[str, object]:
    selector = load_shared_selector()
    llvm = discover_shared_backend(selector, "llvm-mingw")
    tinycc = discover_shared_backend(selector, "tinycc")
    base_cache = work / "shared lifecycle cache"
    diagnostics_root = work / "shared lifecycle diagnostics"
    diagnostics_root.mkdir(parents=True, exist_ok=True)

    llvm_cache = llvm.cache_root(base_cache)
    tinycc_cache = tinycc.cache_root(base_cache)
    if llvm.backend_cache_id == tinycc.backend_cache_id:
        raise RuntimeError("LLVM-MinGW and TinyCC unexpectedly share a backend cache identity")
    if llvm_cache == tinycc_cache:
        raise RuntimeError("LLVM-MinGW and TinyCC unexpectedly share a physical cache root")

    had_sentinel = LIFECYCLE_SENTINEL in os.environ
    old_sentinel = os.environ.get(LIFECYCLE_SENTINEL)
    os.environ[LIFECYCLE_SENTINEL] = "baseline"
    baseline = dict(os.environ)

    try:
        nesting = [
            qualify_same_backend_nesting(selector, llvm, base_cache, diagnostics_root),
            qualify_same_backend_nesting(selector, tinycc, base_cache, diagnostics_root),
        ]
        conflicts = [
            qualify_conflicting_nested_backends(
                selector, llvm, tinycc, base_cache, diagnostics_root
            ),
            qualify_conflicting_nested_backends(
                selector, tinycc, llvm, base_cache, diagnostics_root
            ),
        ]
        exceptions = [
            qualify_exception_restoration(selector, llvm, base_cache, diagnostics_root),
            qualify_exception_restoration(selector, tinycc, base_cache, diagnostics_root),
        ]
        threads = [
            qualify_thread_serialization(
                selector, llvm, llvm, base_cache, diagnostics_root
            ),
            qualify_thread_serialization(
                selector, tinycc, tinycc, base_cache, diagnostics_root
            ),
            qualify_thread_serialization(
                selector, llvm, tinycc, base_cache, diagnostics_root
            ),
            qualify_thread_serialization(
                selector, tinycc, llvm, base_cache, diagnostics_root
            ),
        ]
        cache_isolation = qualify_shared_cache_isolation(selector, work)
        assert_shared_idle(selector, baseline)
    finally:
        if had_sentinel:
            assert old_sentinel is not None
            os.environ[LIFECYCLE_SENTINEL] = old_sentinel
        else:
            os.environ.pop(LIFECYCLE_SENTINEL, None)

    return {
        "status": "pass",
        "backends": {
            "llvm-mingw": {
                "backend_cache_id": llvm.backend_cache_id,
                "backend_root": str(llvm.backend_root),
                "cache_root": str(llvm_cache),
            },
            "tinycc": {
                "backend_cache_id": tinycc.backend_cache_id,
                "backend_root": str(tinycc.backend_root),
                "cache_root": str(tinycc_cache),
            },
        },
        "same_backend_nesting": nesting,
        "conflicting_nested_backends": conflicts,
        "exception_restoration": exceptions,
        "thread_serialization": threads,
        "cache_isolation": cache_isolation,
    }


def assemble_metrics(cache: Path) -> dict[str, float]:
    import ufl
    from dolfinx import fem, mesh
    from mpi4py import MPI

    domain = mesh.create_unit_square(MPI.COMM_WORLD, 6, 5)
    one = fem.Constant(domain, 1.0)
    vector = fem.Constant(domain, np.array([1.25, -0.75], dtype=np.float64))
    tensor = fem.Constant(domain, np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64))
    x = ufl.SpatialCoordinate(domain)

    expressions = {
        "cell_scalar": one * ufl.dx,
        "facet_scalar": one * ufl.ds,
        "vector_cell": ufl.inner(vector, vector) * ufl.dx,
        "tensor_cell": ufl.inner(tensor, tensor) * ufl.dx,
        "coefficient_heavy": (1.3 + 0.7 * x[0] - 0.4 * x[1] + 0.25 * x[0] * x[1]) * ufl.dx,
        "vector_facet": ufl.inner(vector, vector) * ufl.ds,
    }

    values: dict[str, float] = {}
    for name, expression in expressions.items():
        form = fem.form(expression, jit_options={"cache_dir": cache})
        values[name] = float(fem.assemble_scalar(form))

    high = fem.functionspace(domain, ("Lagrange", 2))
    coefficient = fem.Function(high)
    coefficient.interpolate(lambda coords: coords[0] ** 2 + 0.5 * coords[1] ** 2)
    high_form = fem.form(coefficient * coefficient * ufl.dx, jit_options={"cache_dir": cache})
    values["higher_order_p2"] = float(fem.assemble_scalar(high_form))

    expected = {
        "cell_scalar": 1.0,
        "facet_scalar": 4.0,
        "vector_cell": 2.125,
        "tensor_cell": 30.0,
        "coefficient_heavy": 1.5125,
        "vector_facet": 8.5,
        "higher_order_p2": 13.0 / 36.0,
    }
    for name, target in expected.items():
        if not math.isclose(values[name], target, rel_tol=2e-10, abs_tol=2e-10):
            raise RuntimeError(f"{name} numerical result mismatch: got {values[name]}, expected {target}")
    return values


def crt_allocator_stress(backend_root: Path, diagnostics: Path, work: Path) -> Path:
    adapter = load_module(backend_root / "tinycc_adapter.py", "phase4a_crt_adapter")
    config = adapter.TinyCCConfig.discover(
        root=backend_root,
        python_def=backend_root / "python3.def",
        diagnostics_dir=diagnostics,
        revision=REVISION,
    )
    ffi = FFI()
    ffi.cdef("unsigned long long phase4a_crt_stress(int rounds);")
    ffi.set_source(
        "_tinycc_phase4a_crt",
        """
        #include <stdlib.h>
        #include <string.h>
        unsigned long long phase4a_crt_stress(int rounds) {
            unsigned long long total = 0;
            int i;
            for (i = 1; i <= rounds; ++i) {
                size_t n = (size_t)((i % 4093) + 1);
                unsigned char *p = (unsigned char *)malloc(n);
                if (!p) return 0;
                memset(p, i & 255, n);
                total += p[0] + p[n - 1] + (unsigned long long)n;
                free(p);
            }
            return total;
        }
        """,
    )
    build = work / "crt stress build with spaces"
    with adapter.activate(config):
        output = Path(ffi.compile(tmpdir=str(build), verbose=False)).resolve()
    module = load_module(output, "_tinycc_phase4a_crt")
    value = int(module.lib.phase4a_crt_stress(20000))
    if value <= 0:
        raise RuntimeError("mixed-CRT internal allocation stress failed")
    return output


def compare_metrics(actual: dict[str, float], reference_path: Path) -> None:
    reference = json.loads(reference_path.read_text(encoding="utf-8"))["metrics"]
    for name, value in actual.items():
        if name not in reference:
            raise RuntimeError(f"reference metric missing: {name}")
        if not math.isclose(value, float(reference[name]), rel_tol=2e-10, abs_tol=2e-10):
            raise RuntimeError(f"TinyCC/reference mismatch for {name}: {value} != {reference[name]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("llvm-mingw", "tinycc"), required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend-root", type=Path)
    parser.add_argument("--reference-json", type=Path)
    parser.add_argument("--cache-reload", action="store_true")
    args = parser.parse_args()

    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    diagnostics = work / "diagnostics"
    cache = work / "private cache with spaces"
    diagnostics.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    backend_root = (args.backend_root or (Path(sys.prefix) / "Library/fenics-jit/backends/tinycc")).resolve()

    shared_lifecycle = (
        qualify_shared_runtime_lifecycle(work)
        if args.mode == "llvm-mingw"
        else None
    )

    saved_cwd = Path.cwd()
    saved_home = os.environ.get("HOME")
    saved_profile = os.environ.get("USERPROFILE")
    hostile_home = work / "hostile home with spaces"
    hostile_home.mkdir(parents=True, exist_ok=True)
    (work / "setup.cfg").write_text(
        "[build_ext]\ncompiler=msvc\nbuild_temp=forbidden-build-temp\nlibrary_dirs=forbidden-library-root\n",
        encoding="utf-8",
    )
    (hostile_home / "pydistutils.cfg").write_text(
        "[build_ext]\ncompiler=msvc\nbuild_lib=forbidden-build-lib\n",
        encoding="utf-8",
    )

    before = command_count(diagnostics)
    try:
        os.chdir(work)
        if args.mode == "tinycc":
            os.environ["HOME"] = str(hostile_home)
            os.environ["USERPROFILE"] = str(hostile_home)
        manager, backend_cache_id = runtime_context(args.mode, backend_root, diagnostics)
        with manager:
            first = assemble_metrics(cache)
            middle = command_count(diagnostics)
            second = assemble_metrics(cache)
            after_repeat = command_count(diagnostics)
        if first != second:
            raise RuntimeError(f"same-process repeated results changed: {first} != {second}")

        crt_module = None
        if args.mode == "tinycc" and not args.cache_reload:
            crt_module = crt_allocator_stress(backend_root, diagnostics, work)
        after = command_count(diagnostics)
    finally:
        os.chdir(saved_cwd)
        if saved_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = saved_home
        if saved_profile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = saved_profile

    if args.mode == "tinycc":
        commands_path = diagnostics / "compiler-commands.jsonl"
        commands = commands_path.read_text(encoding="utf-8").lower() if commands_path.is_file() else ""
        forbidden = [token for token in ("cl.exe", "link.exe", "clang", "gcc", "vswhere", "windows kits", "microsoft visual studio") if token in commands]
        if forbidden:
            raise RuntimeError(f"forbidden host compiler/SDK input in TinyCC commands: {forbidden}")
        if args.reference_json is None:
            raise RuntimeError("--reference-json is required for TinyCC mode")
        compare_metrics(first, args.reference_json.resolve())
        if args.cache_reload and after != before:
            raise RuntimeError(f"new-process private cache reload unexpectedly compiled: before={before}, after={after}")
        if not args.cache_reload and middle <= before:
            raise RuntimeError(f"fresh TinyCC broad JIT did not invoke compiler: before={before}, first={middle}")
        if after_repeat != middle:
            raise RuntimeError(f"same-process cache reuse unexpectedly compiled: first={middle}, repeat={after_repeat}")
        pe_records = inspect_tinycc_modules(cache)
        if crt_module is not None:
            inspect_tinycc_modules(crt_module.parent)
    else:
        pe_records = []

    result = {
        "status": "pass",
        "mode": args.mode,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "backend_cache_id": backend_cache_id,
        "metrics": first,
        "same_process_repeat": second,
        "compiler_commands_before": before,
        "compiler_commands_after_first_forms": middle,
        "compiler_commands_after_repeat": after_repeat,
        "compiler_commands_after": after,
        "cache_reload": args.cache_reload,
        "generated_modules": pe_records,
        "hostile_config_root": str(work),
        "shared_runtime_lifecycle": shared_lifecycle,
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())