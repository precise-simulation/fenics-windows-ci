#!/usr/bin/env python3
"""Validate machine-readable support policy against live repository declarations."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "support-policy.json"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _minor_key(value: str) -> tuple[int, int]:
    major, minor = value.split(".", 1)
    return int(major), int(minor)


def _recipe_identity(text: str) -> tuple[str | None, int | None]:
    version_match = re.search(r'(?m)^\s*version:\s*"?([^"\s]+)"?\s*$', text)
    build_match = re.search(r"(?m)^\s*build:\s*(\d+)\s*$", text)
    version = version_match.group(1) if version_match else None
    build = int(build_match.group(1)) if build_match else None
    return version, build


def validate(root: Path = ROOT) -> list[str]:
    global ROOT, POLICY_PATH
    old_root, old_policy = ROOT, POLICY_PATH
    ROOT = root
    POLICY_PATH = ROOT / "config" / "support-policy.json"
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        errors: list[str] = []

        if policy.get("schema_version") != 1:
            errors.append("support-policy schema_version must be 1")

        python_policy = policy.get("python") or {}
        supported = list(python_policy.get("supported") or [])
        preview = list(python_policy.get("preview") or [])
        if not supported:
            errors.append("python.supported must not be empty")
        if len(supported) != len(set(supported)):
            errors.append("python.supported contains duplicates")
        if supported != sorted(supported, key=_minor_key):
            errors.append("python.supported must be sorted by minor version")
        overlap = sorted(set(supported) & set(preview), key=_minor_key)
        if overlap:
            errors.append(f"python supported/preview overlap: {overlap}")
        expected_next = None
        if supported:
            major, minor = _minor_key(supported[-1])
            expected_next = f"{major}.{minor + 1}"
            if python_policy.get("next_minor_candidate") != expected_next:
                errors.append(
                    f"python.next_minor_candidate must be {expected_next} for supported max {supported[-1]}"
                )

        jit = policy.get("jit") or {}
        backends = jit.get("backends") or {}
        default_backend = jit.get("default_backend")
        if default_backend not in backends:
            errors.append("jit.default_backend is not present in jit.backends")
        elif backends[default_backend].get("role") != "default":
            errors.append("jit.default_backend must have role=default")

        runtime_spec = jit.get("runtime_package") or {}
        runtime_recipe = _read("recipes/fenics-jit-runtime/recipe.yaml")
        runtime_version, _ = _recipe_identity(runtime_recipe)
        if runtime_version != str(runtime_spec.get("version")):
            errors.append(
                f"fenics-jit-runtime recipe version {runtime_version!r} != policy {runtime_spec.get('version')!r}"
            )

        recipe_map = {
            "micro-clang": "recipes/fenics-jit-micro-clang/recipe.yaml",
            "llvm-mingw": "recipes/fenics-jit-llvm-mingw/recipe.yaml",
            "tinycc": "recipes/fenics-jit-tinycc/recipe.yaml",
        }
        for backend, path in recipe_map.items():
            spec = backends.get(backend) or {}
            text = _read(path)
            version, build = _recipe_identity(text)
            if version != str(spec.get("version")):
                errors.append(f"{backend} recipe version {version!r} != policy {spec.get('version')!r}")
            if build != spec.get("build"):
                errors.append(f"{backend} recipe build {build!r} != policy {spec.get('build')!r}")

        tiny = backends.get("tinycc") or {}
        tiny_recipe = _read(recipe_map["tinycc"])
        revision = tiny.get("source_revision")
        if revision and f"tinycc_revision: {revision}" not in tiny_recipe:
            errors.append("TinyCC recipe source revision does not match policy")
        constraint = tiny.get("python_constraint")
        if constraint and f"- python {constraint}" not in tiny_recipe:
            errors.append("TinyCC runtime Python constraint does not match policy")
        if supported and expected_next:
            expected_constraint = f">={supported[0]},<{expected_next}"
            if constraint != expected_constraint:
                errors.append(
                    f"TinyCC python_constraint must be {expected_constraint} for the supported matrix"
                )
        if tiny.get("requires_python_gil") and "- python-gil" not in tiny_recipe:
            errors.append("TinyCC policy requires python-gil but recipe does not")
        tiny_adapter = _read("recipes/fenics-jit-tinycc/tinycc_adapter.py")
        if tiny.get("requires_python_gil") and "Py_GIL_DISABLED" not in tiny_adapter:
            errors.append("TinyCC GIL-only policy is not enforced by adapter")
        for version in supported:
            tag = version.replace(".", "")
            if f"python3{tag}" not in tiny_adapter:
                errors.append(f"TinyCC versioned-Python rejection policy is missing Python {version}")

        micro = backends.get("micro-clang") or {}
        dolfinx_recipe = _read("recipes/dolfinx/recipe.yaml")
        runtime_name = runtime_spec.get("name")
        runtime_version_policy = runtime_spec.get("version")
        if runtime_name and runtime_version_policy:
            runtime_pin = f"{runtime_name} =={runtime_version_policy}"
            if runtime_pin not in dolfinx_recipe:
                errors.append("DOLFINx JIT runtime dependency pin does not match policy")
        micro_pin = f"{micro.get('package')} =={micro.get('version')}"
        if micro_pin not in dolfinx_recipe:
            errors.append("DOLFINx default micro-Clang dependency pin does not match policy")

        micro_release = _read(".github/workflows/micro-clang-release.yml")
        package_file = re.search(r'(?m)^\s*PACKAGE_FILE:\s*"([^"]+)"', micro_release)
        expected_prefix = f"{micro.get('package')}-{micro.get('version')}-"
        expected_suffix = f"_{micro.get('build')}.conda"
        if not package_file or not (
            package_file.group(1).startswith(expected_prefix)
            and package_file.group(1).endswith(expected_suffix)
        ):
            errors.append("micro-clang release PACKAGE_FILE does not match policy")

        readme = _read("README.md")
        if supported:
            req = "- CPython " + ", ".join(supported[:-1]) + ", or " + supported[-1]
            statement = "Python " + ", ".join(supported[:-1]) + ", and " + supported[-1] + " are supported."
            if req not in readme:
                errors.append("README CPython requirements do not match python.supported")
            if statement not in readme:
                errors.append("README supported-Python statement does not match python.supported")

        abi3 = _read("scripts/test-python-abi3.ps1")
        if "config/support-policy.json" not in abi3.replace("\\", "/"):
            errors.append("test-python-abi3.ps1 must read config/support-policy.json")
        if "python.supported" not in abi3:
            errors.append("test-python-abi3.ps1 must derive versions from python.supported")

        optional_release = _read(".github/workflows/optional-jit-release.yml")
        if "config/support-policy.json" not in optional_release:
            errors.append("optional-jit-release must read config/support-policy.json")
        if "python.supported" not in optional_release:
            errors.append("optional-jit-release must derive its Python matrix from policy")
        if "ANACONDA_CHANNEL" not in optional_release:
            errors.append("optional-jit-release must derive its channel from policy")

        channel_test = _read(".github/workflows/channel-dep-test.yml")
        expected_matrix = 'python: [' + ", ".join(f'\"{v}\"' for v in supported) + "]"
        if expected_matrix not in channel_test:
            errors.append("channel-dep-test Python matrix does not match policy")

        tinycc_workflow = _read(".github/workflows/tinycc-jit.yml")
        for version in supported:
            expected = f'- python: "{version}"'
            if expected not in tinycc_workflow:
                errors.append(f"tinycc-jit is missing supported Python {version}")
            block = re.search(
                rf'- python: "{re.escape(version)}"\s+experimental:\s*(true|false)',
                tinycc_workflow,
            )
            if not block or block.group(1) != "false":
                errors.append(f"tinycc-jit Python {version} must be blocking")

        llvm_stage = _read("recipes/fenics-jit-llvm-mingw/stage-toolchain.ps1")
        llvm_test = _read("recipes/fenics-jit-llvm-mingw/test-package.bat")
        for version in supported:
            tag = version.replace(".", "")
            alias = f"libpython{tag}.a"
            if alias not in llvm_stage:
                errors.append(f"LLVM-MinGW stage is missing {alias}")
            if alias not in llvm_test:
                errors.append(f"LLVM-MinGW package test is missing {alias}")

        return errors
    finally:
        ROOT, POLICY_PATH = old_root, old_policy


def main() -> int:
    errors = validate()
    if errors:
        print("support-policy validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("support-policy validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
