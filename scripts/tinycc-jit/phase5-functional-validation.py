"""Phase 5 integrated TinyCC serial validation using the established FFCx corpus."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterator

import pefile

_REQUIRED_DLL_CHARACTERISTICS = 0x20 | 0x40 | 0x100
_ACTIVE_RUNTIME = None
_ACTIVE_CACHE_ROOT: Path | None = None


def _load_module(path: Path, name: str) -> ModuleType:
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


def _load_reference_validator() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "llvm-mingw-jit" / "phase5-functional-validation.py"
    if not path.is_file():
        raise RuntimeError(f"LLVM-MinGW Phase-5 functional validator is missing: {path}")
    return _load_module(path, "_tinycc_phase5_reference_validator")


def _load_selector() -> ModuleType:
    path = Path(sys.prefix) / "Library" / "fenics-jit" / "runtime" / "fenics_jit_selector.py"
    if not path.is_file():
        raise RuntimeError(f"installed shared JIT selector is missing: {path}")
    return _load_module(path, "_tinycc_phase5_selector")


def _runtime_record() -> dict[str, object]:
    if _ACTIVE_RUNTIME is None or _ACTIVE_CACHE_ROOT is None:
        raise RuntimeError("TinyCC Phase-5 runtime was not initialized")
    record = _ACTIVE_RUNTIME.diagnostic_record(_ACTIVE_CACHE_ROOT)
    expected_root = Path(sys.prefix).resolve() / "Library" / "fenics-jit" / "backends" / "tinycc"
    if record.get("selected_backend") != "tinycc":
        raise RuntimeError(f"shared selector did not select TinyCC: {record!r}")
    if Path(str(record.get("backend_root"))).resolve() != expected_root:
        raise RuntimeError(f"shared selector selected wrong TinyCC backend root: {record!r}")
    backend = record.get("backend")
    if not isinstance(backend, dict) or backend.get("adapter") != "tinycc-direct-cffi":
        raise RuntimeError(f"unexpected TinyCC backend diagnostics: {record!r}")
    if backend.get("crt_identity") != "msvcrt-owned-allocation-boundary-v1":
        raise RuntimeError(f"unexpected TinyCC CRT policy: {record!r}")
    return record


def _render_command(cmd: object) -> str:
    if isinstance(cmd, (list, tuple)):
        return subprocess.list2cmdline([str(part) for part in cmd])
    return str(cmd)


@contextlib.contextmanager
def _record_tinycc_runs(path: Path) -> Iterator[list[str]]:
    if _ACTIVE_RUNTIME is None or _ACTIVE_CACHE_ROOT is None:
        raise RuntimeError("TinyCC Phase-5 runtime was not initialized")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    calls: list[str] = []
    original_run = subprocess.run

    def logged(cmd, *args, **kwargs):  # noqa: ANN001
        rendered = _render_command(cmd)
        calls.append(rendered)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(rendered + "\n")
        return original_run(cmd, *args, **kwargs)

    diagnostics = path.parent / (path.stem + "-runtime")
    with _ACTIVE_RUNTIME.activate(
        cache_root=_ACTIVE_CACHE_ROOT,
        diagnostics_dir=diagnostics,
        verbose=True,
    ):
        subprocess.run = logged
        try:
            yield calls
        finally:
            subprocess.run = original_run


def _assert_tinycc_commands(
    calls: list[str],
    record: dict[str, object],
    *,
    require_compile: bool,
) -> None:
    del record
    tcc_calls = [call for call in calls if re.search(r"(?i)(?:^|[\\/\s\"])(?:tcc\.exe)(?:$|[\s\"])", call)]
    if require_compile and not tcc_calls:
        raise RuntimeError("fresh JIT did not invoke packaged TinyCC")
    if not require_compile and tcc_calls:
        raise RuntimeError("cache reload unexpectedly invoked TinyCC: " + "\n".join(tcc_calls))

    for call in tcc_calls:
        lowered = call.lower()
        for forbidden in ("cl.exe", "link.exe", "clang", "gcc", "microsoft visual studio", "windows kits"):
            if forbidden in lowered:
                raise RuntimeError(f"host/alternate compiler input leaked into TinyCC command: {forbidden}: {call}")
        if re.search(r"(?i)python3(?:12|13|14|15)(?:_d)?\.(?:lib|dll)", call):
            raise RuntimeError(f"versioned Python link input reached TinyCC: {call}")
        for required in (
            "-mms-bitfields",
            "-Wl,-dynamicbase",
            "-Wl,-high-entropy-va",
            "-Wl,-nxcompat",
            "-D__MINGW32__=1",
            "-DMS_WIN64=1",
            "-D__STDC_NO_COMPLEX__=1",
            "python3.def",
        ):
            if required.lower() not in lowered:
                raise RuntimeError(f"TinyCC command missing required policy input {required}: {call}")


def _inspect_tinycc_pyds(cache_dirs: list[Path], diagnostics: Path) -> list[Path]:
    pyds = sorted({path.resolve() for cache_dir in cache_dirs for path in cache_dir.rglob("*.pyd")})
    if not pyds:
        raise RuntimeError("functional JIT validation produced no .pyd modules")

    report: list[dict[str, object]] = []
    unexpected_runtime = re.compile(
        r"(?i)^(?:python3\d{2}t?(?:_d)?\.dll|libgcc_s.*\.dll|libstdc\+\+.*\.dll|"
        r"libwinpthread.*\.dll|libclang_rt.*\.dll|clang_rt.*\.dll|libomp.*\.dll|cygwin1\.dll)$"
    )
    for pyd in pyds:
        pe = pefile.PE(str(pyd), fast_load=False)
        try:
            imports = sorted(
                entry.dll.decode("ascii", errors="replace").lower()
                for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
            )
            chars = int(pe.OPTIONAL_HEADER.DllCharacteristics)
            sections = {
                section.Name.rstrip(b"\0").decode("ascii", errors="replace"): int(section.SizeOfRawData)
                for section in pe.sections
            }
        finally:
            pe.close()

        if "python3.dll" not in imports:
            raise RuntimeError(f"Stable-ABI python3.dll import missing from {pyd}: {imports}")
        bad = [name for name in imports if unexpected_runtime.match(name)]
        if bad:
            raise RuntimeError(f"unexpected compiler/version runtime imports in {pyd}: {bad}")
        if (chars & _REQUIRED_DLL_CHARACTERISTICS) != _REQUIRED_DLL_CHARACTERISTICS:
            raise RuntimeError(f"required TinyCC PE mitigation bits missing from {pyd}: 0x{chars:x}")
        if not sections.get(".reloc") or not sections.get(".pdata"):
            raise RuntimeError(
                f"TinyCC PE relocation/unwind metadata missing from {pyd}: "
                f"reloc={sections.get('.reloc', 0)}, pdata={sections.get('.pdata', 0)}"
            )
        report.append(
            {
                "path": str(pyd),
                "imports": imports,
                "dll_characteristics": chars,
                "reloc_size": sections[".reloc"],
                "pdata_size": sections[".pdata"],
            }
        )

    diagnostics.mkdir(parents=True, exist_ok=True)
    (diagnostics / "tinycc-pyd-pe.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return pyds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--diagnostics-dir", type=Path, required=True)
    args = parser.parse_args()

    global _ACTIVE_RUNTIME, _ACTIVE_CACHE_ROOT

    os.environ["FENICS_JIT_COMPILER"] = "tinycc"
    selector = _load_selector()
    runtime = selector.discover_runtime()
    if runtime.selected_backend != "tinycc":
        raise RuntimeError(f"FENICS_JIT_COMPILER=tinycc selected {runtime.selected_backend!r}")

    base_cache = args.cache_dir.resolve()
    diagnostics = args.diagnostics_dir.resolve()
    physical_cache = runtime.cache_root(base_cache)
    _ACTIVE_RUNTIME = runtime
    _ACTIVE_CACHE_ROOT = physical_cache

    validator = _load_reference_validator()
    validator._runtime_record = _runtime_record
    validator._record_check_calls = _record_tinycc_runs
    validator._assert_compiler_commands = _assert_tinycc_commands
    validator._inspect_pyds = _inspect_tinycc_pyds

    validator._serial_validation(physical_cache, diagnostics)
    summary_path = diagnostics / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["selected_backend"] = runtime.selected_backend
    summary["backend_cache_id"] = runtime.backend_cache_id
    summary["backend_root"] = str(runtime.backend_root.resolve())
    summary["physical_cache_root"] = str(physical_cache)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("TinyCC Phase 5 integrated serial functional validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
