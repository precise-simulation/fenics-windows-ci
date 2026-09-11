"""Phase-1 TinyCC compatibility proof for CFFI/FFCx on Windows."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path

import pefile
from cffi import FFI

from tinycc_adapter import TinyCCConfig, activate

DEV_REVISION = "0fb54300b56512754221d80adda85ddb9815bceb"
_REQUIRED_DLL_CHARACTERISTICS = {
    "dynamic_base": 0x40,
    "high_entropy_va": 0x20,
    "nx_compat": 0x100,
}
_FORBIDDEN_COMMAND_TOKENS = (
    "cl.exe",
    "link.exe",
    "clang",
    "gcc",
    "vswhere",
    "microsoft visual studio",
    "windows kits",
)


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print("+", subprocess.list2cmdline(command))
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)


def _find_python3_dll(prefix: Path) -> Path:
    preferred = [prefix / "python3.dll", prefix / "DLLs" / "python3.dll"]
    for path in preferred:
        if path.is_file():
            return path.resolve()
    matches = sorted(prefix.rglob("python3.dll"), key=lambda path: (len(path.parts), str(path).lower()))
    if not matches:
        raise RuntimeError(f"python3.dll not found below {prefix}")
    return matches[0].resolve()


def _generate_python_def(tcc: Path, root: Path, python_dll: Path, output: Path) -> list[str]:
    command = [str(tcc), "-B" + str(root), "-impdef", str(python_dll), "-o", str(output)]
    _run(command, cwd=output.parent)
    if not output.is_file():
        raise RuntimeError(f"TinyCC failed to generate Stable-ABI definition file: {output}")
    text = output.read_text(encoding="utf-8", errors="replace").lower()
    if "exports" not in text:
        raise RuntimeError("Generated python3.def has no EXPORTS section")
    return command


def _compiler_builtin_model(tcc: Path, root: Path, diagnostics: Path) -> dict[str, int]:
    source = diagnostics / "tinycc-builtin-model.c"
    executable = diagnostics / "tinycc-builtin-model.exe"
    source.write_text(
        r'''#include <stdio.h>
#include <stddef.h>
#ifdef _WIN32
# define V_WIN32 1
#else
# define V_WIN32 0
#endif
#ifdef _WIN64
# define V_WIN64 1
#else
# define V_WIN64 0
#endif
#ifdef _MSC_VER
# define V_MSC 1
#else
# define V_MSC 0
#endif
#ifdef __MINGW32__
# define V_MINGW 1
#else
# define V_MINGW 0
#endif
#ifdef _M_X64
# define V_M_X64 1
#else
# define V_M_X64 0
#endif
#ifdef _M_AMD64
# define V_M_AMD64 1
#else
# define V_M_AMD64 0
#endif
int main(void) {
  printf("_WIN32=%d\n", V_WIN32);
  printf("_WIN64=%d\n", V_WIN64);
  printf("_MSC_VER=%d\n", V_MSC);
  printf("__MINGW32__=%d\n", V_MINGW);
  printf("_M_X64=%d\n", V_M_X64);
  printf("_M_AMD64=%d\n", V_M_AMD64);
  printf("sizeof_void_p=%u\n", (unsigned)sizeof(void *));
  printf("sizeof_size_t=%u\n", (unsigned)sizeof(size_t));
  printf("sizeof_long_double=%u\n", (unsigned)sizeof(long double));
  printf("alignof_long_double=%u\n", (unsigned)_Alignof(long double));
  return 0;
}
''',
        encoding="ascii",
    )
    _run([str(tcc), "-B" + str(root), str(source), "-o", str(executable)], cwd=diagnostics)
    result = _run([str(executable)], cwd=diagnostics)
    values: dict[str, int] = {}
    for line in result.stdout.splitlines():
        key, value = line.strip().split("=", 1)
        values[key] = int(value)
    (diagnostics / "compiler-builtin-model.json").write_text(
        json.dumps(values, indent=2, sort_keys=True), encoding="utf-8"
    )
    if values.get("_WIN32") != 1 or values.get("_WIN64") != 1:
        raise RuntimeError(f"TinyCC is not reporting an x86-64 Windows target: {values}")
    if values.get("_MSC_VER") != 0:
        raise RuntimeError("TinyCC unexpectedly defines _MSC_VER before compatibility definitions")
    if values.get("sizeof_void_p") != 8 or values.get("sizeof_size_t") != 8:
        raise RuntimeError(f"TinyCC built-in x64 data model is not 64-bit: {values}")
    return values


def _load_extension(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load extension {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inspect_pe(path: Path) -> dict[str, object]:
    pe = pefile.PE(str(path), fast_load=False)
    chars = int(pe.OPTIONAL_HEADER.DllCharacteristics)
    imports: list[str] = []
    if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
        imports = sorted(entry.dll.decode("ascii", errors="replace").lower() for entry in pe.DIRECTORY_ENTRY_IMPORT)
    reloc = pe.OPTIONAL_HEADER.DATA_DIRECTORY[5]
    pdata = next(
        (
            section
            for section in pe.sections
            if section.Name.rstrip(b"\0") == b".pdata" and int(section.SizeOfRawData) > 0
        ),
        None,
    )
    result: dict[str, object] = {
        "path": str(path),
        "dll_characteristics": hex(chars),
        "imports": imports,
        "relocation_virtual_address": int(reloc.VirtualAddress),
        "relocation_size": int(reloc.Size),
        "pdata_size": int(pdata.SizeOfRawData) if pdata is not None else 0,
    }
    for name, mask in _REQUIRED_DLL_CHARACTERISTICS.items():
        result[name] = bool(chars & mask)
    return result


def _assert_pe_contract(info: dict[str, object]) -> None:
    for name in _REQUIRED_DLL_CHARACTERISTICS:
        if info.get(name) is not True:
            raise RuntimeError(f"PE hardening bit {name} missing: {info}")
    if int(info["relocation_size"]) <= 0:
        raise RuntimeError(f"PE relocation directory is missing: {info}")
    if int(info["pdata_size"]) <= 0:
        raise RuntimeError(f"x64 .pdata/unwind metadata is missing: {info}")
    imports = {str(item).lower() for item in info["imports"]}  # type: ignore[index]
    if "python3.dll" not in imports:
        raise RuntimeError(f"Stable-ABI python3.dll import is missing: {sorted(imports)}")
    minor = sorted(item for item in imports if re.fullmatch(r"python3(?:12|13|14|15)(?:_d)?\.dll", item))
    if minor:
        raise RuntimeError(f"Versioned Python DLL imported by TinyCC extension: {minor}")


def _write_hostile_config(work: Path) -> None:
    poison = (
        "[build_ext]\n"
        "compiler = msvc\n"
        "include_dirs = C:\\\\poison\\\\Microsoft Visual Studio\\\\include\n"
        "library_dirs = C:\\\\poison\\\\Windows Kits\\\\lib\n"
    )
    (work / "setup.cfg").write_text(poison, encoding="utf-8")
    home = work / "hostile-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "pydistutils.cfg").write_text(poison, encoding="utf-8")
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)


def _minimal_cffi(config: TinyCCConfig, work: Path, diagnostics: Path) -> tuple[Path, dict[str, int]]:
    ffi = FFI()
    ffi.cdef(
        """
        int add_ints(int a, int b);
        int probe_win64(void);
        int probe_ms_win64(void);
        int probe_sizeof_void_p(void);
        int probe_sizeof_size_t(void);
        int probe_sizeof_py_ssize_t(void);
        int probe_sizeof_long_double(void);
        int probe_alignof_long_double(void);
        int probe_bitfield_size(void);
        unsigned int probe_bitfield_raw(void);
        int probe_packed_size(void);
        int probe_packed_offset(void);
        int probe_alloc_roundtrip(int n);
        """
    )
    ffi.set_source(
        "_tinycc_phase1_probe",
        r'''
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <Python.h>

int add_ints(int a, int b) { return a + b; }
int probe_win64(void) {
#ifdef _WIN64
    return 1;
#else
    return 0;
#endif
}
int probe_ms_win64(void) {
#ifdef MS_WIN64
    return 1;
#else
    return 0;
#endif
}
int probe_sizeof_void_p(void) { return (int)sizeof(void *); }
int probe_sizeof_size_t(void) { return (int)sizeof(size_t); }
int probe_sizeof_py_ssize_t(void) { return (int)sizeof(Py_ssize_t); }
int probe_sizeof_long_double(void) { return (int)sizeof(long double); }
int probe_alignof_long_double(void) { return (int)_Alignof(long double); }

struct phase1_bits { unsigned int a:3; unsigned int b:5; unsigned int c:8; };
union phase1_bits_union { struct phase1_bits bits; unsigned int raw; };
int probe_bitfield_size(void) { return (int)sizeof(struct phase1_bits); }
unsigned int probe_bitfield_raw(void) {
    union phase1_bits_union value = {0};
    value.bits.a = 5;
    value.bits.b = 17;
    value.bits.c = 0xab;
    return value.raw;
}
#pragma pack(push, 1)
struct phase1_packed { char a; uint64_t b; };
#pragma pack(pop)
int probe_packed_size(void) { return (int)sizeof(struct phase1_packed); }
int probe_packed_offset(void) { return (int)offsetof(struct phase1_packed, b); }
int probe_alloc_roundtrip(int n) {
    unsigned char *buffer = (unsigned char *)malloc((size_t)n);
    int sum = 0;
    int i;
    if (!buffer) return -1;
    for (i = 0; i < n; ++i) { buffer[i] = (unsigned char)(i & 0xff); sum += buffer[i]; }
    free(buffer);
    return sum;
}
''',
        extra_compile_args=["-std:c17", "-O2"],
    )
    target = work / "minimal-cffi"
    target.mkdir(parents=True, exist_ok=True)
    with activate(config):
        output = Path(ffi.compile(tmpdir=str(target), verbose=True)).resolve()
    module = _load_extension("_tinycc_phase1_probe", output)
    lib = module.lib
    if lib.add_ints(19, 23) != 42:
        raise RuntimeError("TinyCC CFFI probe returned the wrong result")
    probes = {
        "_WIN64": int(lib.probe_win64()),
        "MS_WIN64": int(lib.probe_ms_win64()),
        "sizeof_void_p": int(lib.probe_sizeof_void_p()),
        "sizeof_size_t": int(lib.probe_sizeof_size_t()),
        "sizeof_Py_ssize_t": int(lib.probe_sizeof_py_ssize_t()),
        "sizeof_long_double": int(lib.probe_sizeof_long_double()),
        "alignof_long_double": int(lib.probe_alignof_long_double()),
        "bitfield_size": int(lib.probe_bitfield_size()),
        "bitfield_raw": int(lib.probe_bitfield_raw()),
        "packed_size": int(lib.probe_packed_size()),
        "packed_offset": int(lib.probe_packed_offset()),
    }
    expected = {
        "_WIN64": 1,
        "MS_WIN64": 1,
        "sizeof_void_p": 8,
        "sizeof_size_t": 8,
        "sizeof_Py_ssize_t": 8,
        "sizeof_long_double": 16,
        "alignof_long_double": 16,
        "bitfield_size": 4,
        "bitfield_raw": 0xAB8D,
        "packed_size": 9,
        "packed_offset": 1,
    }
    mismatches = {key: (probes.get(key), value) for key, value in expected.items() if probes.get(key) != value}
    if mismatches:
        raise RuntimeError(f"TinyCC ABI/CPython target-model probe mismatch: {mismatches}")
    for n in (1, 17, 257, 4096):
        expected_sum = sum(i & 0xFF for i in range(n))
        actual_sum = int(lib.probe_alloc_roundtrip(n))
        if actual_sum != expected_sum:
            raise RuntimeError(f"TinyCC internal CRT allocation stress failed for n={n}: {actual_sum} != {expected_sum}")
    (diagnostics / "abi-probes.json").write_text(json.dumps(probes, indent=2, sort_keys=True), encoding="utf-8")
    return output, probes


def _negative_inputs(config: TinyCCConfig, work: Path, diagnostics: Path) -> dict[str, str]:
    results: dict[str, str] = {}
    cases = [
        ("foreign-object", {"extra_objects": [str(work / "poison.obj")]}),
        ("versioned-python-library", {"libraries": ["python312"]}),
    ]
    for name, kwargs in cases:
        ffi = FFI()
        ffi.cdef("int negative_probe(void);")
        ffi.set_source(f"_tinycc_negative_{name.replace('-', '_')}", "int negative_probe(void) { return 1; }", **kwargs)
        try:
            with activate(config):
                ffi.compile(tmpdir=str(work / name), verbose=True)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            results[name] = message
            if "reject" not in message.lower():
                raise RuntimeError(f"Negative input failed for an unexpected reason: {name}: {message}") from exc
        else:
            raise RuntimeError(f"TinyCC adapter unexpectedly accepted negative input: {name}")
    (diagnostics / "negative-inputs.json").write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    return results


def _run_poisson(config: TinyCCConfig, work: Path, poisson_script: Path) -> list[Path]:
    cache_root = work / "ffcx-cache-root"
    if cache_root.exists():
        import shutil

        shutil.rmtree(cache_root)
    cache_root.mkdir(parents=True)
    os.environ["XDG_CACHE_HOME"] = str(cache_root)

    with activate(config):
        import cffi
        import dolfinx
        import ffcx
        import setuptools

        version_text = "\n".join(
            [
                f"python={sys.version}",
                f"dolfinx={dolfinx.__version__}",
                f"ffcx={ffcx.__version__}",
                f"cffi={cffi.__version__}",
                f"setuptools={setuptools.__version__}",
            ]
        ) + "\n"
        (config.diagnostics_dir / "versions.txt").write_text(version_text, encoding="utf-8")
        runpy.run_path(str(poisson_script), run_name="__main__")

    pyds = sorted(cache_root.rglob("*.pyd"))
    if not pyds:
        raise RuntimeError(f"Fresh FFCx Poisson solve produced no .pyd files below {cache_root}")
    return pyds


def _check_command_hermeticity(command_log: Path) -> None:
    text = command_log.read_text(encoding="utf-8", errors="replace").lower()
    hits = [token for token in _FORBIDDEN_COMMAND_TOKENS if token in text]
    if hits:
        raise RuntimeError(f"Forbidden compiler/development inputs found in command log: {hits}")
    if re.search(r"python3(?:12|13|14|15)(?:_d)?\.(?:lib|dll)", text):
        raise RuntimeError("Versioned Python library found in TinyCC command log")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tinycc-root", required=True)
    parser.add_argument("--python-prefix", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--diagnostics-dir", required=True)
    parser.add_argument("--poisson-script", required=True)
    args = parser.parse_args()

    if sys.platform != "win32":
        raise RuntimeError("TinyCC Phase-1 proof is Windows-only")

    tinycc_root = Path(args.tinycc_root).resolve()
    python_prefix = Path(args.python_prefix).resolve()
    work = Path(args.work_dir).resolve()
    diagnostics = Path(args.diagnostics_dir).resolve()
    poisson_script = Path(args.poisson_script).resolve()
    work.mkdir(parents=True, exist_ok=True)
    diagnostics.mkdir(parents=True, exist_ok=True)
    if not poisson_script.is_file():
        raise RuntimeError(f"Poisson script not found: {poisson_script}")

    metadata_path = tinycc_root / "fenics-tinycc-bootstrap.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    revision = str(metadata.get("revision", ""))
    if revision != DEV_REVISION:
        raise RuntimeError(f"Unexpected TinyCC revision: {revision!r}; expected {DEV_REVISION}")

    tcc = tinycc_root / "tcc.exe"
    python_dll = _find_python3_dll(python_prefix)
    python_def = diagnostics / "python3.def"
    def_command = _generate_python_def(tcc, tinycc_root, python_dll, python_def)
    builtin_model = _compiler_builtin_model(tcc, tinycc_root, diagnostics)
    _write_hostile_config(work)

    config = TinyCCConfig.discover(
        root=tinycc_root,
        python_def=python_def,
        diagnostics_dir=diagnostics,
        revision=revision,
    )
    (diagnostics / "backend-cache-id.txt").write_text(config.backend_cache_id + "\n", encoding="utf-8")

    previous_cwd = Path.cwd()
    try:
        os.chdir(work)
        minimal_pyd, abi_probes = _minimal_cffi(config, work, diagnostics)
        negative_inputs = _negative_inputs(config, work, diagnostics)
        ffcx_pyds = _run_poisson(config, work, poisson_script)
    finally:
        os.chdir(previous_cwd)

    pe_results: list[dict[str, object]] = []
    for path in [minimal_pyd, *ffcx_pyds]:
        info = _inspect_pe(path)
        _assert_pe_contract(info)
        pe_results.append(info)
    (diagnostics / "pe-inspection.json").write_text(json.dumps(pe_results, indent=2, sort_keys=True), encoding="utf-8")

    import ffcx.codegeneration.jit as ffcx_jit

    ufcx_long_double = "long double" in ffcx_jit.ufcx_h
    if ufcx_long_double:
        raise RuntimeError("UFCx public ABI unexpectedly contains long double")

    command_log = diagnostics / "compiler-commands.jsonl"
    if not command_log.is_file():
        raise RuntimeError("TinyCC adapter did not record compiler commands")
    _check_command_hermeticity(command_log)

    imports = sorted({dll for item in pe_results for dll in item["imports"]})  # type: ignore[index]
    crt_model = "msvcrt" if "msvcrt.dll" in imports else "other"
    summary = {
        "status": "passed",
        "tinycc_revision": revision,
        "tinycc_version": metadata.get("version"),
        "python": sys.version,
        "python3_dll": str(python_dll),
        "python_def_command": def_command,
        "backend_cache_id": config.backend_cache_id,
        "compiler_builtin_model": builtin_model,
        "compatibility_definitions": ["__MINGW32__=1", "__STDC_NO_COMPLEX__=1", "-mms-bitfields"],
        "abi_probes": abi_probes,
        "long_double_boundary": "known TinyCC 16/16 representation; no long double in UFCx public ABI",
        "crt_model": crt_model,
        "mixed_crt_policy": "TinyCC-owned malloc/free remains internal; Python/CFFI ownership uses Python APIs; allocation stress passed",
        "system_library_policy": "TinyCC packaged roots plus normal Windows system DLL resolution; no host SDK/development library directories",
        "external_config_policy": "suppressed by owned CFFI Distribution interception",
        "negative_inputs": negative_inputs,
        "minimal_pyd": str(minimal_pyd),
        "ffcx_pyds": [str(path) for path in ffcx_pyds],
        "pe_imports": imports,
        "ufcx_contains_long_double": ufcx_long_double,
    }
    (diagnostics / "phase1-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
