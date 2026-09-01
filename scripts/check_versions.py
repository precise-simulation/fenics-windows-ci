#!/usr/bin/env python3
"""Plan a win-64 FEniCS stack build from a conda-forge reference solve.

The Linux conda-forge DOLFINx solve is the dependency authority. Patch releases
inside the currently supported dependency families follow that solve exactly;
a major/minor family migration fails in preflight and requires an explicit
Windows-stack migration instead of silently continuing an obsolete family.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

CHANNEL_USER = "precise-simulation"
RECIPES = pathlib.Path(__file__).resolve().parent.parent / "recipes"
ORDER = ["hdf5", "petsc", "petsc4py", "dolfinx"]
CHANNEL_PACKAGE = {
    "hdf5": "hdf5",
    "petsc": "petsc",
    "petsc4py": "petsc4py",
    "dolfinx": "fenics-dolfinx",
}
WINDOWS_BUILD_NUMBER_OFFSET = {"hdf5": 0, "petsc": 0, "petsc4py": 0, "dolfinx": 100}
REFERENCE_KEYS = ("fenics-dolfinx", "petsc", "petsc4py", "slepc", "slepc4py", "hdf5", "mpi")


def http_json(url: str):
    headers = {"User-Agent": "fenics-windows-ci"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def download_sha256(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "fenics-windows-ci"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=300) as response:
        while chunk := response.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def vkey(version: str):
    key = []
    for token in re.findall(r"\d+|[a-z]+", version):
        key.append((1, int(token), "") if token.isdigit() else (0, 0, token))
    return key


def version_family(version: str) -> str:
    parts = version.split(".")
    if len(parts) < 2:
        raise RuntimeError(f"expected major.minor version, got {version!r}")
    return ".".join(parts[:2])


def load_reference(path: pathlib.Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("platform") != "linux-64":
        raise RuntimeError(f"unsupported reference stack metadata in {path}")
    packages = data.get("packages") or {}
    missing = [name for name in REFERENCE_KEYS if not (packages.get(name) or {}).get("version")]
    if missing:
        raise RuntimeError(f"reference stack missing package versions: {', '.join(missing)}")

    petsc_family = version_family(packages["petsc"]["version"])
    for name in ("petsc4py", "slepc", "slepc4py"):
        family = version_family(packages[name]["version"])
        if family != petsc_family:
            raise RuntimeError(
                f"reference PETSc family is incoherent: petsc={petsc_family}, {name}={family}"
            )
    return data


def latest_dolfinx_release() -> str:
    tag = http_json("https://api.github.com/repos/fenics/dolfinx/releases/latest")["tag_name"]
    return tag.lstrip("v")


def channel_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in ORDER:
        package = CHANNEL_PACKAGE[name]
        try:
            data = http_json(f"https://api.anaconda.org/package/{CHANNEL_USER}/{package}")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            out[name] = None
        else:
            versions = data["versions"]
            out[name] = max(versions, key=vkey) if versions else None
    return out


def channel_win64_max_build_number(name: str, version: str) -> int | None:
    package = CHANNEL_PACKAGE[name]
    encoded_version = urllib.parse.quote(version, safe="")
    url = f"https://api.anaconda.org/release/{CHANNEL_USER}/{package}/{encoded_version}"
    try:
        data = http_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise

    build_numbers = []
    for distribution in data.get("distributions", []):
        attrs = distribution.get("attrs") or {}
        if attrs.get("subdir") == "win-64" and isinstance(attrs.get("build_number"), int):
            build_numbers.append(attrs["build_number"])
    return max(build_numbers) if build_numbers else None


def read_recipe(name: str) -> tuple[str, str]:
    text = (RECIPES / name / "recipe.yaml").read_text(encoding="utf-8")
    version_match = re.search(r'version:\s*"([^"]+)"', text)
    sha_match = re.search(r"sha256:\s*([0-9a-f]{64})", text)
    if not version_match or not sha_match:
        raise RuntimeError(f"could not read version/sha256 from {name} recipe")
    return version_match.group(1), sha_match.group(1)


def source_url(name: str, version: str) -> str:
    if name == "dolfinx":
        return f"https://github.com/fenics/dolfinx/archive/refs/tags/v{version}.tar.gz"
    if name == "hdf5":
        major_minor = "_".join(version.split(".")[:2])
        return (
            f"https://support.hdfgroup.org/releases/hdf5/v{major_minor}/"
            f"downloads/hdf5-{version}.tar.gz"
        )
    return f"https://pypi.org/packages/source/{name[0]}/{name}/{name}-{version}.tar.gz"


def patch_recipe(name: str, new_version: str) -> None:
    path = RECIPES / name / "recipe.yaml"
    text = path.read_text(encoding="utf-8")
    old_match = re.search(r'version:\s*"([^"]+)"', text)
    sha_match = re.search(r"sha256:\s*([0-9a-f]{64})", text)
    if not old_match or not sha_match:
        raise RuntimeError(f"could not find version/sha256 in {path}")
    old_version = old_match.group(1)
    url = source_url(name, new_version)
    sha = download_sha256(url) if new_version != old_version else sha_match.group(1)

    if name == "hdf5":
        text = re.sub(r"(url:\s*)\S+", rf"\g<1>{url}", text, count=1)
    text = re.sub(r'(version:\s*")([^"]+)(")', rf"\g<1>{new_version}\g<3>", text, count=1)
    text = re.sub(r"(sha256:\s*)([0-9a-f]{64})", rf"\g<1>{sha}", text, count=1)
    path.write_text(text, encoding="utf-8")
    print(f"[plan] {name}: recipe pinned to {new_version} (sha256 {sha[:12]}...)", file=sys.stderr)


def patch_variant_value(recipe_name: str, key: str, value: str) -> None:
    path = RECIPES / recipe_name / "variants-win64.yaml"
    text = path.read_text(encoding="utf-8")
    pattern = rf"(?m)^({re.escape(key)}:\s*\n-\s*)([^\s#]+)"
    text, count = re.subn(pattern, rf"\g<1>{value}", text, count=1)
    if count != 1:
        raise RuntimeError(f"could not update {key!r} in {path}")
    path.write_text(text, encoding="utf-8")


def assert_supported_families(reference: dict) -> None:
    packages = reference["packages"]
    local_petsc = read_recipe("petsc")[0]
    local_petsc4py = read_recipe("petsc4py")[0]
    local_hdf5 = read_recipe("hdf5")[0]
    local_dolfinx = read_recipe("dolfinx")[0]

    checks = [
        ("PETSc", local_petsc, packages["petsc"]["version"]),
        ("petsc4py", local_petsc4py, packages["petsc4py"]["version"]),
        ("HDF5", local_hdf5, packages["hdf5"]["version"]),
        ("DOLFINx", local_dolfinx, packages["fenics-dolfinx"]["version"]),
    ]
    migrations = []
    for label, local_version, reference_version in checks:
        if version_family(local_version) != version_family(reference_version):
            migrations.append(
                f"{label}: Windows recipe family {version_family(local_version)} -> "
                f"conda-forge reference family {version_family(reference_version)}"
            )
    if migrations:
        raise RuntimeError(
            "conda-forge dependency-family migration detected; update the Windows recipes explicitly:\n  - "
            + "\n  - ".join(migrations)
        )


def assert_dolfinx_dependency_policy() -> None:
    text = (RECIPES / "dolfinx" / "recipe.yaml").read_text(encoding="utf-8")
    exact = re.findall(r"(?m)^\s*-\s+(petsc|petsc4py)\s+==([^\s]+)", text)
    if exact:
        raise RuntimeError(
            "DOLFINx recipe contains exact PETSc-family patch pins; dependency selection must "
            f"come from the reference solve/local channel instead: {exact!r}"
        )


def advance_build_number(name: str, published_build_number: int | None) -> None:
    path = RECIPES / name / "recipe.yaml"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^  build:\s*(\d+)\s*$", text)
    if not match:
        raise RuntimeError(f"could not find context build revision in {path}")
    current = int(match.group(1))
    offset = WINDOWS_BUILD_NUMBER_OFFSET[name]
    next_context = current + 1
    if published_build_number is not None:
        next_context = max(next_context, published_build_number - offset + 1)
    text = text[: match.start(1)] + str(next_context) + text[match.end(1) :]
    path.write_text(text, encoding="utf-8")
    print(
        f"[plan] {name}: context build {current} -> {next_context} "
        f"(win-64 build_number={next_context + offset}, published max={published_build_number})",
        file=sys.stderr,
    )


def print_parity(reference: dict, targets: dict[str, str]) -> None:
    packages = reference["packages"]
    print("Reference conda-forge stack (linux-64):", file=sys.stderr)
    for key in ("fenics-dolfinx", "petsc", "petsc4py", "slepc", "slepc4py", "hdf5", "mpi"):
        record = packages[key]
        build = record.get("build_string", "")
        print(f"  {key:14} {record['version']:12} {build}", file=sys.stderr)
    print("Windows build target:", file=sys.stderr)
    print(f"  {'fenics-dolfinx':14} {targets['dolfinx']}", file=sys.stderr)
    print(f"  {'petsc':14} {targets['petsc']}", file=sys.stderr)
    print(f"  {'petsc4py':14} {targets['petsc4py']}", file=sys.stderr)
    print(f"  {'hdf5':14} {targets['hdf5']}", file=sys.stderr)
    print(f"  {'mpi':14} impi (Windows-specific)", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", default="reference-stack.json")
    args = parser.parse_args()

    force_all = os.environ.get("FORCE_ALL", "").lower() in ("true", "1")
    reference = load_reference(pathlib.Path(args.reference))
    assert_supported_families(reference)
    assert_dolfinx_dependency_policy()

    packages = reference["packages"]
    latest_dolfinx = latest_dolfinx_release()
    if version_family(latest_dolfinx) != reference["dolfinx_family"]:
        raise RuntimeError(
            f"latest upstream DOLFINx {latest_dolfinx} is outside conda-forge reference family "
            f"{reference['dolfinx_family']}; wait for/perform the conda-forge migration first"
        )

    targets = {
        "hdf5": packages["hdf5"]["version"],
        "petsc": packages["petsc"]["version"],
        "petsc4py": packages["petsc4py"]["version"],
        "dolfinx": latest_dolfinx,
    }
    print_parity(reference, targets)

    # HDF5 is a variant input to downstream recipes, not just a source version.
    patch_variant_value("petsc", "hdf5", targets["hdf5"])
    patch_variant_value("dolfinx", "hdf5", targets["hdf5"])

    channel = channel_versions()
    print(f"[plan] targets : {targets}", file=sys.stderr)
    print(f"[plan] channel : {channel}", file=sys.stderr)

    plan: dict[str, dict] = {}
    dirty = False
    for name in ORDER:
        recipe_version, _ = read_recipe(name)
        needs = force_all or targets[name] != channel[name] or dirty

        if needs and targets[name] != recipe_version:
            patch_recipe(name, targets[name])

        if needs and targets[name] == channel[name]:
            advance_build_number(name, channel_win64_max_build_number(name, targets[name]))

        plan[name] = {"version": targets[name], "rebuild": bool(needs)}
        dirty = dirty or needs

    plan["reference"] = {
        "platform": reference["platform"],
        "dolfinx_family": reference["dolfinx_family"],
        "petsc_family": reference["petsc_family"],
        "packages": {key: packages[key]["version"] for key in REFERENCE_KEYS},
    }
    pathlib.Path("plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
