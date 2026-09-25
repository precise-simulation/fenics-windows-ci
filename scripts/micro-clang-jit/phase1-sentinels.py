"""Compare source-built micro-Clang with the immutable Stage-AW driver/ABI control."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {subprocess.list2cmdline(cmd)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def canonical_target(value: str) -> str:
    return value.strip().lower().replace("-windows-gnu", "-mingw32")


def driver_defaults(compiler: Path, source: Path) -> dict[str, object]:
    result = run([str(compiler), "-###", "-c", str(source), "-o", os.devnull])
    text = result.stderr + "\n" + result.stdout
    triple = re.search(r'"-triple"\s+"([^"]+)"', text)
    cpu = re.search(r'"-target-cpu"\s+"([^"]+)"', text)
    features = re.findall(r'"-target-feature"\s+"([^"]+)"', text)
    return {
        "triple": canonical_target(triple.group(1)) if triple else None,
        "target_cpu": cpu.group(1) if cpu else None,
        "target_features": features,
        "raw": text,
    }


def abi_probe(compiler: Path, source: Path, output: Path) -> dict[str, int]:
    run([str(compiler), str(source), "-O0", "-o", str(output)])
    result = run([str(output)])
    values = json.loads(result.stdout)
    if not isinstance(values, dict):
        raise RuntimeError("ABI probe did not return an object")
    return {key: int(value) for key, value in values.items()}


def inspect_pe(readobj: Path, path: Path) -> str:
    result = run(
        [str(readobj), "--file-headers", "--sections", "--coff-imports", str(path)]
    )
    return result.stdout + result.stderr


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--micro-root", required=True)
    parser.add_argument("--reference-root", required=True)
    parser.add_argument("--diagnostics-dir", required=True)
    parser.add_argument("--require-space-path", action="store_true")
    args = parser.parse_args()

    micro = Path(args.micro_root).resolve()
    reference = Path(args.reference_root).resolve()
    diagnostics = Path(args.diagnostics_dir).resolve()
    diagnostics.mkdir(parents=True, exist_ok=True)

    if args.require_space_path and " " not in str(micro):
        raise RuntimeError("Phase-1 paths-with-spaces proof requires a spaced micro root")

    micro_cc = micro / "bin" / "x86_64-w64-mingw32-clang.exe"
    ref_cc = reference / "bin" / "x86_64-w64-mingw32-clang.exe"
    readobj = micro / "bin" / "llvm-readobj.exe"
    for path in (micro_cc, ref_cc, readobj):
        if not path.is_file():
            raise RuntimeError(f"required Phase-1 input missing: {path}")

    source = diagnostics / "empty.c"
    source.write_text("int micro_clang_empty(void) { return 0; }\n", encoding="utf-8")

    micro_target = run([str(micro_cc), "-dumpmachine"]).stdout.strip()
    ref_target = run([str(ref_cc), "-dumpmachine"]).stdout.strip()
    if canonical_target(micro_target) != canonical_target(ref_target):
        raise RuntimeError(f"target drift: micro={micro_target}, reference={ref_target}")
    if canonical_target(micro_target) != "x86_64-w64-mingw32":
        raise RuntimeError(f"unexpected micro-Clang target: {micro_target}")

    micro_version = run([str(micro_cc), "--version"]).stdout
    ref_version = run([str(ref_cc), "--version"]).stdout
    if "clang version 23.1.0" not in micro_version or "clang version 23.1.0" not in ref_version:
        raise RuntimeError("Phase-1 compilers are not both LLVM/Clang 23.1.0")

    micro_defaults = driver_defaults(micro_cc, source)
    ref_defaults = driver_defaults(ref_cc, source)
    for key in ("triple", "target_cpu", "target_features"):
        if micro_defaults[key] != ref_defaults[key]:
            raise RuntimeError(
                f"driver default mismatch for {key}: "
                f"micro={micro_defaults[key]!r}, reference={ref_defaults[key]!r}"
            )

    (diagnostics / "micro-driver.txt").write_text(
        str(micro_defaults["raw"]), encoding="utf-8"
    )
    (diagnostics / "reference-driver.txt").write_text(
        str(ref_defaults["raw"]), encoding="utf-8"
    )

    abi_source = diagnostics / "abi-probe.c"
    abi_source.write_text(
        r'''#include <stddef.h>
#include <stdio.h>
struct ms_bits {
    char lead;
    unsigned int a:3;
    unsigned int b:5;
    char tail;
};
int main(void) {
    printf("{\"long_double_size\":%zu,"
           "\"long_double_align\":%zu,"
           "\"bitfield_struct_size\":%zu,"
           "\"bitfield_struct_align\":%zu,"
           "\"bitfield_tail_offset\":%zu}\n",
           sizeof(long double), _Alignof(long double),
           sizeof(struct ms_bits), _Alignof(struct ms_bits),
           offsetof(struct ms_bits, tail));
    return 0;
}
''',
        encoding="utf-8",
    )
    micro_abi = abi_probe(micro_cc, abi_source, diagnostics / "micro-abi.exe")
    ref_abi = abi_probe(ref_cc, abi_source, diagnostics / "reference-abi.exe")
    if micro_abi != ref_abi:
        raise RuntimeError(f"ABI mismatch: micro={micro_abi}, reference={ref_abi}")

    smoke_source = diagnostics / "smoke.c"
    smoke_source.write_text(
        "__declspec(dllexport) int micro_clang_smoke(void) { return 42; }\n",
        encoding="utf-8",
    )
    smoke_dll = diagnostics / "micro-clang-smoke.dll"
    run([str(micro_cc), "-shared", str(smoke_source), "-o", str(smoke_dll)])
    pe_text = inspect_pe(readobj, smoke_dll)
    (diagnostics / "smoke-pe.txt").write_text(pe_text, encoding="utf-8")
    for required in ("DYNAMIC_BASE", "HIGH_ENTROPY_VA", "NX_COMPAT", ".reloc", ".pdata"):
        if required.lower() not in pe_text.lower():
            raise RuntimeError(f"generated DLL is missing PE sentinel {required}")

    link_plan = run(
        [str(micro_cc), "-###", "-shared", str(smoke_source), "-o", str(smoke_dll)]
    )
    link_text = link_plan.stderr + "\n" + link_plan.stdout
    (diagnostics / "micro-link-plan.txt").write_text(link_text, encoding="utf-8")
    if "ld.lld" not in link_text.lower():
        raise RuntimeError("micro-Clang GNU/MinGW link plan does not select ld.lld")
    if re.search(r'(?i)(^|[\\/\s"])(link|lld-link)\.exe(["\s]|$)', link_text):
        raise RuntimeError("micro-Clang link plan drifted to an MSVC-style linker")

    host_imports: dict[str, str] = {}
    forbidden = ("libllvm", "libclang-cpp", "vcruntime", "msvcp")
    for name in ("clang-23.exe", "ld.lld.exe", "llvm-dlltool.exe", "llvm-readobj.exe"):
        path = micro / "bin" / name
        text = run([str(readobj), "--coff-imports", str(path)]).stdout
        host_imports[name] = text
        lowered = text.lower()
        for token in forbidden:
            if token in lowered:
                raise RuntimeError(f"{name} has forbidden host runtime dependency: {token}")

    summary = {
        "micro_target": micro_target,
        "reference_target": ref_target,
        "micro_version_first_line": micro_version.splitlines()[0],
        "reference_version_first_line": ref_version.splitlines()[0],
        "driver_defaults": {
            key: micro_defaults[key] for key in ("triple", "target_cpu", "target_features")
        },
        "abi": micro_abi,
        "pe_sentinels": "passed",
        "host_shared_runtime_sentinels": "passed",
        "path_with_spaces": " " in str(micro),
    }
    (diagnostics / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name, text in host_imports.items():
        (diagnostics / f"{name}.imports.txt").write_text(text, encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
