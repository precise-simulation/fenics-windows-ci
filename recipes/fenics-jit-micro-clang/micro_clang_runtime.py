"""Backend-owned micro-Clang integration for the shared Windows FEniCS JIT runtime."""

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
    "adapter_schema": "micro-clang-cffi-runtime-v1",
    "external_config": "suppress-all-v1",
    "language": "c17-no-complex-v1",
    "generated_code": "ffcx-setuptools-mingw-o2-qualified-v1",
    "python_link": "stable-abi-python3-importlib-v1",
    "crt": "ucrt-v1",
    "pe_hardening": "llvm-mingw-default-pe-v1",
}
_WINDOWS_ABI_POLICY = "x86_64-w64-mingw32-ms-bitfields-longdouble80-storage16-v1"
_SYSTEM_LIBRARY_POLICY = "windows-system-dll-resolution-v1"
_RUNTIME_MODULE_NAME = "_fenics_jit_micro_clang_backend_impl"


def _metadata_string(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"micro-Clang backend metadata does not contain {key}")
    return value.strip()


def _manifest_sha256(root: Path) -> str:
    path = root.resolve() / "manifest.csv"
    if not path.is_file():
        raise RuntimeError(f"micro-Clang backend manifest is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_runtime(root: Path) -> ModuleType:
    root = root.resolve()
    path = root / "fenics_jit_runtime.py"
    if not path.is_file():
        raise RuntimeError(f"micro-Clang backend runtime is missing: {path}")
    module = sys.modules.get(_RUNTIME_MODULE_NAME)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(_RUNTIME_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load micro-Clang backend runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_RUNTIME_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_RUNTIME_MODULE_NAME, None)
        raise
    return module


def backend_cache_id(*, root: Path, metadata: dict[str, object]) -> str:
    """Return an immutable cache ID covering the qualified compiler/sysroot payload."""
    manifest_sha256 = _manifest_sha256(root)
    payload = {
        "cache_schema": _CACHE_SCHEMA,
        "backend": "micro-clang",
        "backend_metadata": metadata,
        "installed_manifest_sha256": manifest_sha256,
        "policy": _BACKEND_POLICY,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    llvm_revision = _metadata_string(metadata, "llvm_commit")[:12]
    return f"micro-clang-{llvm_revision}-{digest}"


def _discover_config(*, root: Path, metadata: dict[str, object], expected_cache_id: str):
    root = root.resolve()
    actual_cache_id = backend_cache_id(root=root, metadata=metadata)
    if actual_cache_id != expected_cache_id:
        raise RuntimeError(
            "micro-Clang selected cache identity changed after runtime discovery: "
            f"selected={expected_cache_id}, backend={actual_cache_id}"
        )
    runtime = _load_runtime(root)
    return runtime.RuntimeConfig.discover(toolchain_root=root)


def diagnostic_record(*, root: Path, metadata: dict[str, object]) -> dict[str, object]:
    cache_id = backend_cache_id(root=root, metadata=metadata)
    config = _discover_config(root=root, metadata=metadata, expected_cache_id=cache_id)
    manifest_sha256 = _manifest_sha256(root)
    llvm_revision = _metadata_string(metadata, "llvm_commit")
    mingw_revision = _metadata_string(metadata, "mingw_w64_commit")
    record = config.diagnostic_record()
    record.update(
        {
            "adapter": "micro-clang-cffi-runtime",
            "backend_cache_id": cache_id,
            "compiler_revision": (
                f"llvm-{llvm_revision}-mingw-w64-{mingw_revision}-"
                f"manifest-{manifest_sha256}"
            ),
            "compiler_version": _metadata_string(metadata, "clang_version"),
            "llvm_commit": llvm_revision,
            "mingw_w64_commit": mingw_revision,
            "installed_manifest_sha256": manifest_sha256,
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
    config = _discover_config(
        root=root,
        metadata=metadata,
        expected_cache_id=expected_cache_id,
    )
    with config.activate(diagnostics_dir=diagnostics_dir, verbose=False):
        if verbose:
            print(
                "FEniCS JIT backend: "
                f"micro-clang / {expected_cache_id} / {config.clang}"
            )
        yield config
