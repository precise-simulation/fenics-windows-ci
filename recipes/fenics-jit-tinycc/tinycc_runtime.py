"""Backend-owned TinyCC integration for the shared Windows FEniCS JIT runtime."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Iterator

_ADAPTER_MODULE_NAME = "_fenics_jit_tinycc_adapter_runtime"


def _load_adapter(root: Path) -> ModuleType:
    root = root.resolve()
    path = root / "tinycc_adapter.py"
    if not path.is_file():
        raise RuntimeError(f"TinyCC adapter is missing: {path}")
    module = sys.modules.get(_ADAPTER_MODULE_NAME)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(_ADAPTER_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load TinyCC adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_ADAPTER_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_ADAPTER_MODULE_NAME, None)
        raise
    return module


def _metadata_string(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"TinyCC backend metadata does not contain {key}")
    return value.strip()


def backend_cache_id(*, root: Path, metadata: dict[str, object]) -> str:
    """Return and validate the immutable TinyCC binary-compatibility cache ID."""
    revision = _metadata_string(metadata, "source_revision")
    declared = _metadata_string(metadata, "backend_cache_id")
    adapter = _load_adapter(root)
    computed = adapter._policy_identity(revision)
    if declared != computed:
        raise RuntimeError(
            "TinyCC backend cache identity mismatch: "
            f"metadata={declared}, adapter={computed}"
        )
    return declared


def diagnostic_record(*, root: Path, metadata: dict[str, object]) -> dict[str, object]:
    """Return backend-owned diagnostics without exposing TinyCC policy to the selector."""
    policy = metadata.get("policy")
    if not isinstance(policy, dict):
        raise RuntimeError("TinyCC backend metadata does not contain policy")
    return {
        "adapter": "tinycc-direct-cffi",
        "source_revision": _metadata_string(metadata, "source_revision"),
        "backend_cache_id": backend_cache_id(root=root, metadata=metadata),
        "tcc_version": metadata.get("tcc_version"),
        "policy": policy,
    }


def _discover_config(
    *,
    root: Path,
    metadata: dict[str, object],
    diagnostics_dir: Path,
    expected_cache_id: str,
):
    root = root.resolve()
    diagnostics_dir = diagnostics_dir.resolve()
    adapter = _load_adapter(root)
    declared_cache_id = backend_cache_id(root=root, metadata=metadata)
    if declared_cache_id != expected_cache_id:
        raise RuntimeError(
            "TinyCC selected cache identity changed after runtime discovery: "
            f"selected={expected_cache_id}, backend={declared_cache_id}"
        )
    revision = _metadata_string(metadata, "source_revision")
    config = adapter.TinyCCConfig.discover(
        root=root,
        python_def=root / "python3.def",
        diagnostics_dir=diagnostics_dir,
        revision=revision,
    )
    if config.backend_cache_id != declared_cache_id:
        raise RuntimeError(
            "TinyCC runtime configuration cache identity mismatch: "
            f"metadata={declared_cache_id}, config={config.backend_cache_id}"
        )
    return adapter, config


@contextlib.contextmanager
def activate(
    *,
    root: Path,
    metadata: dict[str, object],
    diagnostics_dir: Path,
    expected_cache_id: str,
) -> Iterator[object]:
    """Activate the qualified TinyCC adapter behind a backend-owned interface."""
    adapter, config = _discover_config(
        root=root,
        metadata=metadata,
        diagnostics_dir=diagnostics_dir,
        expected_cache_id=expected_cache_id,
    )
    with adapter.activate(config):
        yield config


def _read_metadata(root: Path) -> dict[str, object]:
    path = root.resolve() / "backend-metadata.json"
    if not path.is_file():
        raise RuntimeError(f"TinyCC backend metadata is missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid TinyCC backend metadata object: {path}")
    return data


def _self_test(root: Path) -> None:
    root = root.resolve()
    metadata = _read_metadata(root)
    cache_id = backend_cache_id(root=root, metadata=metadata)
    record = diagnostic_record(root=root, metadata=metadata)
    if record["backend_cache_id"] != cache_id:
        raise AssertionError("TinyCC runtime diagnostics cache identity mismatch")
    with tempfile.TemporaryDirectory(prefix="fenics-jit-tinycc-runtime-") as temp_dir:
        diagnostics = Path(temp_dir)
        with activate(
            root=root,
            metadata=metadata,
            diagnostics_dir=diagnostics,
            expected_cache_id=cache_id,
        ) as config:
            if config.backend_cache_id != cache_id:
                raise AssertionError("TinyCC runtime activation cache identity mismatch")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    metadata = _read_metadata(args.backend_root)
    if args.self_test:
        _self_test(args.backend_root)
        print("TinyCC shared-runtime integration self-test passed")
        return
    print(
        json.dumps(
            diagnostic_record(root=args.backend_root, metadata=metadata),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
