"""Apply the Phase 1 FFCx C17 flag patch for a MinGW-style backend."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
from pathlib import Path


OLD = """    # Compile in C17 mode
    if sys.platform.startswith("win32"):
        cffi_base_compile_args = ["-std:c17"]
    else:
        cffi_base_compile_args = ["-std=c17"]
"""

NEW = """    # Compile in C17 mode. Windows MSVC and GNU-style drivers use
    # different spellings, so key this off the selected CFFI backend rather
    # than sys.platform alone. The MSVC-built DOLFINx UFCx ABI omits complex
    # function-pointer members. LLVM-MinGW supports C99 complex, so explicitly
    # suppress those members to keep ufcx_integral layout ABI-compatible.
    cffi_compiler_backend = os.environ.get("FFCX_CFFI_COMPILER_BACKEND", "").lower()
    if sys.platform.startswith("win32"):
        if cffi_compiler_backend == "mingw32":
            cffi_base_compile_args = ["-std=c17", "-D__STDC_NO_COMPLEX__"]
        else:
            cffi_base_compile_args = ["-std:c17"]
    else:
        cffi_base_compile_args = ["-std=c17"]
"""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostics-dir", required=True)
    args = parser.parse_args()

    diagnostics = Path(args.diagnostics_dir).resolve()
    diagnostics.mkdir(parents=True, exist_ok=True)

    spec = importlib.util.find_spec("ffcx.codegeneration.jit")
    if spec is None or spec.origin is None:
        raise RuntimeError("Cannot locate installed ffcx.codegeneration.jit")

    path = Path(spec.origin).resolve()
    source = path.read_text(encoding="utf-8")
    before = sha256(source)

    if NEW in source:
        patched = source
        status = "already-patched"
    elif OLD in source:
        patched = source.replace(OLD, NEW, 1)
        path.write_text(patched, encoding="utf-8")
        status = "patched"
    else:
        raise RuntimeError(
            f"Installed FFCx JIT source at {path} does not match the expected 0.11.x C17 block"
        )

    after = sha256(patched)
    (diagnostics / "ffcx-c17-patch.txt").write_text(
        f"status={status}\npath={path}\nbefore_sha256={before}\nafter_sha256={after}\n",
        encoding="utf-8",
    )
    print(f"FFCx C17 patch: {status}: {path}")


if __name__ == "__main__":
    main()
