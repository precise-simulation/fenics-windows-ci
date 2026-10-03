"""Prepare and verify the private micro-Clang Phase-1 JIT contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pefile

_REQUIRED_DLL_CHARACTERISTICS = {
    "dynamic_base": 0x40,
    "high_entropy_va": 0x20,
    "nx_compat": 0x100,
}


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print("+", subprocess.list2cmdline(command))
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)


def python3_dll(prefix: Path) -> Path:
    candidates = [
        prefix / "python3.dll",
        prefix / "DLLs" / "python3.dll",
        prefix / "Library" / "bin" / "python3.dll",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(f"python3.dll not found below {prefix}")


def generate_python_imports(root: Path, prefix: Path) -> dict[str, object]:
    readobj = root / "bin" / "llvm-readobj.exe"
    dlltool = root / "bin" / "llvm-dlltool.exe"
    for tool in (readobj, dlltool):
        if not tool.is_file():
            raise RuntimeError(f"required micro-Clang tool missing: {tool}")

    dll = python3_dll(prefix)
    exports = run([str(readobj), "--coff-exports", str(dll)]).stdout
    names = sorted(
        {
            match.group(1).strip()
            for line in exports.splitlines()
            if (match := re.match(r"^\s*Name:\s+(.+?)\s*$", line))
        }
    )
    if len(names) < 10:
        raise RuntimeError(f"unexpectedly few python3.dll exports: {len(names)}")

    libdir = root / "lib" / "python"
    libdir.mkdir(parents=True, exist_ok=True)
    def_path = libdir / "python3.def"
    def_path.write_text(
        "LIBRARY python3.dll\nEXPORTS\n" + "\n".join(names) + "\n",
        encoding="ascii",
    )

    tag = f"{sys.version_info.major}{sys.version_info.minor}"
    outputs: list[str] = []
    for name in ("libpython3.a", f"libpython{tag}.a"):
        output = libdir / name
        run(
            [
                str(dlltool),
                "-m",
                "i386:x86-64",
                "-d",
                str(def_path),
                "-l",
                str(output),
                "-D",
                "python3.dll",
            ]
        )
        if not output.is_file():
            raise RuntimeError(f"failed to generate Python import library: {output}")
        outputs.append(str(output))

    return {
        "python_dll": str(dll),
        "python_export_count": len(names),
        "python_import_libraries": outputs,
    }


def parse_driver(text: str) -> dict[str, object]:
    cpu = None
    match = re.search(r'"-target-cpu"\s+"([^"]+)"', text)
    if match:
        cpu = match.group(1)
    features = re.findall(r'"-target-feature"\s+"([^"]+)"', text)
    return {"target_cpu": cpu, "target_features": features}


def abi_probe(root: Path, output: Path) -> dict[str, int]:
    source = output / "abi-sentinel.c"
    executable = output / "abi-sentinel.exe"
    source.write_text(
        r'''#include <stddef.h>
#include <stdio.h>

struct bitfield_probe {
    char prefix;
    unsigned int a : 4;
    unsigned int b : 4;
    unsigned short tail;
};

int main(void) {
    printf(
        "{\"sizeof_long_double\":%zu,"
        "\"alignof_long_double\":%zu,"
        "\"sizeof_bitfield_probe\":%zu,"
        "\"alignof_bitfield_probe\":%zu,"
        "\"offsetof_bitfield_tail\":%zu}\n",
        sizeof(long double),
        _Alignof(long double),
        sizeof(struct bitfield_probe),
        _Alignof(struct bitfield_probe),
        offsetof(struct bitfield_probe, tail)
    );
    return 0;
}
''',
        encoding="ascii",
    )
    clang = root / "bin" / "x86_64-w64-mingw32-clang.exe"
    run([str(clang), "-std=c17", "-O2", str(source), "-o", str(executable)])
    return json.loads(run([str(executable)]).stdout.strip())


def prepare(args: argparse.Namespace) -> None:
    root = Path(args.toolchain_root).resolve()
    prefix = Path(args.python_prefix).resolve()
    helper = Path(args.runtime_helper).resolve()
    reference_path = Path(args.reference_driver).resolve()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    if not helper.is_file():
        raise RuntimeError(f"qualified LLVM-MinGW runtime helper missing: {helper}")
    runtime_dir = root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    staged_helper = runtime_dir / "fenics_jit_runtime.py"
    shutil.copy2(helper, staged_helper)

    python_info = generate_python_imports(root, prefix)

    clang = root / "bin" / "x86_64-w64-mingw32-clang.exe"
    lld = root / "bin" / "ld.lld.exe"
    source = output / "driver-probe.c"
    source.write_text("int micro_clang_probe(void) { return 42; }\n", encoding="ascii")
    target = run([str(clang), "-dumpmachine"]).stdout.strip()
    version = run([str(clang), "--version"]).stdout.strip()
    lld_version = run([str(lld), "--version"]).stdout.strip()
    driver = run(
        [
            str(clang),
            "-###",
            "-O2",
            "-std=c17",
            "-shared",
            str(source),
            "-o",
            str(output / "driver-probe.dll"),
        ]
    ).stderr
    (output / "driver-defaults.txt").write_text(driver, encoding="utf-8")
    parsed = parse_driver(driver)
    abi = abi_probe(root, output)

    reference = json.loads(reference_path.read_text(encoding="utf-8-sig"))
    reference_target = str(reference["target"])
    if target.lower() not in {
        reference_target.lower(),
        "x86_64-w64-windows-gnu",
    }:
        raise RuntimeError(
            f"micro-Clang target differs from Stage-AW reference: {target!r} vs {reference_target!r}"
        )

    reference_abi = {key: int(value) for key, value in reference["abi"].items()}
    if abi != reference_abi:
        raise RuntimeError(f"ABI sentinel mismatch: micro={abi!r}, reference={reference_abi!r}")

    reference_cpu = reference.get("target_cpu")
    if parsed["target_cpu"] != reference_cpu:
        raise RuntimeError(
            "target CPU differs from Stage-AW reference: "
            f"micro={parsed['target_cpu']!r}, reference={reference_cpu!r}"
        )
    reference_features = list(reference.get("target_features") or [])
    if parsed["target_features"] != reference_features:
        raise RuntimeError(
            "target feature defaults differ from Stage-AW reference: "
            f"micro={parsed['target_features']!r}, reference={reference_features!r}"
        )

    # The target wrapper must preserve the qualified compiler-rt/libunwind/LLD
    # link policy. Clang materializes -unwindlib=libunwind in the linker command
    # as "-lunwind", so validate the emitted link token rather than the driver
    # option spelling. The -### shared-link probe is authoritative.
    lowered_driver = driver.lower()
    for required in ("ld.lld", "libclang_rt.builtins", '"-lunwind"'):
        if required not in lowered_driver:
            raise RuntimeError(f"qualified link policy missing {required!r} from micro-Clang -###")

    helper_sha = hashlib.sha256(staged_helper.read_bytes()).hexdigest()
    result = {
        "schema": "fenics-jit-micro-clang-phase1-contract-v1",
        "target": target,
        "clang_version": version,
        "lld_version": lld_version,
        "driver": parsed,
        "abi": abi,
        "reference_abi_match": True,
        "reference_target_defaults_match": True,
        "runtime_helper_sha256": helper_sha,
        "python": python_info,
        "toolchain_root": str(root),
    }
    (output / "phase1-contract.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def inspect_pe(path: Path) -> dict[str, object]:
    pe = pefile.PE(str(path), fast_load=False)
    chars = int(pe.OPTIONAL_HEADER.DllCharacteristics)
    imports: list[str] = []
    if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
        imports = sorted(
            entry.dll.decode("ascii", errors="replace").lower()
            for entry in pe.DIRECTORY_ENTRY_IMPORT
        )
    reloc = pe.OPTIONAL_HEADER.DATA_DIRECTORY[5]
    pdata = next(
        (
            section
            for section in pe.sections
            if section.Name.rstrip(b"\0") == b".pdata" and int(section.SizeOfRawData) > 0
        ),
        None,
    )
    info: dict[str, object] = {
        "path": str(path),
        "dll_characteristics": chars,
        "imports": imports,
        "relocation_virtual_address": int(reloc.VirtualAddress),
        "relocation_size": int(reloc.Size),
        "pdata_size": int(pdata.SizeOfRawData) if pdata is not None else 0,
    }
    for name, mask in _REQUIRED_DLL_CHARACTERISTICS.items():
        info[name] = bool(chars & mask)
    return info


def assert_pe(info: dict[str, object]) -> None:
    for name in _REQUIRED_DLL_CHARACTERISTICS:
        if info.get(name) is not True:
            raise RuntimeError(f"PE hardening bit {name} missing: {info}")
    if int(info["relocation_size"]) <= 0:
        raise RuntimeError(f"PE relocation directory missing: {info}")
    if int(info["pdata_size"]) <= 0:
        raise RuntimeError(f"x64 .pdata/unwind metadata missing: {info}")
    imports = {str(item).lower() for item in info["imports"]}  # type: ignore[index]
    if "python3.dll" not in imports:
        raise RuntimeError(f"Stable-ABI python3.dll import missing: {sorted(imports)}")
    minor = sorted(
        item
        for item in imports
        if re.fullmatch(r"python3(?:12|13|14|15)(?:_d)?\.dll", item)
    )
    if minor:
        raise RuntimeError(f"versioned Python DLL imported: {minor}")


def verify(args: argparse.Namespace) -> None:
    root = Path(args.toolchain_root).resolve()
    diagnostics = Path(args.diagnostics_dir).resolve()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    path_lists = [
        diagnostics / "minimal" / "pyd-path.txt",
        diagnostics / "poisson" / "pyd-paths.txt",
    ]
    pyds: list[Path] = []
    for listing in path_lists:
        if not listing.is_file():
            raise RuntimeError(f"JIT output listing missing: {listing}")
        for line in listing.read_text(encoding="utf-8").splitlines():
            path = Path(line.strip())
            if path.is_file():
                pyds.append(path.resolve())
    if not pyds:
        raise RuntimeError("no generated Phase-1 .pyd files found")

    pe_records = []
    for path in sorted(set(pyds)):
        info = inspect_pe(path)
        assert_pe(info)
        pe_records.append(info)

    command_paths = [
        diagnostics / "minimal" / "compiler-commands.txt",
        diagnostics / "poisson" / "compiler-commands.txt",
    ]
    forbidden = (
        "microsoft visual studio",
        "windows kits",
        "fenics-jit\\backends\\llvm-mingw",
        "fenics-jit/backends/llvm-mingw",
    )
    command_records = []
    expected_root = str(root).lower()
    for path in command_paths:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        if expected_root not in lowered:
            raise RuntimeError(f"compiler command log does not use micro-Clang root: {path}")
        hit = next((token for token in forbidden if token in lowered), None)
        if hit is not None:
            raise RuntimeError(f"forbidden ambient/reference compiler token {hit!r} in {path}")
        command_records.append({"path": str(path), "line_count": len(text.splitlines())})

    result = {
        "schema": "fenics-jit-micro-clang-phase1-verification-v1",
        "status": "pass",
        "python": sys.version,
        "toolchain_root": str(root),
        "generated_modules": pe_records,
        "compiler_command_logs": command_records,
        "normal_llvm_mingw_backend_used": False,
        "ambient_vs_sdk_used": False,
    }
    (output / "phase1-verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--toolchain-root", required=True)
    prepare_parser.add_argument("--python-prefix", required=True)
    prepare_parser.add_argument("--runtime-helper", required=True)
    prepare_parser.add_argument("--reference-driver", required=True)
    prepare_parser.add_argument("--output-dir", required=True)
    prepare_parser.set_defaults(func=prepare)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--toolchain-root", required=True)
    verify_parser.add_argument("--diagnostics-dir", required=True)
    verify_parser.add_argument("--output-dir", required=True)
    verify_parser.set_defaults(func=verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
