"""Shared Windows FEniCS FFCx/CFFI JIT backend selector and lifecycle."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
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
_LLVM_POLICY = {
    "adapter_schema": "llvm-mingw-cffi-runtime-v1",
    "external_config": "suppress-all-v1",
    "language": "c17-no-complex-v1",
    "python_link": "stable-abi-python3-importlib-v1",
    "crt": "ucrt-v1",
    "pe_hardening": "llvm-mingw-default-pe-v1",
}
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


def _llvm_cache_id(metadata: dict[str, object]) -> str:
    payload = {
        "cache_schema": _CACHE_SCHEMA,
        "backend": "llvm-mingw",
        "backend_metadata": metadata,
        "policy": _LLVM_POLICY,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    version = str(metadata.get("llvm_mingw_release") or metadata.get("package_version") or "unknown")
    return f"llvm-mingw-{version}-{digest}"


def _tinycc_cache_id(metadata: dict[str, object]) -> str:
    value = metadata.get("backend_cache_id")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("TinyCC backend metadata does not contain backend_cache_id")
    return value.strip()


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
    backend_config: object | None = None

    def cache_root(self, base_cache: str | os.PathLike[str]) -> Path:
        return backend_cache_root(base_cache, self.selected_backend, self.backend_cache_id)

    def diagnostic_record(self, cache_root: Path | None = None) -> dict[str, object]:
        record: dict[str, object] = {
            "selected_backend": self.selected_backend,
            "backend_cache_id": self.backend_cache_id,
            "backend_root": str(self.backend_root),
            "cache_root": str(cache_root.resolve()) if cache_root is not None else None,
            "cache_schema": _CACHE_SCHEMA,
        }
        if self.selected_backend == "llvm-mingw" and self.backend_config is not None:
            record["backend"] = self.backend_config.diagnostic_record()
        else:
            record["backend"] = {
                "source_revision": self.metadata.get("source_revision"),
                "policy": self.metadata.get("policy"),
            }
        return record

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

        saved_environment = dict(os.environ)
        try:
            with _shared_activation(self.selected_backend) as depth:
                os.environ["FENICS_JIT_COMPILER"] = self.selected_backend
                os.environ["FENICS_JIT_BACKEND_CACHE_ID"] = self.backend_cache_id
                os.environ["FENICS_JIT_CACHE_ROOT"] = str(cache)
                os.environ["FENICS_JIT_BACKEND_ROOT"] = str(self.backend_root)

                if self.selected_backend == "llvm-mingw":
                    assert self.backend_config is not None
                    backend_context = self.backend_config.activate(
                        diagnostics_dir=diagnostics,
                        verbose=verbose,
                    )
                else:
                    sanitized = _sanitized_tinycc_environment()
                    os.environ.clear()
                    os.environ.update(sanitized)
                    adapter = self.backend_module
                    revision = self.metadata.get("source_revision")
                    if not isinstance(revision, str) or not revision:
                        raise RuntimeError("TinyCC backend metadata does not contain source_revision")
                    tiny_config = adapter.TinyCCConfig.discover(
                        root=self.backend_root,
                        python_def=self.backend_root / "python3.def",
                        diagnostics_dir=diagnostics,
                        revision=revision,
                    )
                    if tiny_config.backend_cache_id != self.backend_cache_id:
                        raise RuntimeError(
                            "TinyCC backend cache identity mismatch: "
                            f"metadata={self.backend_cache_id}, adapter={tiny_config.backend_cache_id}"
                        )
                    backend_context = adapter.activate(tiny_config)

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
            Path(__file__).resolve().parent / "fenics_jit_runtime.py",
            "_fenics_jit_llvm_mingw_runtime",
        )
        config = module.RuntimeConfig.discover(toolchain_root=backend_root)
        cache_id = _llvm_cache_id(metadata)
        return SelectedRuntime(selected, backend_root, cache_id, metadata, module, config)

    metadata = _read_metadata(backend_root / "backend-metadata.json", "TinyCC")
    module = _load_module(
        backend_root / "tinycc_adapter.py",
        "_fenics_jit_tinycc_adapter",
    )
    cache_id = _tinycc_cache_id(metadata)
    return SelectedRuntime(selected, backend_root, cache_id, metadata, module)


def _self_test() -> None:
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
