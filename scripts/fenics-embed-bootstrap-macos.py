"""Runtime bootstrap for the relocatable macOS FEniCS overlay."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shlex
import shutil
import stat
import sys
import tempfile


_ACTIVATED_ROOT: Path | None = None
_JIT_WRAPPER: Path | None = None
_JIT_ZIG_SOURCE: Path | None = None
_JIT_ZIG_EXE: Path | None = None


def _runtime_root() -> Path:
    here = Path(__file__).resolve()
    framework = next((parent for parent in here.parents if parent.name == "Python.framework"), None)
    if framework is None:
        raise RuntimeError(f"cannot derive embedded runtime root from bootstrap location: {here}")
    return framework.parent.resolve()


def _prepend_path(name: str, value: Path) -> None:
    current = os.environ.get(name, "")
    parts = [item for item in current.split(os.pathsep) if item]
    normalized = {os.path.normcase(os.path.abspath(item)) for item in parts}
    candidate = os.path.normcase(os.path.abspath(str(value)))
    if candidate not in normalized:
        os.environ[name] = str(value) + (os.pathsep + current if current else "")


def _wrapper_root(runtime_root: Path) -> Path:
    candidates = []
    for raw in (os.environ.get("RUNNER_TEMP"), tempfile.gettempdir(), "/tmp"):
        if raw:
            path = Path(raw).resolve()
            if path not in candidates:
                candidates.append(path)
    for base in candidates:
        if any(character.isspace() for character in str(base)):
            continue
        token = hashlib.sha256(str(runtime_root).encode("utf-8")).hexdigest()[:16]
        return base / f"fenics-embed-zig-{token}-{platform.machine()}-{os.getpid()}"
    raise RuntimeError("no whitespace-safe temporary directory is available for the FEniCS Zig compiler shim")


def _write_jit_wrapper(runtime_root: Path) -> tuple[Path, Path, Path]:
    global _JIT_WRAPPER, _JIT_ZIG_SOURCE, _JIT_ZIG_EXE
    if (
        _JIT_WRAPPER is not None
        and _JIT_WRAPPER.exists()
        and _JIT_ZIG_SOURCE is not None
        and _JIT_ZIG_EXE is not None
        and _JIT_ZIG_EXE.exists()
    ):
        return _JIT_WRAPPER, _JIT_ZIG_SOURCE, _JIT_ZIG_EXE

    machine = platform.machine()
    target = {
        "arm64": "aarch64-macos.14.0",
        "x86_64": "x86_64-macos.14.0",
    }.get(machine)
    if target is None:
        raise RuntimeError(f"unsupported macOS FEniCS runtime architecture: {machine}")

    zig_source_root = runtime_root / "fenics-runtime" / "zig"
    zig_source = zig_source_root / "zig"
    if not zig_source.is_file():
        raise RuntimeError(f"bundled Zig executable is missing: {zig_source}")

    root = _wrapper_root(runtime_root)
    root.mkdir(parents=True, exist_ok=True)
    runtime_alias = root / "runtime-root"
    runtime_alias.symlink_to(runtime_root, target_is_directory=True)

    # The x86_64 Zig clang frontend can fail under Rosetta when its own
    # InstalledDir contains whitespace. Keep the relocated runtime itself under
    # its real path, but execute an exact temporary copy of the bundled Zig tree
    # from a whitespace-safe location. No ambient compiler/toolchain is used.
    zig = zig_source
    if machine == "x86_64" and any(character.isspace() for character in str(zig_source_root)):
        staged_zig_root = root / "zig-runtime"
        shutil.copytree(zig_source_root, staged_zig_root, symlinks=True)
        zig = staged_zig_root / "zig"
        if not zig.is_file():
            raise RuntimeError(f"staged Zig executable is missing: {zig}")
        source_sha256 = hashlib.sha256(zig_source.read_bytes()).digest()
        staged_sha256 = hashlib.sha256(zig.read_bytes()).digest()
        if staged_sha256 != source_sha256:
            raise RuntimeError("staged Zig executable differs from bundled Zig")

    wrapper = root / "fenics-zig-cc"
    python_include = runtime_alias / "Python.framework" / "Versions" / "3.12" / "include" / "python3.12"
    private_include = runtime_alias / "fenics-runtime" / "conda" / "include"
    if not python_include.is_dir():
        raise RuntimeError(f"staged CPython headers are missing: {python_include}")
    if not private_include.is_dir():
        raise RuntimeError(f"private FEniCS/PETSc headers are missing: {private_include}")
    script = f"""#!/usr/bin/env bash
set -euo pipefail
zig={shlex.quote(str(zig))}
target={shlex.quote(target)}
runtime_root={shlex.quote(str(runtime_root))}
runtime_alias={shlex.quote(str(runtime_alias))}
python_include={shlex.quote(str(python_include))}
private_include={shlex.quote(str(private_include))}
args=("-I$python_include" "-I$private_include")
python_extension_link=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        -bundle)
            python_extension_link=1
            shift
            ;;
        -undefined)
            if [[ "${{2:-}}" == dynamic_lookup ]]; then
                python_extension_link=1
                shift 2
            else
                args+=("$1")
                shift
            fi
            ;;
        -arch)
            # A universal2 host CPython injects both architecture slices via
            # sysconfig.  This shim already pins one exact Zig target, so
            # inherited -arch flags must not override or conflict with it.
            shift 2
            ;;
        -isysroot)
            shift 2
            ;;
        -isysroot*)
            shift
            ;;
        -I)
            if [[ "${{2:-}}" == */include/python3.12 && "${{2:-}}" != "$runtime_root"/* ]]; then
                shift 2
            elif [[ "${{2:-}}" == "$runtime_root"/* ]]; then
                args+=("$1" "$runtime_alias/${{2#"$runtime_root"/}}")
                shift 2
            else
                args+=("$1" "${{2:-}}")
                shift 2
            fi
            ;;
        -I"$runtime_root"/*)
            args+=("-I$runtime_alias/${{1#-I"$runtime_root"/}}")
            shift
            ;;
        -I*/include/python3.12)
            shift
            ;;
        -isystem)
            if [[ "${{2:-}}" == "$runtime_root"/* ]]; then
                args+=("$1" "$runtime_alias/${{2#"$runtime_root"/}}")
            fi
            shift 2
            ;;
        -isystem"$runtime_root"/*)
            args+=("-isystem$runtime_alias/${{1#-isystem"$runtime_root"/}}")
            shift
            ;;
        -isystem*)
            shift
            ;;
        -mmacosx-version-min=*)
            shift
            ;;
        -Wl,-syslibroot,*|-Wl,-platform_version,macos,*)
            shift
            ;;
        *)
            args+=("$1")
            shift
            ;;
    esac
done
if [[ $python_extension_link -eq 1 ]]; then
    exec "$zig" cc -target "$target" -mmacosx-version-min=14.0 -shared -Wl,-undefined,dynamic_lookup "${{args[@]}}"
fi
exec "$zig" cc -target "$target" -mmacosx-version-min=14.0 "${{args[@]}}"
"""
    wrapper.write_text(script, encoding="utf-8")
    wrapper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    _JIT_WRAPPER = wrapper
    _JIT_ZIG_SOURCE = zig_source
    _JIT_ZIG_EXE = zig
    return wrapper, zig_source, zig


def activate() -> Path:
    """Activate the bundled macOS FEniCS runtime from its installed location."""

    global _ACTIVATED_ROOT

    if sys.platform != "darwin":
        raise RuntimeError("fenics_embed_runtime macOS overlay requires Darwin")
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(
            f"FEniCS embedded runtime requires CPython 3.12, got {sys.version_info.major}.{sys.version_info.minor}"
        )

    root = _runtime_root()
    if _ACTIVATED_ROOT is not None:
        if _ACTIVATED_ROOT != root:
            raise RuntimeError(
                f"FEniCS embedded runtime already activated from {_ACTIVATED_ROOT}; cannot switch to {root}"
            )
        return root

    private_prefix = root / "fenics-runtime" / "conda"
    private_site = private_prefix / "lib" / "python3.12" / "site-packages"
    for required, label in (
        (private_prefix / "lib", "private native-library root"),
        (private_site, "private FEniCS site-packages"),
        (root / "fenics-runtime" / "zig" / "zig", "bundled Zig compiler"),
    ):
        if not required.exists():
            raise RuntimeError(f"{label} is missing from embedded runtime: {required}")

    private_site_text = str(private_site)
    if private_site_text not in sys.path:
        sys.path.insert(0, private_site_text)

    wrapper, zig_source, zig_exe = _write_jit_wrapper(root)
    _prepend_path("PATH", wrapper.parent)

    os.environ["PETSC_DIR"] = str(private_prefix)
    os.environ["PETSC_ARCH"] = ""
    os.environ["CC"] = str(wrapper)
    os.environ["CXX"] = str(wrapper)
    os.environ["CPP"] = f"{wrapper} -E"
    os.environ["LDSHARED"] = f"{wrapper} -bundle -undefined dynamic_lookup"
    os.environ["MACOSX_DEPLOYMENT_TARGET"] = "14.0"
    os.environ["FENICS_ZIG_SOURCE"] = str(zig_source)
    os.environ["FENICS_ZIG_EXE"] = str(zig_exe)
    os.environ["FENICS_ZIG_TARGET"] = (
        "aarch64-macos.14.0" if platform.machine() == "arm64" else "x86_64-macos.14.0"
    )

    import petsc4py

    current_get_config = petsc4py.get_config
    if not getattr(current_get_config, "_fenics_embed_runtime", False):

        def relocated_get_config(_petsc_root=str(private_prefix)):
            return {"PETSC_DIR": _petsc_root, "PETSC_ARCH": ""}

        relocated_get_config._fenics_embed_runtime = True
        petsc4py.get_config = relocated_get_config

    _ACTIVATED_ROOT = root
    return root
