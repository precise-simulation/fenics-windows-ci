"""Owned TinyCC CFFI adapter for FEniCS JIT on Windows.

The adapter intercepts the temporary Distribution created by cffi.ffiplatform,
suppresses ambient distutils/setuptools configuration, and builds CFFI
extensions directly from C source to a .pyd with TinyCC. Process-global
activation is serialized and restoration-safe.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sysconfig
import threading
from pathlib import Path
from typing import Iterator, Sequence

from cffi import _shimmed_dist_utils as _dist


ADAPTER_SCHEMA_VERSION = "tinycc-cffi-adapter-v2"
EXTERNAL_CONFIG_POLICY_VERSION = "suppress-all-v1"
PYTHON_LINK_POLICY_VERSION = "stable-abi-python3-def-v1"
PE_HARDENING_POLICY_VERSION = "dynamicbase-highentropyva-nxcompat-v1"
CRT_POLICY_VERSION = "msvcrt-owned-allocation-boundary-v1"
ABI_POLICY_VERSION = "mingw32-mswin64-msbitfields-longdouble8-v1"
SYSTEM_LIBRARY_POLICY_VERSION = "windows-system-dll-resolution-v1"

_VERSIONED_PYTHON = re.compile(r"(?i)(?:^|[\\/])?python3(?:12|13|14|15)(?:_d)?(?:\.lib|\.dll)?$")
_FOREIGN_BINARY_SUFFIXES = {".obj", ".o", ".lib", ".a"}
_ALLOWED_EXTRA_ARGS = {"-O0", "-O1", "-O2", "-O3", "-g", "-DNDEBUG"}
_TRANSLATED_LANGUAGE_ARGS = {"-std:c17", "/std:c17", "-std=c17", "-std=gnu17"}
_FORBIDDEN_INCLUDE_TOKENS = ("microsoft visual studio", "windows kits", "\\pcbuild")
_FORBIDDEN_COMMAND_TOKENS = ("cl.exe", "link.exe", "clang", "gcc", "vswhere", "microsoft visual studio", "windows kits")

_ACTIVATION_LOCK = threading.RLock()
_ACTIVE_CONFIG: TinyCCConfig | None = None
_ACTIVE_DEPTH = 0
_ACTIVE_OWNER_THREAD: int | None = None
_ORIGINAL_DISTRIBUTION = None


def _policy_identity(revision: str) -> str:
    payload = {
        "revision": revision,
        "adapter_schema": ADAPTER_SCHEMA_VERSION,
        "external_config": EXTERNAL_CONFIG_POLICY_VERSION,
        "python_link": PYTHON_LINK_POLICY_VERSION,
        "pe_hardening": PE_HARDENING_POLICY_VERSION,
        "crt": CRT_POLICY_VERSION,
        "abi": ABI_POLICY_VERSION,
        "system_library": SYSTEM_LIBRARY_POLICY_VERSION,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:20]
    return f"tinycc-{revision[:12]}-{digest}"


@dataclasses.dataclass(frozen=True)
class TinyCCConfig:
    root: Path
    tcc: Path
    python_def: Path
    diagnostics_dir: Path
    revision: str
    backend_cache_id: str

    @classmethod
    def discover(
        cls,
        *,
        root: Path,
        python_def: Path,
        diagnostics_dir: Path,
        revision: str,
    ) -> "TinyCCConfig":
        root = root.resolve()
        tcc = (root / "tcc.exe").resolve()
        python_def = python_def.resolve()
        diagnostics_dir = diagnostics_dir.resolve()
        if not tcc.is_file():
            raise RuntimeError(f"TinyCC executable is missing: {tcc}")
        if not python_def.is_file():
            raise RuntimeError(f"python3.def is missing: {python_def}")
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        return cls(root, tcc, python_def, diagnostics_dir, revision, _policy_identity(revision))

    def policy_metadata(self) -> dict[str, str]:
        return {
            "revision": self.revision,
            "backend_cache_id": self.backend_cache_id,
            "adapter_schema": ADAPTER_SCHEMA_VERSION,
            "external_config_policy": EXTERNAL_CONFIG_POLICY_VERSION,
            "python_link_policy": PYTHON_LINK_POLICY_VERSION,
            "pe_hardening_policy": PE_HARDENING_POLICY_VERSION,
            "crt_policy": CRT_POLICY_VERSION,
            "abi_policy": ABI_POLICY_VERSION,
            "system_library_policy": SYSTEM_LIBRARY_POLICY_VERSION,
        }


def _active_config() -> TinyCCConfig:
    if _ACTIVE_CONFIG is None:
        raise RuntimeError("TinyCC CFFI adapter used outside an active TinyCC context")
    return _ACTIVE_CONFIG


def _record(config: TinyCCConfig, name: str, payload: object) -> None:
    path = config.diagnostics_dir / name
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")


def _dependency_versions() -> dict[str, str]:
    return {
        "cffi": importlib.metadata.version("cffi"),
        "setuptools": importlib.metadata.version("setuptools"),
    }


def validate_cffi_integration() -> dict[str, str]:
    """Fail clearly if the qualified CFFI interception surface is unavailable."""
    from cffi import ffiplatform

    if not hasattr(_dist, "Distribution"):
        raise RuntimeError("Unsupported CFFI: cffi._shimmed_dist_utils.Distribution is unavailable")
    if not callable(getattr(ffiplatform, "_build", None)):
        raise RuntimeError("Unsupported CFFI: cffi.ffiplatform._build is unavailable")
    versions = _dependency_versions()
    versions["interception"] = "cffi._shimmed_dist_utils.Distribution"
    return versions


def _header_supports_py_no_link_lib() -> bool:
    include = Path(sysconfig.get_path("include") or "")
    if not include.is_dir():
        return False
    for name in ("Python.h", "pyconfig.h"):
        path = include / name
        if path.is_file() and "Py_NO_LINK_LIB" in path.read_text(encoding="utf-8", errors="ignore"):
            return True
    return False


def _reject_path(path: str | os.PathLike[str], *, what: str) -> None:
    value = str(path)
    suffix = Path(value).suffix.lower()
    if suffix in _FOREIGN_BINARY_SUFFIXES:
        raise RuntimeError(f"TinyCC adapter rejects {what} input: {value}")
    if _VERSIONED_PYTHON.search(Path(value).name):
        raise RuntimeError(f"TinyCC adapter rejects versioned Python link input: {value}")


def _translate_extra_args(args: Sequence[str]) -> list[str]:
    translated: list[str] = []
    for raw in args:
        arg = str(raw)
        if arg in _TRANSLATED_LANGUAGE_ARGS:
            # Phase 1 qualified the generated corpus using TinyCC's C11/default mode.
            continue
        if arg in _ALLOWED_EXTRA_ARGS or arg.startswith("-D") or arg.startswith("-U"):
            translated.append(arg)
            continue
        raise RuntimeError(f"TinyCC adapter does not support compile argument {arg!r}")
    return translated


class TinyCCBuildExt(_dist.build_ext):
    """CFFI build_ext command that invokes TinyCC directly source-to-PYD."""

    def get_libraries(self, ext):  # noqa: ANN001
        libraries = list(getattr(ext, "libraries", None) or [])
        if libraries:
            raise RuntimeError(f"TinyCC adapter rejects CFFI libraries: {libraries!r}")
        return []

    def build_extension(self, ext):  # noqa: ANN001
        config = _active_config()

        sources = [Path(source).resolve() for source in (getattr(ext, "sources", None) or [])]
        if not sources:
            raise RuntimeError("TinyCC adapter received an extension with no C sources")
        for source in sources:
            if source.suffix.lower() != ".c":
                raise RuntimeError(f"TinyCC adapter accepts only C sources, got: {source}")
            if not source.is_file():
                raise RuntimeError(f"C source does not exist: {source}")

        extra_objects = list(getattr(ext, "extra_objects", None) or [])
        if extra_objects:
            for item in extra_objects:
                _reject_path(item, what="extra object")
            raise RuntimeError(f"TinyCC adapter rejects extra_objects: {extra_objects!r}")

        libraries = list(getattr(ext, "libraries", None) or [])
        if libraries:
            for item in libraries:
                _reject_path(item, what="library")
            raise RuntimeError(f"TinyCC adapter rejects CFFI libraries: {libraries!r}")

        library_dirs = list(getattr(ext, "library_dirs", None) or [])
        runtime_library_dirs = list(getattr(ext, "runtime_library_dirs", None) or [])
        if library_dirs or runtime_library_dirs:
            raise RuntimeError(
                "TinyCC adapter rejects ambient library directories: "
                f"library_dirs={library_dirs!r}, runtime_library_dirs={runtime_library_dirs!r}"
            )

        output = Path(self.get_ext_fullpath(ext.name)).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        include_dirs: list[Path] = []
        for candidate in [
            *(getattr(ext, "include_dirs", None) or []),
            sysconfig.get_path("include"),
            sysconfig.get_path("platinclude"),
        ]:
            if not candidate:
                continue
            path = Path(candidate).resolve()
            if path not in include_dirs:
                include_dirs.append(path)
        for include_dir in include_dirs:
            text = str(include_dir).lower()
            if any(token in text for token in _FORBIDDEN_INCLUDE_TOKENS):
                raise RuntimeError(f"Forbidden host development include directory: {include_dir}")

        command: list[str] = [
            str(config.tcc),
            "-B" + str(config.root),
            "-shared",
            "-mms-bitfields",
            "-Wl,-dynamicbase",
            "-Wl,-high-entropy-va",
            "-Wl,-nxcompat",
            "-D__MINGW32__=1",
            "-DMS_WIN64=1",
            "-D__STDC_NO_COMPLEX__=1",
        ]
        if _header_supports_py_no_link_lib():
            command.append("-DPy_NO_LINK_LIB=1")

        for name, value in (getattr(ext, "define_macros", None) or []):
            command.append(f"-D{name}" if value is None else f"-D{name}={value}")
        for name in (getattr(ext, "undef_macros", None) or []):
            command.append(f"-U{name}")
        for include_dir in include_dirs:
            command.extend(["-I", str(include_dir)])

        command.extend(_translate_extra_args(getattr(ext, "extra_compile_args", None) or []))
        command.extend(str(source) for source in sources)
        command.append(str(config.python_def))
        command.extend(["-o", str(output)])

        rendered = subprocess.list2cmdline(command)
        lowered = rendered.lower()
        hit = [token for token in _FORBIDDEN_COMMAND_TOKENS if token in lowered]
        if hit:
            raise RuntimeError(f"Forbidden host compiler/development input reached TinyCC command: {hit}")
        if re.search(r"python3(?:12|13|14|15)(?:_d)?\.(?:lib|dll)", lowered):
            raise RuntimeError(f"Versioned Python library reached TinyCC command: {rendered}")

        _record(
            config,
            "compiler-commands.jsonl",
            {
                "extension": ext.name,
                "command": command,
                "output": str(output),
                "policy": config.policy_metadata(),
            },
        )
        subprocess.run(command, check=True, cwd=output.parent)
        if not output.is_file():
            raise RuntimeError(f"TinyCC did not produce expected extension: {output}")


@contextlib.contextmanager
def activate(config: TinyCCConfig) -> Iterator[None]:
    """Serialize and install the temporary CFFI Distribution interception."""

    global _ACTIVE_CONFIG, _ACTIVE_DEPTH, _ACTIVE_OWNER_THREAD, _ORIGINAL_DISTRIBUTION

    thread_id = threading.get_ident()
    with _ACTIVATION_LOCK:
        if _ACTIVE_CONFIG is not None and _ACTIVE_CONFIG != config:
            raise RuntimeError("Conflicting nested TinyCC activation is not permitted")
        if _ACTIVE_DEPTH and _ACTIVE_OWNER_THREAD != thread_id:
            # RLock serialization should make this unreachable; retain a hard invariant.
            raise RuntimeError("TinyCC activation ownership invariant violated")

        if _ACTIVE_DEPTH == 0:
            validate_cffi_integration()
            original_distribution = _dist.Distribution

            class TinyCCDistribution(original_distribution):
                def __init__(self, attrs=None):  # noqa: ANN001
                    owned = dict(attrs or {})
                    cmdclass = dict(owned.get("cmdclass") or {})
                    cmdclass["build_ext"] = TinyCCBuildExt
                    owned["cmdclass"] = cmdclass
                    super().__init__(owned)

                def parse_config_files(self, filenames=None, ignore_option_errors=False):  # noqa: ANN001
                    _record(
                        config,
                        "config-isolation.jsonl",
                        {
                            "filenames": [str(item) for item in filenames] if filenames else [],
                            "policy": EXTERNAL_CONFIG_POLICY_VERSION,
                        },
                    )
                    return []

            _ORIGINAL_DISTRIBUTION = original_distribution
            _dist.Distribution = TinyCCDistribution
            _ACTIVE_CONFIG = config
            _ACTIVE_OWNER_THREAD = thread_id
            _record(
                config,
                "activation.jsonl",
                {
                    "event": "activate",
                    "thread": thread_id,
                    "depth": 1,
                    "dependencies": _dependency_versions(),
                    "distribution_interception": "cffi._shimmed_dist_utils.Distribution",
                    "policy": config.policy_metadata(),
                },
            )

        _ACTIVE_DEPTH += 1
        if _ACTIVE_DEPTH > 1:
            _record(config, "activation.jsonl", {"event": "nest", "thread": thread_id, "depth": _ACTIVE_DEPTH})
        try:
            yield
        finally:
            _ACTIVE_DEPTH -= 1
            if _ACTIVE_DEPTH == 0:
                assert _ORIGINAL_DISTRIBUTION is not None
                _dist.Distribution = _ORIGINAL_DISTRIBUTION
                _record(config, "activation.jsonl", {"event": "deactivate", "thread": thread_id})
                _ORIGINAL_DISTRIBUTION = None
                _ACTIVE_CONFIG = None
                _ACTIVE_OWNER_THREAD = None
