"""Phase-2 contract tests for the owned TinyCC CFFI adapter."""

from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
from pathlib import Path

from cffi import _shimmed_dist_utils as _dist

from tinycc_adapter import (
    ADAPTER_SCHEMA_VERSION,
    EXTERNAL_CONFIG_POLICY_VERSION,
    TinyCCBuildExt,
    TinyCCConfig,
    _reject_path,
    _translate_extra_args,
    activate,
)


def _expect_raises(callable_obj, contains: str) -> None:
    try:
        callable_obj()
    except RuntimeError as exc:
        if contains.lower() not in str(exc).lower():
            raise AssertionError(f"expected error containing {contains!r}, got {exc!r}") from exc
    else:
        raise AssertionError(f"expected RuntimeError containing {contains!r}")


def _make_config(root: Path, revision: str, diagnostics: Path) -> TinyCCConfig:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tcc.exe").write_bytes(b"phase2-contract")
    python_def = root / "python3.def"
    python_def.write_text("LIBRARY python3.dll\nEXPORTS\n", encoding="ascii")
    return TinyCCConfig.discover(
        root=root,
        python_def=python_def,
        diagnostics_dir=diagnostics,
        revision=revision,
    )


def _config_and_identity_test(base: Path) -> dict[str, str]:
    config = _make_config(
        base / "toolchain root with spaces",
        "0fb54300b56512754221d80adda85ddb9815bceb",
        base / "diagnostics with spaces",
    )
    same = TinyCCConfig.discover(
        root=config.root,
        python_def=config.python_def,
        diagnostics_dir=base / "other diagnostics",
        revision=config.revision,
    )
    other = TinyCCConfig.discover(
        root=config.root,
        python_def=config.python_def,
        diagnostics_dir=base / "third diagnostics",
        revision="1fb54300b56512754221d80adda85ddb9815bceb",
    )
    assert config.backend_cache_id == same.backend_cache_id
    assert config.backend_cache_id != other.backend_cache_id
    assert ADAPTER_SCHEMA_VERSION in config.backend_cache_id
    assert EXTERNAL_CONFIG_POLICY_VERSION in config.backend_cache_id
    assert " " in str(config.root)
    return config.policy_metadata()


def _interception_and_restoration_test(config: TinyCCConfig) -> None:
    original = _dist.Distribution
    with activate(config):
        active = _dist.Distribution
        assert active is not original
        dist = active({"name": "phase2-contract"})
        assert dist.parse_config_files() == []
        assert dist.get_command_class("build_ext") is TinyCCBuildExt
        with activate(config):
            assert _dist.Distribution is active
    assert _dist.Distribution is original

    try:
        with activate(config):
            raise ValueError("intentional restoration probe")
    except ValueError:
        pass
    assert _dist.Distribution is original


def _conflicting_nested_test(base: Path, config: TinyCCConfig) -> None:
    other = _make_config(
        base / "other toolchain",
        "0fb54300b56512754221d80adda85ddb9815bcec",
        base / "other backend diagnostics",
    )
    original = _dist.Distribution
    with activate(config):
        _expect_raises(lambda: _enter_once(other), "Conflicting nested")
    assert _dist.Distribution is original


def _enter_once(config: TinyCCConfig) -> None:
    with activate(config):
        pass


def _thread_serialization_test(config: TinyCCConfig) -> None:
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    failures: list[str] = []

    def first() -> None:
        try:
            with activate(config):
                first_entered.set()
                if not release_first.wait(timeout=10):
                    raise RuntimeError("thread serialization release timeout")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"first: {exc!r}")

    def second() -> None:
        try:
            if not first_entered.wait(timeout=10):
                raise RuntimeError("first activation did not start")
            with activate(config):
                second_entered.set()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"second: {exc!r}")

    t1 = threading.Thread(target=first, name="tinycc-contract-owner")
    t2 = threading.Thread(target=second, name="tinycc-contract-waiter")
    t1.start()
    t2.start()
    if not first_entered.wait(timeout=10):
        raise AssertionError("first activation did not enter")
    time.sleep(0.25)
    assert not second_entered.is_set(), "second thread interleaved process-global activation"
    release_first.set()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not t1.is_alive() and not t2.is_alive()
    if failures:
        raise AssertionError("; ".join(failures))
    assert second_entered.is_set()


def _rejection_contract_test() -> None:
    assert _translate_extra_args(["-O2", "-std:c17", "-DVALUE=1"]) == ["-O2", "-DVALUE=1"]
    _expect_raises(lambda: _translate_extra_args(["-Wl,--version-script=bad"]), "does not support")
    _expect_raises(lambda: _reject_path("python312.lib", what="library"), "rejects library input")
    _expect_raises(lambda: _reject_path("foreign.obj", what="extra object"), "rejects extra object input")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostics-dir", type=Path, required=True)
    args = parser.parse_args()
    diagnostics = args.diagnostics_dir.resolve()
    diagnostics.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tinycc phase2 contract ") as temporary:
        base = Path(temporary)
        config = _make_config(
            base / "toolchain root with spaces",
            "0fb54300b56512754221d80adda85ddb9815bceb",
            diagnostics,
        )
        metadata = _config_and_identity_test(base)
        _interception_and_restoration_test(config)
        _conflicting_nested_test(base, config)
        _thread_serialization_test(config)
        _rejection_contract_test()

    result = {
        "status": "pass",
        "adapter_schema": ADAPTER_SCHEMA_VERSION,
        "external_config_policy": EXTERNAL_CONFIG_POLICY_VERSION,
        "policy": metadata,
    }
    (diagnostics / "phase2-contract.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
