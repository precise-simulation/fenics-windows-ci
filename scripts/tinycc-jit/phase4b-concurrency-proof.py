"""Real shared-runtime JIT concurrency qualification for TinyCC Phase 4B."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import threading
from pathlib import Path


class GatedObservedRLock:
    """Hold the first owner until another thread has attempted the shared lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._meta = threading.Lock()
        self._owner: int | None = None
        self._depth = 0
        self._gate_thread: int | None = None
        self.first_acquired = threading.Event()
        self.waiter_attempted = threading.Event()
        self.release_first = threading.Event()

    def __enter__(self):
        thread_id = threading.get_ident()
        with self._meta:
            if self._owner is not None and self._owner != thread_id:
                self.waiter_attempted.set()

        self._lock.acquire()
        gate = False
        with self._meta:
            if self._owner is None:
                self._owner = thread_id
                if self._gate_thread is None:
                    self._gate_thread = thread_id
                    gate = True
            elif self._owner != thread_id:
                self._lock.release()
                raise RuntimeError("gated shared RLock owner invariant violated")
            self._depth += 1

        if gate:
            self.first_acquired.set()
            if not self.release_first.wait(30):
                with self._meta:
                    self._depth -= 1
                    if self._depth == 0:
                        self._owner = None
                self._lock.release()
                raise RuntimeError("timed out waiting to release the first JIT worker")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        with self._meta:
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
        self._lock.release()
        return False


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


def load_shared_selector():
    path = Path(sys.prefix) / "Library/fenics-jit/runtime/fenics_jit_selector.py"
    if not path.is_file():
        raise RuntimeError(f"installed shared JIT selector is missing: {path}")
    return load_module(path, "phase4b_concurrency_selector")


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


def assert_shared_record(diagnostics: Path, runtime, cache: Path) -> dict[str, object]:
    path = diagnostics / "shared-runtime.json"
    if not path.is_file():
        raise RuntimeError(f"shared runtime diagnostics missing: {path}")
    record = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "selected_backend": runtime.selected_backend,
        "backend_cache_id": runtime.backend_cache_id,
        "backend_root": str(runtime.backend_root.resolve()),
        "cache_root": str(cache.resolve()),
        "activation_depth": 1,
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
        raise RuntimeError("process environment did not restore after concurrent JIT requests")


def compile_probe(runtime, base_cache: Path, diagnostics: Path, scale: float) -> dict[str, object]:
    import ufl
    from dolfinx import fem, mesh
    from mpi4py import MPI

    cache = runtime.cache_root(base_cache)
    if pyd_snapshot(cache):
        raise RuntimeError(f"concurrent JIT cache was not fresh: {cache}")

    with runtime.activate(cache_root=cache, diagnostics_dir=diagnostics):
        assert_shared_active(runtime, cache)
        record = assert_shared_record(diagnostics, runtime, cache)
        domain = mesh.create_unit_square(MPI.COMM_WORLD, 2, 2)
        x = ufl.SpatialCoordinate(domain)
        form = fem.form(
            (1.0 + scale * x[0]) * ufl.dx,
            jit_options={"cache_dir": cache},
        )
        value = float(fem.assemble_scalar(form))
        modules = pyd_snapshot(cache)
        if not modules:
            raise RuntimeError(
                f"{runtime.selected_backend} concurrent JIT did not compile a module"
            )
        assert_shared_active(runtime, cache)
        assert_shared_record(diagnostics, runtime, cache)

    expected = 1.0 + 0.5 * scale
    if not math.isclose(value, expected, rel_tol=2e-10, abs_tol=2e-10):
        raise RuntimeError(
            f"{runtime.selected_backend} concurrent JIT numerical mismatch: "
            f"got {value}, expected {expected}"
        )
    return {
        "backend": runtime.selected_backend,
        "backend_cache_id": runtime.backend_cache_id,
        "cache_root": str(cache),
        "value": value,
        "generated_modules": modules,
        "diagnostics": record,
    }


def qualify_pair(selector, first, second, work: Path, label: str) -> dict[str, object]:
    root = work / f"{label} with spaces"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    baseline = dict(os.environ)
    original_lock = selector._ACTIVATION_LOCK
    gated_lock = GatedObservedRLock()
    selector._ACTIVATION_LOCK = gated_lock

    results: dict[str, dict[str, object]] = {}
    errors: list[str] = []
    result_lock = threading.Lock()

    def worker(name: str, runtime, scale: float) -> None:
        try:
            result = compile_probe(
                runtime,
                root / f"{name} logical cache",
                root / "diagnostics" / name,
                scale,
            )
        except BaseException as exc:  # noqa: BLE001
            with result_lock:
                errors.append(f"{name}: {exc!r}")
        else:
            with result_lock:
                results[name] = result

    first_thread = threading.Thread(
        target=worker,
        args=("first", first, 1.25),
        name=f"phase4b-jit-{label}-first",
    )
    second_thread = threading.Thread(
        target=worker,
        args=("second", second, 2.5),
        name=f"phase4b-jit-{label}-second",
    )

    first_started = False
    second_started = False
    try:
        first_thread.start()
        first_started = True
        if not gated_lock.first_acquired.wait(30):
            raise RuntimeError(f"{label}: first JIT worker did not acquire the shared lock")
        second_thread.start()
        second_started = True
        if not gated_lock.waiter_attempted.wait(30):
            raise RuntimeError(f"{label}: second JIT worker did not contend for the shared lock")
        if results or errors:
            raise RuntimeError(
                f"{label}: a JIT worker completed before the contention gate was released"
            )

        gated_lock.release_first.set()
        first_thread.join(180)
        second_thread.join(180)
        if first_thread.is_alive() or second_thread.is_alive():
            raise RuntimeError(f"{label}: concurrent JIT workers did not finish")
        if errors:
            raise RuntimeError(f"{label}: concurrent JIT worker failed: {errors}")
        if set(results) != {"first", "second"}:
            raise RuntimeError(f"{label}: incomplete concurrent JIT results: {results!r}")
        assert_shared_idle(selector, baseline)
    finally:
        gated_lock.release_first.set()
        if first_started:
            first_thread.join(5)
        if second_started:
            second_thread.join(5)
        selector._ACTIVATION_LOCK = original_lock

    if results["first"]["cache_root"] == results["second"]["cache_root"]:
        raise RuntimeError(f"{label}: concurrent JIT requests unexpectedly shared one cache root")

    return {
        "status": "pass",
        "pair": [first.selected_backend, second.selected_backend],
        "contention_observed": True,
        "first": results["first"],
        "second": results["second"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    selector = load_shared_selector()
    llvm = discover_shared_backend(selector, "llvm-mingw")
    tinycc = discover_shared_backend(selector, "tinycc")

    result = {
        "status": "pass",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "pairs": [
            qualify_pair(selector, tinycc, tinycc, work, "tinycc-tinycc"),
            qualify_pair(selector, llvm, llvm, work, "llvm-mingw-llvm-mingw"),
            qualify_pair(selector, llvm, tinycc, work, "llvm-mingw-tinycc"),
        ],
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
