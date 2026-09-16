"""Record version-specific generated-C evidence for TinyCC Phase 5."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_BROAD_CASES = (
    "p2-poisson-module-1",
    "p2-poisson-module-2",
    "vector-linear-elasticity",
    "cell-facet-coefficients",
    "nonlinear-residual-jacobian-module-1",
    "nonlinear-residual-jacobian-module-2",
    "fem-expression",
)
_CACHE_CASES = ("fresh-cache-reload-proof",)
_REQUIRED_POLICY_INPUTS = (
    "-mms-bitfields",
    "-D__MINGW32__=1",
    "-DMS_WIN64=1",
    "-D__STDC_NO_COMPLEX__=1",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _normalized_source_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return _sha256_bytes(normalized.encode("utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise RuntimeError(f"missing TinyCC compiler record: {path}")
    records: list[dict[str, object]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RuntimeError(f"invalid record at {path}:{number}")
        records.append(value)
    return records


def _module_record(
    record: dict[str, object],
    *,
    case: str,
    command_record: Path,
    diagnostics: Path,
    cache_root: Path,
    sequence_index: int,
) -> dict[str, object]:
    command = record.get("command")
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        raise RuntimeError(f"invalid TinyCC command record for {case}: {record!r}")
    lowered = [part.lower() for part in command]
    for required in _REQUIRED_POLICY_INPUTS:
        if required.lower() not in lowered:
            raise RuntimeError(f"corpus command for {case} is missing {required}: {command!r}")
    if any(part.startswith("-std") or part.startswith("/std") for part in lowered):
        raise RuntimeError(f"corpus command for {case} unexpectedly overrides TinyCC default C11 mode: {command!r}")

    sources = [Path(part).resolve() for part in command if part.lower().endswith(".c")]
    if len(sources) != 1:
        raise RuntimeError(f"expected one generated C source for {case}, got {sources!r}")
    source = sources[0]
    if not source.is_file():
        raise RuntimeError(f"generated C source for {case} is missing: {source}")
    try:
        relative_source = source.relative_to(cache_root)
    except ValueError as exc:
        raise RuntimeError(f"generated C source escaped the TinyCC physical cache: {source}") from exc

    extension = record.get("extension")
    if not isinstance(extension, str) or not extension:
        raise RuntimeError(f"compiler record for {case} has no extension identity: {record!r}")
    policy = record.get("policy")
    if not isinstance(policy, dict):
        raise RuntimeError(f"compiler record for {case} has no policy metadata: {record!r}")

    return {
        "test_identity": case,
        "sequence_index": sequence_index,
        "logical_module": extension,
        "source_path": relative_source.as_posix(),
        "source_size": source.stat().st_size,
        "source_sha256": _sha256_file(source),
        "normalized_source_sha256": _normalized_source_sha256(source),
        "normalization": "utf8-newlines-lf-v1",
        "compile_result": "success",
        "compiler_command": command,
        "compiler_record": command_record.relative_to(diagnostics).as_posix(),
        "policy": policy,
    }


def _package_versions() -> dict[str, str]:
    import basix
    import cffi
    import dolfinx
    import ffcx
    import ufl

    return {
        "basix": str(basix.__version__),
        "cffi": str(cffi.__version__),
        "dolfinx": str(dolfinx.__version__),
        "ffcx": str(ffcx.__version__),
        "ufl": str(ufl.__version__),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostics-dir", type=Path, required=True)
    args = parser.parse_args()

    diagnostics = args.diagnostics_dir.resolve()
    summary_path = diagnostics / "summary.json"
    if not summary_path.is_file():
        raise RuntimeError(f"TinyCC Phase-5 summary is missing: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict) or summary.get("selected_backend") != "tinycc":
        raise RuntimeError(f"unexpected TinyCC Phase-5 summary: {summary!r}")

    cache_root = Path(str(summary["physical_cache_root"])).resolve()
    backend_root = Path(str(summary["backend_root"])).resolve()
    metadata_path = backend_root / "backend-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    if not isinstance(metadata, dict):
        raise RuntimeError(f"invalid TinyCC backend metadata: {metadata_path}")

    command_sets = (
        (
            diagnostics / "serial-compiler-commands-runtime" / "compiler-commands.jsonl",
            _BROAD_CASES,
        ),
        (
            diagnostics / "cache-first-commands-runtime" / "compiler-commands.jsonl",
            _CACHE_CASES,
        ),
    )
    modules: list[dict[str, object]] = []
    for command_path, cases in command_sets:
        records = _load_jsonl(command_path)
        if len(records) != len(cases):
            raise RuntimeError(
                f"generated-C corpus changed for {command_path.name}: "
                f"expected {len(cases)} modules, observed {len(records)}"
            )
        for index, (record, case) in enumerate(zip(records, cases, strict=True), start=len(modules)):
            modules.append(
                _module_record(
                    record,
                    case=case,
                    command_record=command_path,
                    diagnostics=diagnostics,
                    cache_root=cache_root,
                    sequence_index=index,
                )
            )

    observed_sources = {str(item["source_path"]) for item in modules}
    cache_sources = {
        path.resolve().relative_to(cache_root).as_posix()
        for path in cache_root.rglob("*.c")
    }
    if observed_sources != cache_sources:
        raise RuntimeError(
            "compiler records do not cover the complete generated-C cache: "
            f"recorded_only={sorted(observed_sources - cache_sources)!r}, "
            f"unrecorded={sorted(cache_sources - observed_sources)!r}"
        )

    scripts = Path(__file__).resolve().parent
    reference_validator = scripts.parent / "llvm-mingw-jit" / "phase5-functional-validation.py"
    tinycc_validator = scripts / "phase5-functional-validation.py"
    backend_policy = metadata.get("policy")
    if not isinstance(backend_policy, dict):
        raise RuntimeError("TinyCC backend metadata has no policy object")

    evidence = {
        "schema": 1,
        "kind": "tinycc-phase5-generated-c-observation",
        "status": "observed-not-yet-pinned",
        "python": {
            "version": sys.version,
            "major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        },
        "generator_versions": _package_versions(),
        "validation_inputs": {
            "reference_validator_sha256": _sha256_file(reference_validator),
            "tinycc_validator_sha256": _sha256_file(tinycc_validator),
        },
        "backend": {
            "cache_id": summary["backend_cache_id"],
            "source_revision": metadata.get("source_revision"),
            "tcc_version": metadata.get("tcc_version"),
            "local_build_patch": metadata.get("local_build_patch"),
            "upstream_build_script_sha256": metadata.get("upstream_build_script_sha256"),
            "patched_build_script_sha256": metadata.get("patched_build_script_sha256"),
            "adapter_sha256": metadata.get("adapter_sha256"),
            "runtime_integration_sha256": metadata.get("runtime_integration_sha256"),
            "policy": backend_policy,
        },
        "compile_policy": {
            "c_standard_mode": "tinycc-default-c11",
            "python_win64_compatibility_definitions": ["__MINGW32__=1", "MS_WIN64=1"],
            "packing_bitfield": "-mms-bitfields",
            "complex_policy": "__STDC_NO_COMPLEX__=1",
            "source_normalization": "utf8-newlines-lf-v1",
        },
        "compiler_output_capture": "stdout/stderr retained in the Actions job log; per-module capture is not yet part of this observation",
        "coverage": summary.get("coverage", []),
        "module_count": len(modules),
        "modules": modules,
    }
    output = diagnostics / "generated-corpus-observation.json"
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"TinyCC Phase 5 generated-C observation recorded: {len(modules)} modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
