"""Hermetic runtime configuration for the Windows FEniCS FFCx/CFFI JIT."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


_REMOVED_ENV = {
    "CC", "CXX", "CPP", "LD", "LDSHARED",
    "INCLUDE", "LIB", "LIBPATH", "LIBRARY_PATH",
    "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH",
    "COMPILER_PATH", "GCC_EXEC_PREFIX",
    "VSINSTALLDIR", "VCINSTALLDIR", "VCToolsInstallDir",
    "WindowsSdkDir", "WindowsSDKVersion",
    "UniversalCRTSdkDir", "UCRTVersion",
    "DISTUTILS_USE_SDK", "MSSdk",
}
_REMOVED_PREFIXES = ("VSCMD_",)


def _require_file(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"{label} not found: {path}")
    return path


def _require_dir(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_dir():
        raise RuntimeError(f"{label} not found: {path}")
    return path


def _dedupe(paths: list[Path | str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in paths:
        text = str(value)
        key = os.path.normcase(os.path.abspath(text))
        if key not in seen:
            seen.add(key)
            result.append(text)
    return result


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved compiler and development inputs for one JIT process."""

    toolchain_root: Path
    python_prefix: Path
    clang: Path
    clangxx: Path
    lld: Path
    readobj: Path
    toolchain_include: Path
    target_library_dir: Path
    python_include: Path
    python_dll: Path
    python_import_library_dir: Path
    python_import_library: Path
    python_stable_import_library: Path
    ffcx_include: Path
    runtime_dll_dir: Path | None
    backend: str = "mingw32"
    target: str = "x86_64-w64-mingw32"
    crt: str = "UCRT"

    @classmethod
    def discover(
        cls,
        *,
        toolchain_root: str | os.PathLike[str] | None = None,
        python_prefix: str | os.PathLike[str] | None = None,
        python_include: str | os.PathLike[str] | None = None,
        ffcx_include: str | os.PathLike[str] | None = None,
    ) -> "RuntimeConfig":
        root = (
            Path(toolchain_root).resolve()
            if toolchain_root is not None
            else Path(__file__).resolve().parent.parent
        )
        prefix = Path(python_prefix or sys.prefix).resolve()
        bin_dir = _require_dir(root / "bin", "LLVM-MinGW bin directory")

        clang = _require_file(bin_dir / "x86_64-w64-mingw32-clang.exe", "Clang C driver")
        clangxx = _require_file(
            bin_dir / "x86_64-w64-mingw32-clang++.exe", "Clang C++ driver"
        )
        lld = _require_file(bin_dir / "ld.lld.exe", "LLD linker")
        readobj = _require_file(bin_dir / "llvm-readobj.exe", "llvm-readobj")
        toolchain_include_dir = _require_dir(root / "include", "mingw-w64/UCRT include root")
        _require_file(toolchain_include_dir / "io.h", "mingw-w64 io.h")
        target_library_dir = _require_dir(
            root / "x86_64-w64-mingw32" / "lib", "x86-64 target library root"
        )

        py_include = Path(python_include or sysconfig.get_path("include")).resolve()
        _require_file(py_include / "Python.h", "Python.h")
        _require_file(py_include / "pyconfig.h", "pyconfig.h")

        dll_candidates = [
            prefix / "python3.dll",
            prefix / "DLLs" / "python3.dll",
            prefix / "Library" / "bin" / "python3.dll",
        ]
        python_dll_path = next((p.resolve() for p in dll_candidates if p.is_file()), None)
        if python_dll_path is None:
            raise RuntimeError(f"python3.dll not found below Python prefix: {prefix}")

        version_tag = f"{sys.version_info.major}{sys.version_info.minor}"
        py_lib_dir = _require_dir(root / "lib" / "python", "packaged Python import-library root")
        py_lib = _require_file(
            py_lib_dir / f"libpython{version_tag}.a",
            f"GNU Python {version_tag} import library",
        )
        py_stable = _require_file(
            py_lib_dir / "libpython3.a", "GNU stable-ABI Python import library"
        )

        if ffcx_include is None:
            spec = importlib.util.find_spec("ffcx")
            if spec is None or not spec.submodule_search_locations:
                raise RuntimeError("Cannot locate installed FFCx package")
            package_root = Path(next(iter(spec.submodule_search_locations))).resolve()
            ffcx_include_path = package_root / "codegeneration"
        else:
            ffcx_include_path = Path(ffcx_include).resolve()
        ffcx_include_path = _require_dir(ffcx_include_path, "FFCx/UFCx include root")
        _require_file(ffcx_include_path / "ufcx.h", "ufcx.h")

        runtime_dll = prefix / "Library" / "bin"
        runtime_dll_dir = runtime_dll.resolve() if runtime_dll.is_dir() else None

        return cls(
            toolchain_root=root,
            python_prefix=prefix,
            clang=clang,
            clangxx=clangxx,
            lld=lld,
            readobj=readobj,
            toolchain_include=toolchain_include_dir,
            target_library_dir=target_library_dir,
            python_include=py_include,
            python_dll=python_dll_path,
            python_import_library_dir=py_lib_dir,
            python_import_library=py_lib,
            python_stable_import_library=py_stable,
            ffcx_include=ffcx_include_path,
            runtime_dll_dir=runtime_dll_dir,
        )

    @property
    def bin_dir(self) -> Path:
        return self.toolchain_root / "bin"

    def extension_include_dirs(self, existing: list[str] | None = None) -> list[str]:
        return _dedupe(
            [self.python_include, self.ffcx_include, self.toolchain_include, *(existing or [])]
        )

    def extension_library_dirs(self, existing: list[str] | None = None) -> list[str]:
        return _dedupe(
            [self.python_import_library_dir, self.target_library_dir, *(existing or [])]
        )

    def sanitized_environment(self) -> dict[str, str]:
        env = dict(os.environ)
        for key in list(env):
            if key in _REMOVED_ENV or any(key.startswith(prefix) for prefix in _REMOVED_PREFIXES):
                env.pop(key, None)

        system_root = Path(env.get("SystemRoot", r"C:\Windows"))
        env["PATH"] = os.pathsep.join(
            _dedupe(
                [
                    self.bin_dir,
                    self.python_prefix,
                    self.python_prefix / "Scripts",
                    system_root / "System32",
                    system_root,
                ]
            )
        )
        env["CC"] = self.clang.name
        env["CXX"] = self.clangxx.name
        env["SETUPTOOLS_USE_DISTUTILS"] = "local"
        env["FFCX_CFFI_COMPILER_BACKEND"] = self.backend
        env["FENICS_JIT_ROOT"] = str(self.toolchain_root)
        env["FENICS_JIT_PYTHON_INCLUDE"] = str(self.python_include)
        env["FENICS_JIT_PYTHON_LIBRARY_DIR"] = str(self.python_import_library_dir)
        env["FENICS_JIT_FFCX_INCLUDE"] = str(self.ffcx_include)
        return env

    def diagnostic_record(self) -> dict[str, object]:
        env = self.sanitized_environment()
        clang_version = subprocess.run(
            [str(self.clang), "--version"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.splitlines()[0]
        clang_target = subprocess.run(
            [str(self.clang), "-dumpmachine"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()
        lld_version = subprocess.run(
            [str(self.lld), "--version"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.splitlines()[0]
        return {
            "backend": self.backend,
            "target": self.target,
            "clang_reported_target": clang_target,
            "crt": self.crt,
            "clang_version": clang_version,
            "lld_version": lld_version,
            "toolchain_root": str(self.toolchain_root),
            "clang": str(self.clang),
            "lld": str(self.lld),
            "toolchain_include": str(self.toolchain_include),
            "target_library_dir": str(self.target_library_dir),
            "python_prefix": str(self.python_prefix),
            "python_include": str(self.python_include),
            "python_dll": str(self.python_dll),
            "python_import_library_dir": str(self.python_import_library_dir),
            "python_import_library": str(self.python_import_library),
            "python_stable_import_library": str(self.python_stable_import_library),
            "ffcx_include": str(self.ffcx_include),
            "runtime_dll_dir": str(self.runtime_dll_dir) if self.runtime_dll_dir else None,
        }

    def _verify_path_and_tools(self) -> None:
        resolved_cc = shutil.which(self.clang.name)
        if resolved_cc is None or Path(resolved_cc).resolve() != self.clang:
            raise RuntimeError(f"CC does not resolve to packaged Clang: {resolved_cc}")

        for forbidden in ("cl.exe", "vswhere.exe", "vcvarsall.bat"):
            resolved = shutil.which(forbidden)
            if resolved:
                raise RuntimeError(f"Forbidden ambient tool is resolvable: {forbidden} -> {resolved}")

        resolved_link = shutil.which("link.exe")
        if resolved_link is not None:
            link = Path(resolved_link).resolve()
            try:
                link.relative_to(self.bin_dir.resolve())
            except ValueError as exc:
                raise RuntimeError(f"Ambient link.exe is resolvable: {link}") from exc

    @contextlib.contextmanager
    def activate(
        self,
        *,
        diagnostics_dir: str | os.PathLike[str] | None = None,
        verbose: bool = False,
    ) -> Iterator["RuntimeConfig"]:
        """Apply JIT-local configuration and restore the process afterwards."""
        saved_environment = dict(os.environ)
        dll_handles: list[object] = []
        shim = None
        original_distribution = None

        try:
            sanitized = self.sanitized_environment()
            os.environ.clear()
            os.environ.update(sanitized)

            if os.name == "nt" and self.runtime_dll_dir is not None:
                dll_handles.append(os.add_dll_directory(str(self.runtime_dll_dir)))

            self._verify_path_and_tools()

            import cffi._shimmed_dist_utils as shim_module

            shim = shim_module
            original_distribution = shim.Distribution
            config = self

            class RuntimeDistribution(original_distribution):
                def parse_config_files(self, filenames=None, ignore_option_errors=False):
                    # CFFI's temporary Distribution has no package metadata that
                    # needs ambient setup.cfg/pydistutils.cfg input. Ignore such
                    # files completely and own build_ext selection here.
                    options = self.get_option_dict("build_ext")
                    options.clear()
                    options["compiler"] = ("fenics-jit-runtime", config.backend)
                    for extension in self.ext_modules or []:
                        extension.include_dirs = config.extension_include_dirs(
                            extension.include_dirs
                        )
                        extension.library_dirs = config.extension_library_dirs(
                            extension.library_dirs
                        )
                    return None

            shim.Distribution = RuntimeDistribution

            record = self.diagnostic_record()
            if diagnostics_dir is not None:
                diagnostics = Path(diagnostics_dir).resolve()
                diagnostics.mkdir(parents=True, exist_ok=True)
                (diagnostics / "runtime-config.json").write_text(
                    json.dumps(record, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                (diagnostics / "runtime-environment.txt").write_text(
                    "\n".join(
                        [
                            f"PATH={os.environ['PATH']}",
                            f"CC={os.environ['CC']}",
                            f"CXX={os.environ['CXX']}",
                            f"FFCX_CFFI_COMPILER_BACKEND={os.environ['FFCX_CFFI_COMPILER_BACKEND']}",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )

            if verbose:
                print(
                    "FFCx JIT compiler: "
                    f"LLVM-MinGW / {record['clang_version']} / {self.backend} / "
                    f"{record['clang_reported_target']} / {self.crt}"
                )
                print(f"FFCx JIT linker: {record['lld_version']}")
                print(f"FFCx JIT Python: {self.python_include} / {self.python_dll.name}")
                print(f"FFCx JIT Python import library: {self.python_import_library}")
                print(f"FFCx JIT UFCx include: {self.ffcx_include}")

            yield self
        finally:
            if shim is not None and original_distribution is not None:
                shim.Distribution = original_distribution
            for handle in reversed(dll_handles):
                close = getattr(handle, "close", None)
                if close is not None:
                    close()
            os.environ.clear()
            os.environ.update(saved_environment)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--toolchain-root")
    parser.add_argument("--python-prefix")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = RuntimeConfig.discover(
        toolchain_root=args.toolchain_root,
        python_prefix=args.python_prefix,
    )
    record = config.diagnostic_record()
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print(
            f"LLVM-MinGW / {record['clang_version']} / {config.backend} / "
            f"{record['clang_reported_target']} / {config.crt}"
        )
        print(f"Python: {config.python_include} / {config.python_dll.name}")


if __name__ == "__main__":
    main()
