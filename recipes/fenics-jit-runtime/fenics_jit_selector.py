"""Shared Windows FEniCS FFCx/CFFI JIT backend selector and lifecycle."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterator

_ALLOWED_BACKENDS = ("llvm-mingw", "tinycc")
_DEFAULT_BACKEND = "llvm-mingw"
_CACHE_SCHEMA = "fenics-jit-cache-v1"
_REMOVED_ENV = {
    "CC", "CXX", "CPP", "LD", "LDSHARED",
    "INCLUDE", "LIB", "LIBPATH", "LIBRARY_PATH",
    "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH",
    "COMPILER_PATH", "GCC_EXEC_PREFIX",
    "VSINSTALLDIR", "VCINSTALLDIR", "VCToolsInstallDir",
    "WindowsSdkDir", "WindowsSDKVersion",
    "UniversalCRTSdkDir", "UCRTVersion",
    "DISTUTILS_USE_SDK", "MSSdk",
}
_REMOVED_PREFIXES = ("VSCMD_",)

_ACTIVATION_LOCK = threading.RLock()
_ACTIVE_BACKEND: str | None = None
_ACTIVE_OWNER_THREAD: int | None = None
_ACTIVE_DEPTH = 0


def normalize_backend(value: str | None) -> str:
    """Normalize the public compiler selector or raise a deterministic error."""
    selected = _DEFAULT_BACKEND if value is None or not value.strip() else value.strip().lower()
    if selected not in _ALLOWED_BACKENDS:
        allowed = ", ".join(_ALLOWED_BACKENDS)
        raise RuntimeError(
            f"Invalid FENICS_JIT_COMPILER={value!r}; expected one of: {allowed}"
        )
    return selected


def selected_backend_name() -> str:
    return normalize_backend(os.getenv("FENICS_JIT_COMPILER"))


def backend_cache_root(base_cache: str | os.PathLike[str], backend: str, cache_id: str) -> Path:
    """Return the immutable physical cache namespace for one backend identity."""
    selected = normalize_backend(backend)
    return Path(base_cache).expanduser().resolve() / "ffcx" / selected / cache_id


def _load_module(path: Path, name: str) -> ModuleType:
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"JIT backend module is missing: {path}")
    module = sys.modules.get(name)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load JIT backend module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _read_metadata(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"{label} metadata is missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read {label} metadata: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid {label} metadata object: {path}")
    return data


def _backend_unavailable(name: str, root: Path) -> RuntimeError:
    return RuntimeError(
        f"FENICS_JIT_COMPILER={name!r} selected, but that backend package is unavailable; "
        f"expected backend root: {root}"
    )


def _sanitized_tinycc_environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        if key in _REMOVED_ENV or any(key.startswith(prefix) for prefix in _REMOVED_PREFIXES):
            env.pop(key, None)
    entries = []
    for entry in env.get("PATH", "").split(os.pathsep):
        lowered = entry.lower()
        if entry and "microsoft visual studio" not in lowered and "windows kits" not in lowered:
            entries.append(entry)
    env["PATH"] = os.pathsep.join(entries)
    env["SETUPTOOLS_USE_DISTUTILS"] = "local"
    return env


@contextlib.contextmanager
def _shared_activation(backend: str) -> Iterator[int]:
    """Serialize all process-global backend activation and define nesting semantics."""
    global _ACTIVE_BACKEND, _ACTIVE_OWNER_THREAD, _ACTIVE_DEPTH

    thread_id = threading.get_ident()
    with _ACTIVATION_LOCK:
        if _ACTIVE_DEPTH:
            if _ACTIVE_OWNER_THREAD != thread_id:
                raise RuntimeError("FEniCS JIT activation ownership invariant violated")
            if _ACTIVE_BACKEND != backend:
                raise RuntimeError(
                    "Conflicting nested FEniCS JIT activation is not permitted: "
                    f"active={_ACTIVE_BACKEND}, requested={backend}"
                )
        else:
            _ACTIVE_BACKEND = backend
            _ACTIVE_OWNER_THREAD = thread_id

        _ACTIVE_DEPTH += 1
        depth = _ACTIVE_DEPTH
        try:
            yield depth
        finally:
            _ACTIVE_DEPTH -= 1
            if _ACTIVE_DEPTH == 0:
                _ACTIVE_BACKEND = None
                _ACTIVE_OWNER_THREAD = None


@dataclass(frozen=True)
class SelectedRuntime:
    """Resolved shared-runtime selection for one JIT backend."""

    selected_backend: str
    backend_root: Path
    backend_cache_id: str
    metadata: dict[str, object]
    backend_module: ModuleType

    def cache_root(self, base_cache: str | os.PathLike[str]) -> Path:
        return backend_cache_root(base_cache, self.selected_backend, self.backend_cache_id)

    def diagnostic_record(self, cache_root: Path | None = None) -> dict[str, object]:
        return {
            "selected_backend": self.selected_backend,
            "backend_cache_id": self.backend_cache_id,
            "backend_root": str(self.backend_root),
            "cache_root": str(cache_root.resolve()) if cache_root is not None else None,
            "cache_schema": _CACHE_SCHEMA,
            "backend": self.backend_module.diagnostic_record(
                root=self.backend_root,
                metadata=self.metadata,
            ),
        }

    @contextlib.contextmanager
    def activate(
        self,
        *,
        cache_root: str | os.PathLike[str],
        diagnostics_dir: str | os.PathLike[str] | None = None,
        verbose: bool = False,
    ) -> Iterator["SelectedRuntime"]:
        """Activate the selected backend under the shared serialization contract."""
        cache = Path(cache_root).expanduser().resolve()
        cache.mkdir(parents=True, exist_ok=True)
        diagnostics = (
            Path(diagnostics_dir).expanduser().resolve()
            if diagnostics_dir is not None
            else Path(tempfile.gettempdir()).resolve()
            / "fenics-jit-diagnostics"
            / self.selected_backend
            / self.backend_cache_id
        )
        diagnostics.mkdir(parents=True, exist_ok=True)

        with _shared_activation(self.selected_backend) as depth:
            # Snapshot and restore process-global state while the shared lock is
            # still held. A waiting backend must not observe or later restore
            # another activation's temporary environment.
            saved_environment = dict(os.environ)
            try:
                os.environ["FENICS_JIT_COMPILER"] = self.selected_backend
                os.environ["FENICS_JIT_BACKEND_CACHE_ID"] = self.backend_cache_id
                os.environ["FENICS_JIT_CACHE_ROOT"] = str(cache)
                os.environ["FENICS_JIT_BACKEND_ROOT"] = str(self.backend_root)

                if self.selected_backend == "tinycc":
                    sanitized = _sanitized_tinycc_environment()
                    os.environ.clear()
                    os.environ.update(sanitized)
                    backend_context = self.backend_module.activate(
                        root=self.backend_root,
                        metadata=self.metadata,
                        diagnostics_dir=diagnostics,
                        expected_cache_id=self.backend_cache_id,
                    )
                else:
                    backend_context = self.backend_module.activate(
                        root=self.backend_root,
                        metadata=self.metadata,
                        diagnostics_dir=diagnostics,
                        expected_cache_id=self.backend_cache_id,
                        verbose=verbose,
                    )

                with backend_context:
                    record = self.diagnostic_record(cache)
                    record["activation_depth"] = depth
                    (diagnostics / "shared-runtime.json").write_text(
                        json.dumps(record, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    if verbose:
                        print(
                            "FEniCS JIT backend: "
                            f"{self.selected_backend} / {self.backend_cache_id} / {cache}"
                        )
                    yield self
            finally:
                os.environ.clear()
                os.environ.update(saved_environment)


def discover_runtime() -> SelectedRuntime:
    """Resolve the requested backend without silently falling back."""
    selected = selected_backend_name()
    jit_root = Path(__file__).resolve().parent.parent
    backend_root = (jit_root / "backends" / selected).resolve()
    if not backend_root.is_dir():
        raise _backend_unavailable(selected, backend_root)

    if selected == "llvm-mingw":
        metadata = _read_metadata(backend_root / "metadata.json", "LLVM-MinGW")
        module = _load_module(
            backend_root / "llvm_mingw_runtime.py",
            "_fenics_jit_llvm_mingw_runtime",
        )
    else:
        metadata = _read_metadata(backend_root / "backend-metadata.json", "TinyCC")
        module = _load_module(
            backend_root / "tinycc_runtime.py",
            "_fenics_jit_tinycc_runtime",
        )

    cache_id = module.backend_cache_id(root=backend_root, metadata=metadata)
    return SelectedRuntime(selected, backend_root, cache_id, metadata, module)


def _self_test_backend_module(name: str) -> ModuleType:
    """Create a no-compiler backend used to qualify shared lifecycle semantics."""
    module = ModuleType(name)

    def diagnostic_record(*, root: Path, metadata: dict[str, object]) -> dict[str, object]:
        return {
            "backend": name,
            "root": str(root.resolve()),
            "metadata": metadata,
        }

    @contextlib.contextmanager
    def activate(**kwargs) -> Iterator[ModuleType]:
        yield module

    module.diagnostic_record = diagnostic_record
    module.activate = activate
    return module


class _SelfTestLock:
    """Instrument an RLock so a test can observe a waiting thread deterministically."""

    def __init__(self, owner_thread: int):
        self._lock = threading.RLock()
        self._owner_thread = owner_thread
        self.waiter_attempted = threading.Event()

    def __enter__(self):
        if threading.get_ident() != self._owner_thread:
            self.waiter_attempted.set()
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._lock.release()
        return False


def _self_test() -> None:
    global _ACTIVATION_LOCK

    assert normalize_backend(None) == "llvm-mingw"
    assert normalize_backend("") == "llvm-mingw"
    assert normalize_backend(" LLVM-MinGW ") == "llvm-mingw"
    assert normalize_backend("tinycc") == "tinycc"
    try:
        normalize_backend("msvc")
    except RuntimeError as exc:
        assert "Invalid FENICS_JIT_COMPILER" in str(exc)
    else:
        raise AssertionError("invalid backend selector was accepted")

    root = backend_cache_root(Path("cache"), "tinycc", "tinycc-test-id")
    assert root.parts[-3:] == ("ffcx", "tinycc", "tinycc-test-id")

    with tempfile.TemporaryDirectory(prefix="fenics-jit-selector-selftest-") as temp_name:
        temp_root = Path(temp_name).resolve()
        base_cache = temp_root / "cache"
        llvm_root = temp_root / "llvm-mingw"
        tinycc_root = temp_root / "tinycc"
        llvm_root.mkdir()
        tinycc_root.mkdir()

        llvm = SelectedRuntime(
            "llvm-mingw",
            llvm_root,
            "llvm-mingw-selftest",
            {},
            _self_test_backend_module("_fenics_jit_selftest_llvm"),
        )
        tinycc = SelectedRuntime(
            "tinycc",
            tinycc_root,
            "tinycc-selftest",
            {},
            _self_test_backend_module("_fenics_jit_selftest_tinycc"),
        )

        sentinel_name = "FENICS_JIT_SELFTEST_SENTINEL"
        nested_name = "FENICS_JIT_SELFTEST_NESTED"
        old_sentinel = os.environ.get(sentinel_name)
        had_sentinel = sentinel_name in os.environ
        old_nested = os.environ.get(nested_name)
        had_nested = nested_name in os.environ
        os.environ[sentinel_name] = "baseline"
        os.environ.pop(nested_name, None)
        baseline_environment = dict(os.environ)

        try:
            # Same-backend nesting must be reentrant and restore the outer
            # activation's exact process environment when the inner scope exits.
            with tinycc.activate(
                cache_root=tinycc.cache_root(base_cache),
                diagnostics_dir=temp_root / "diag-nested-outer",
            ):
                assert _ACTIVE_BACKEND == "tinycc"
                assert _ACTIVE_OWNER_THREAD == threading.get_ident()
                assert _ACTIVE_DEPTH == 1
                outer_environment = dict(os.environ)
                with tinycc.activate(
                    cache_root=tinycc.cache_root(base_cache),
                    diagnostics_dir=temp_root / "diag-nested-inner",
                ):
                    assert _ACTIVE_BACKEND == "tinycc"
                    assert _ACTIVE_DEPTH == 2
                    os.environ[nested_name] = "inner"
                assert _ACTIVE_DEPTH == 1
                assert dict(os.environ) == outer_environment
            assert _ACTIVE_BACKEND is None
            assert _ACTIVE_OWNER_THREAD is None
            assert _ACTIVE_DEPTH == 0
            assert dict(os.environ) == baseline_environment

            # A conflicting backend in the same thread must fail before it can
            # alter the active backend's process-global state.
            with llvm.activate(
                cache_root=llvm.cache_root(base_cache),
                diagnostics_dir=temp_root / "diag-conflict-outer",
            ):
                outer_environment = dict(os.environ)
                try:
                    with tinycc.activate(
                        cache_root=tinycc.cache_root(base_cache),
                        diagnostics_dir=temp_root / "diag-conflict-inner",
                    ):
                        raise AssertionError("conflicting backend activation unexpectedly entered")
                except RuntimeError as exc:
                    assert "Conflicting nested FEniCS JIT activation" in str(exc)
                else:
                    raise AssertionError("conflicting backend activation was accepted")
                assert _ACTIVE_BACKEND == "llvm-mingw"
                assert _ACTIVE_DEPTH == 1
                assert dict(os.environ) == outer_environment
            assert dict(os.environ) == baseline_environment

            # Exceptions from user/JIT work must leave both lifecycle state and
            # the complete environment exactly as they were before activation.
            try:
                with tinycc.activate(
                    cache_root=tinycc.cache_root(base_cache),
                    diagnostics_dir=temp_root / "diag-exception",
                ):
                    os.environ[nested_name] = "exception"
                    raise ValueError("intentional shared-runtime restoration test")
            except ValueError as exc:
                assert "intentional shared-runtime restoration test" in str(exc)
            else:
                raise AssertionError("intentional activation exception did not propagate")
            assert _ACTIVE_BACKEND is None
            assert _ACTIVE_OWNER_THREAD is None
            assert _ACTIVE_DEPTH == 0
            assert dict(os.environ) == baseline_environment

            # Observe a second thread reaching the shared lock while LLVM owns
            # it. The worker must enter only after LLVM restores the baseline,
            # and after the worker exits it must not restore LLVM's stale state.
            original_lock = _ACTIVATION_LOCK
            probe_lock = _SelfTestLock(threading.get_ident())
            _ACTIVATION_LOCK = probe_lock
            worker_entered = threading.Event()
            worker_errors: list[BaseException] = []

            def worker() -> None:
                try:
                    with tinycc.activate(
                        cache_root=tinycc.cache_root(base_cache),
                        diagnostics_dir=temp_root / "diag-thread-tinycc",
                    ):
                        assert os.environ["FENICS_JIT_COMPILER"] == "tinycc"
                        assert _ACTIVE_BACKEND == "tinycc"
                        assert _ACTIVE_DEPTH == 1
                        worker_entered.set()
                except BaseException as exc:
                    worker_errors.append(exc)

            try:
                with llvm.activate(
                    cache_root=llvm.cache_root(base_cache),
                    diagnostics_dir=temp_root / "diag-thread-llvm",
                ):
                    assert os.environ["FENICS_JIT_COMPILER"] == "llvm-mingw"
                    thread = threading.Thread(target=worker, name="fenics-jit-selftest-worker")
                    thread.start()
                    if not probe_lock.waiter_attempted.wait(5):
                        raise AssertionError("worker did not reach the shared activation lock")
                    assert not worker_entered.is_set()
                    assert _ACTIVE_BACKEND == "llvm-mingw"
                    assert _ACTIVE_DEPTH == 1

                thread.join(5)
                if thread.is_alive():
                    raise AssertionError("worker did not finish after shared lock release")
                if worker_errors:
                    raise AssertionError(f"worker activation failed: {worker_errors!r}")
                assert worker_entered.is_set()
                assert _ACTIVE_BACKEND is None
                assert _ACTIVE_OWNER_THREAD is None
                assert _ACTIVE_DEPTH == 0
                assert dict(os.environ) == baseline_environment
            finally:
                _ACTIVATION_LOCK = original_lock
        finally:
            if had_sentinel:
                assert old_sentinel is not None
                os.environ[sentinel_name] = old_sentinel
            else:
                os.environ.pop(sentinel_name, None)
            if had_nested:
                assert old_nested is not None
                os.environ[nested_name] = old_nested
            else:
                os.environ.pop(nested_name, None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print("shared runtime selector self-test passed")
        return
    runtime = discover_runtime()
    print(json.dumps(runtime.diagnostic_record(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
