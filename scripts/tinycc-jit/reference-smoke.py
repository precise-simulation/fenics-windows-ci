"""Non-blocking TinyCC formal-release reference smoke."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pefile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tinycc-root", required=True)
    parser.add_argument("--diagnostics-dir", required=True)
    args = parser.parse_args()

    root = Path(args.tinycc_root).resolve()
    diagnostics = Path(args.diagnostics_dir).resolve()
    diagnostics.mkdir(parents=True, exist_ok=True)
    tcc = root / "tcc.exe"
    source = diagnostics / "reference.c"
    output = diagnostics / "reference.dll"
    source.write_text(
        "__declspec(dllexport) int tinycc_reference(void) { return 42; }\n",
        encoding="ascii",
    )
    command = [
        str(tcc),
        "-B" + str(root),
        "-shared",
        "-Wl,-dynamicbase",
        "-Wl,-high-entropy-va",
        "-Wl,-nxcompat",
        str(source),
        "-o",
        str(output),
    ]
    result = subprocess.run(command, text=True, capture_output=True)
    payload: dict[str, object] = {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.returncode == 0 and output.is_file():
        pe = pefile.PE(str(output), fast_load=False)
        chars = int(pe.OPTIONAL_HEADER.DllCharacteristics)
        payload["dll_characteristics"] = hex(chars)
        payload["dynamic_base"] = bool(chars & 0x40)
        payload["high_entropy_va"] = bool(chars & 0x20)
        payload["nx_compat"] = bool(chars & 0x100)
        payload["pdata"] = any(
            section.Name.rstrip(b"\0") == b".pdata" and int(section.SizeOfRawData) > 0
            for section in pe.sections
        )
    (diagnostics / "reference-smoke.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    if not all(payload.get(key) is True for key in ("dynamic_base", "high_entropy_va", "nx_compat", "pdata")):
        raise SystemExit("formal release does not meet the fixed hardened PE baseline")


if __name__ == "__main__":
    main()
