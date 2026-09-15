"""Backend-owned LLVM-MinGW integration for the shared Windows FEniCS JIT runtime."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterator

_CACHE_SCHEMA = "fenics-jit-cache-v1"
_BACKEND_POLICY = {
    "adapter_schema": "llvm-mingw-cffi-runtime-v1",
    "external_config": "suppress-all-v1",
    "language": "c17-no-complex-v1",
    "python_link": "stable-abi-python3-importlib-v1",
    "crt": "ucrt-v1",
    "pe_hardening": "llvm-mingw-default-pe-v1",
}
_WINDOWS_ABI_POLICY = "x86_64-w64-mingw32-ms-bitfields-longdouble80-storage16-v1"
_SYSTEM_LIBRARY_POLICY = "windows-system-dll-resolution-v1"
_RUNTIME_MODULE_NAME = "_fenics_jit_llvm_mingw_backend_impl"


def _metadata_string(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"LLVM-MinGW backend metadata does not contain {key}")
    return value.strip()


def _load_runtime(root: Path) -> ModuleType:
    root = root.resolve()
    path = root / "fenics_jit_runtime.py"
    if not path.is_file():
        raise RuntimeError(f"LLVM-MinGW backend runtime is missing: {path}")
    module = sys.modules.get(_RUNTIME_MODULE_NAME)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(_RUNTIME_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load LLVM-MinGW backend runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_RUNTIME_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_RUNTIME_MODULE_NAME, None)
        raise
    return module


def backend_cache_id(*, root: Path, metadata: dict[str, object]) -> str:
    """Return the immutable LLVM-MinGW binary-compatibility cache ID."""
    payload = {
        "cache_schema": _CACHE_SCHEMA,
        "backend": "llvm-mingw",
        "backend_metadata": metadata,
        "policy": _BACKEND_POLICY,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    version = str(
        metadata.get("llvm_mingw_release")
        or metadata.get("package_version")
        or "unknown"
    )
    return f"llvm-mingw-{version}-{digest}"


def _discover_config(
    *,
    root: Path,
    metadata: dict[str, object],
    expected_cache_id: str,
):
    root = root.resolve()
    declared_cache_id = backend_cache_id(root=root, metadata=metadata)
    if declared_cache_id != expected_cache_id:
        raise RuntimeError(
            "LLVM-MinGW selected cache identity changed after runtime discovery: "
            f"selected={expected_cache_id}, backend={declared_cache_id}"
        )
    runtime = _load_runtime(root)
    config = runtime.RuntimeConfig.discover(toolchain_root=root)
    return config


def diagnostic_record(*, root: Path, metadata: dict[str, object]) -> dict[str, object]:
    """Return backend-owned diagnostics without exposing LLVM policy to the selector."""
    cache_id = backend_cache_id(root=root, metadata=metadata)
    config = _discover_config(
        root=root,
        metadata=metadata,
        expected_cache_id=cache_id,
    )
    release = _metadata_string(metadata, "llvm_mingw_release")
    archive_sha256 = _metadata_string(metadata, "upstream_sha256")
    record = config.diagnostic_record()
    record.update(
        {
            "adapter": "llvm-mingw-cffi-runtime",
            "backend_cache_id": cache_id,
            "compiler_revision": f"llvm-mingw-{release}-sha256-{archive_sha256}",
            "compiler_release": release,
            "compiler_archive_sha256": archive_sha256,
            "compiler_version": _metadata_string(metadata, "clang_version"),
            "windows_abi_policy": _WINDOWS_ABI_POLICY,
            "external_config_policy": _BACKEND_POLICY["external_config"],
            "system_library_policy": _SYSTEM_LIBRARY_POLICY,
            "crt_identity": _BACKEND_POLICY["crt"],
            "python_abi_definition": str(config.python_stable_import_library),
            "include_roots": {
                "python": str(config.python_include),
                "ffcx": str(config.ffcx_include),
                "toolchain": str(config.toolchain_include),
            },
            "policy": {
                **_BACKEND_POLICY,
                "windows_abi": _WINDOWS_ABI_POLICY,
                "system_library": _SYSTEM_LIBRARY_POLICY,
            },
        }
    )
    return record


@contextlib.contextmanager
def activate(
    *,
    root: Path,
    metadata: dict[str, object],
    diagnostics_dir: Path,
    expected_cache_id: str,
    verbose: bool = False,
) -> Iterator[object]:
    """Activate the proven LLVM-MinGW runtime behind a backend-owned interface."""
    config = _discover_config(
        root=root,
        metadata=metadata,
        expected_cache_id=expected_cache_id,
    )
    with config.activate(diagnostics_dir=diagnostics_dir, verbose=verbose):
        yield config
