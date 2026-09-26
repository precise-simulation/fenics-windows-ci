"""Verify the conservative Phase-2 micro-Clang package is relocatable."""

from __future__ import annotations

import argparse
import json
import py_compile
import subprocess
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--evidence-dir", required=True)
    args = parser.parse_args()

    root = Path(args.backend_root).resolve()
    work = Path(args.work_dir).resolve()
    evidence = Path(args.evidence_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)

    required = [
        root / "bin" / "x86_64-w64-mingw32-clang.exe",
        root / "bin" / "clang-23.exe",
        root / "bin" / "ld.lld.exe",
        root / "bin" / "llvm-readobj.exe",
        root / "bin" / "llvm-dlltool.exe",
        root / "bin" / "libc++.dll",
        root / "bin" / "libunwind.dll",
        root / "include" / "stdio.h",
        root / "include" / "windows.h",
        root / "lib" / "clang" / "23" / "lib" / "windows" / "libclang_rt.builtins-x86_64.a",
        root / "x86_64-w64-mingw32" / "lib" / "libunwind.a",
        root / "lib" / "python" / "libpython3.a",
        root / "lib" / "python" / "libpython312.a",
        root / "lib" / "python" / "libpython313.a",
        root / "lib" / "python" / "libpython314.a",
        root / "metadata.json",
        root / "manifest.csv",
        root / "size.txt",
        root / "fenics_jit_runtime.py",
        root / "provenance" / "build-provenance.json",
        root / "licenses" / "LLVM-LICENSE.TXT",
        root / "licenses" / "llvm-mingw-LICENSE.txt",
        root / "licenses" / "mingw-w64-COPYING",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Phase-2 package files missing: {missing}")

    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8-sig"))
    if metadata.get("package") != "fenics-jit-micro-clang":
        raise RuntimeError(f"unexpected Phase-2 package metadata: {metadata}")
    if metadata.get("phase") != 2:
        raise RuntimeError(f"unexpected package phase: {metadata.get('phase')!r}")
    if metadata.get("production_selector_integrated") is not False:
        raise RuntimeError("Phase-2 package must not integrate the production selector")

    py_compile.compile(str(root / "fenics_jit_runtime.py"), doraise=True)

    clang = root / "bin" / "x86_64-w64-mingw32-clang.exe"
    target = run([str(clang), "-dumpmachine"]).stdout.strip()
    if target.lower() not in {"x86_64-w64-mingw32", "x86_64-w64-windows-gnu"}:
        raise RuntimeError(f"unexpected packaged target: {target!r}")

    source = work / "package smoke with spaces.c"
    dll = work / "package smoke with spaces.dll"
    source.write_text(
        "__declspec(dllexport) int micro_clang_phase2_smoke(void) { return 42; }\n",
        encoding="ascii",
    )
    driver = run(
        [str(clang), "-###", "-O2", "-std=c17", "-shared", str(source), "-o", str(dll)]
    ).stderr.lower()
    for token in ("ld.lld", "libclang_rt.builtins", '"-lunwind"'):
        if token not in driver:
            raise RuntimeError(f"packaged link policy missing {token!r}")

    run([str(clang), "-O2", "-std=c17", "-shared", str(source), "-o", str(dll)])
    if not dll.is_file():
        raise RuntimeError("packaged compiler did not produce smoke DLL")

    pe = pefile.PE(str(dll), fast_load=False)
    chars = int(pe.OPTIONAL_HEADER.DllCharacteristics)
    hardening = {}
    for name, mask in _REQUIRED_DLL_CHARACTERISTICS.items():
        hardening[name] = bool(chars & mask)
        if not hardening[name]:
            raise RuntimeError(f"packaged smoke DLL missing PE hardening bit: {name}")

    reloc = pe.OPTIONAL_HEADER.DATA_DIRECTORY[5]
    if int(reloc.Size) <= 0:
        raise RuntimeError("packaged smoke DLL has no relocation directory")
    pdata = next(
        (
            section
            for section in pe.sections
            if section.Name.rstrip(b"\0") == b".pdata" and int(section.SizeOfRawData) > 0
        ),
        None,
    )
    if pdata is None:
        raise RuntimeError("packaged smoke DLL has no x64 .pdata unwind metadata")

    result = {
        "schema": "fenics-jit-micro-clang-phase2-smoke-v1",
        "status": "pass",
        "backend_root": str(root),
        "target": target,
        "hardening": hardening,
        "relocation_size": int(reloc.Size),
        "pdata_size": int(pdata.SizeOfRawData),
        "production_selector_integrated": False,
    }
    (evidence / "phase2-smoke.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
