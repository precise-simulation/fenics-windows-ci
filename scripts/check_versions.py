#!/usr/bin/env python3
"""Decide which stages of the win-64 FEniCS stack need rebuilding.

Compares upstream releases against the published precise-simulation channel,
patches recipe version/sha256 when an update is needed, synchronizes exact
Windows PETSc-family pins used by downstream DOLFINx, and emits plan.json.

Rebuild rules:
  - hdf5 rebuilds when the latest compatible 1.14.x release != channel hdf5
    (or forced); HDF5 2.x requires an explicit stack migration
  - PETSc/petsc4py use the newest stable patch release published by both projects
  - petsc rebuilds when the selected pair != channel petsc (or forced)
  - petsc4py rebuilds when petsc rebuilt or its own channel version changed
  - dolfinx rebuilds when either upstream dependency rebuilt/changed

Windows stack invariants:
  - PETSc and petsc4py use the same selected patch release
  - every exact PETSc/petsc4py pin in the DOLFINx recipe is rewritten to that
    selected pair before any build starts
  - rebuilding an already-published package version uses a build number higher
    than every published win-64 distribution of that version
"""
from __future__ import annotations

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
# DOLFINx's real-scalar Windows output uses `build + 100`; the other Windows
# stage outputs use the context build revision directly.
WINDOWS_BUILD_NUMBER_OFFSET = {
    "hdf5": 0,
    "petsc": 0,
    "petsc4py": 0,
    "dolfinx": 100,
}
HDF5_SERIES = "1.14."
STABLE_PATCH_RE = re.compile(r"^\d+\.\d+\.\d+(?:\.post\d+)?$")
EXACT_PATCH_RE = r"\d+\.\d+\.\d+(?:\.post\d+)?"


def http_json(url: str):
    headers = {"User-Agent": "fenics-windows-ci"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def download_sha256(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "fenics-windows-ci"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=300) as r:
        while chunk := r.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def vkey(v: str):
    """Sort key that understands 0.11.0 < 0.11.0.post0."""
    key = []
    for tok in re.findall(r"\d+|[a-z]+", v):
        key.append((1, int(tok), "") if tok.isdigit() else (0, 0, tok))
    return key


def upstream_version(name: str) -> str:
    if name == "hdf5":
        data = http_json("https://api.anaconda.org/package/conda-forge/hdf5")
        versions = [v for v in data["versions"] if v.startswith(HDF5_SERIES)]
        if not versions:
            raise RuntimeError(f"No conda-forge HDF5 release found in {HDF5_SERIES}x")
        return max(versions, key=vkey)
    if name == "dolfinx":
        # latest stable GitHub release tag (vX.Y.Z[.postN])
        tag = http_json("https://api.github.com/repos/fenics/dolfinx/releases/latest")["tag_name"]
        return tag.lstrip("v")
    raise ValueError(f"upstream_version() does not select paired package {name!r}")


def pypi_stable_versions(name: str) -> set[str]:
    """Return stable, non-fully-yanked PyPI releases with downloadable files."""
    data = http_json(f"https://pypi.org/pypi/{name}/json")
    versions: set[str] = set()
    for version, files in data.get("releases", {}).items():
        if not STABLE_PATCH_RE.fullmatch(version) or not files:
            continue
        if any(not file_info.get("yanked", False) for file_info in files):
            versions.add(version)
    if not versions:
        raise RuntimeError(f"No usable stable PyPI releases found for {name}")
    return versions


def latest_matching_petsc_pair() -> str:
    """Select newest stable release present for both PETSc and petsc4py.

    PETSc and petsc4py may appear on PyPI at slightly different times. Treat
    that ordinary publication skew as a hold, not as a broken stack: keep using
    the newest common release until both packages publish the next patch.
    """
    petsc_versions = pypi_stable_versions("petsc")
    petsc4py_versions = pypi_stable_versions("petsc4py")
    common = petsc_versions & petsc4py_versions
    if not common:
        raise RuntimeError(
            "PETSc and petsc4py have no common usable stable PyPI release; "
            "cannot construct the Windows stack safely."
        )

    selected = max(common, key=vkey)
    petsc_latest = max(petsc_versions, key=vkey)
    petsc4py_latest = max(petsc4py_versions, key=vkey)
    if selected != petsc_latest or selected != petsc4py_latest:
        print(
            "[plan] PETSc release skew: "
            f"latest petsc={petsc_latest}, petsc4py={petsc4py_latest}; "
            f"holding stack at newest common release {selected}",
            file=sys.stderr,
        )
    return selected


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
    """Return highest published win-64 build number for one exact version."""
    package = CHANNEL_PACKAGE[name]
    encoded_version = urllib.parse.quote(version, safe="")
    url = f"https://api.anaconda.org/release/{CHANNEL_USER}/{package}/{encoded_version}"
    try:
        data = http_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise

    build_numbers: list[int] = []
    for distribution in data.get("distributions", []):
        attrs = distribution.get("attrs") or {}
        if attrs.get("subdir") != "win-64":
            continue
        build_number = attrs.get("build_number")
        if isinstance(build_number, int):
            build_numbers.append(build_number)
    return max(build_numbers) if build_numbers else None


def read_recipe(name: str) -> tuple[str, str]:
    """Return (version, sha256) currently pinned in the recipe."""
    text = (RECIPES / name / "recipe.yaml").read_text(encoding="utf-8")
    version_match = re.search(r'version:\s*"([^"]+)"', text)
    sha_match = re.search(r"sha256:\s*([0-9a-f]{64})", text)
    if not version_match or not sha_match:
        raise RuntimeError(f"Could not read version/sha256 from {name} recipe")
    return version_match.group(1), sha_match.group(1)


def patch_recipe(name: str, new_version: str) -> None:
    """Update version + recomputed source sha256 inside recipe.yaml."""
    path = RECIPES / name / "recipe.yaml"
    text = path.read_text(encoding="utf-8")
    old_match = re.search(r'version:\s*"([^"]+)"', text)
    if not old_match:
        raise RuntimeError(f"Could not find version in {path}")
    old_ver = old_match.group(1)

    if name == "dolfinx":
        url = f"https://github.com/fenics/dolfinx/archive/refs/tags/v{new_version}.tar.gz"
    elif name == "hdf5":
        major_minor = "_".join(new_version.split(".")[:2])
        url = (
            f"https://support.hdfgroup.org/releases/hdf5/v{major_minor}/"
            f"downloads/hdf5-{new_version}.tar.gz"
        )
    else:
        url = f"https://pypi.org/packages/source/{name[0]}/{name}/{name}-{new_version}.tar.gz"

    # Only redownload when the version actually changed.
    sha_match = re.search(r"sha256:\s*([0-9a-f]{64})", text)
    if not sha_match:
        raise RuntimeError(f"Could not find sha256 in {path}")
    sha = download_sha256(url) if new_version != old_ver else sha_match.group(1)

    if name == "hdf5":
        text = re.sub(r"(url:\s*)\S+", rf"\g<1>{url}", text, count=1)
    text = re.sub(r'(version:\s*")([^"]+)(")', rf"\g<1>{new_version}\g<3>", text, count=1)
    text = re.sub(r"(sha256:\s*)([0-9a-f]{64})", rf"\g<1>{sha}", text, count=1)
    path.write_text(text, encoding="utf-8")
    print(f"[plan] {name}: recipe pinned to {new_version} (sha256 {sha[:12]}...)", file=sys.stderr)


def sync_dolfinx_windows_petsc_pins(petsc_version: str, petsc4py_version: str) -> None:
    """Keep DOLFINx's exact Windows PETSc stack pins aligned with this run.

    Strict channel priority is intentional: downstream stages must consume the
    packages just built into output/. Consequently, leaving an older literal
    PETSc/petsc4py patch version in the DOLFINx recipe makes the solve
    unsatisfiable instead of falling back to a lower-priority channel.

    The replacement counts are deliberate guards. If the DOLFINx recipe is
    reorganized, fail here with a useful planner error rather than silently
    leaving one stale dependency behind and failing much later in rattler-build.
    """
    path = RECIPES / "dolfinx" / "recipe.yaml"
    text = path.read_text(encoding="utf-8")

    text, petsc_count = re.subn(
        rf"petsc =={EXACT_PATCH_RE}",
        f"petsc =={petsc_version}",
        text,
    )
    text, petsc4py_count = re.subn(
        rf"petsc4py =={EXACT_PATCH_RE}",
        f"petsc4py =={petsc4py_version}",
        text,
    )

    if petsc_count != 4 or petsc4py_count != 2:
        raise RuntimeError(
            "DOLFINx Windows PETSc pin layout changed: expected 4 PETSc and "
            f"2 petsc4py exact pins, found {petsc_count} and {petsc4py_count}. "
            "Update sync_dolfinx_windows_petsc_pins() with the recipe."
        )

    path.write_text(text, encoding="utf-8")
    print(
        f"[plan] dolfinx: Windows pins synced to petsc={petsc_version}, "
        f"petsc4py={petsc4py_version}",
        file=sys.stderr,
    )


def advance_build_number(name: str, published_build_number: int | None) -> None:
    """Set context build so the emitted win-64 build exceeds public channel."""
    path = RECIPES / name / "recipe.yaml"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^  build:\s*(\d+)\s*$", text)
    if not match:
        raise RuntimeError(
            f"Could not find two-space-indented context build revision in {path}; "
            "update advance_build_number() for the new recipe layout."
        )

    current_context_build = int(match.group(1))
    offset = WINDOWS_BUILD_NUMBER_OFFSET[name]
    next_context_build = current_context_build + 1
    if published_build_number is not None:
        next_context_build = max(next_context_build, published_build_number - offset + 1)

    text = (
        text[: match.start(1)]
        + str(next_context_build)
        + text[match.end(1) :]
    )
    path.write_text(text, encoding="utf-8")
    emitted_build_number = next_context_build + offset
    print(
        f"[plan] {name}: context build {current_context_build} -> {next_context_build} "
        f"(win-64 build_number={emitted_build_number}, published max={published_build_number})",
        file=sys.stderr,
    )


def main() -> int:
    force_all = os.environ.get("FORCE_ALL", "").lower() in ("true", "1")

    chan = channel_versions()
    petsc_pair = latest_matching_petsc_pair()
    upstream = {
        "hdf5": upstream_version("hdf5"),
        "petsc": petsc_pair,
        "petsc4py": petsc_pair,
        "dolfinx": upstream_version("dolfinx"),
    }
    print(f"[plan] upstream : {upstream}", file=sys.stderr)
    print(f"[plan] channel  : {chan}", file=sys.stderr)

    sync_dolfinx_windows_petsc_pins(upstream["petsc"], upstream["petsc4py"])

    plan: dict[str, dict] = {}
    dirty = False
    for name in ORDER:
        rec_ver, _ = read_recipe(name)
        needs = (
            force_all
            or upstream[name] != chan[name]
            or dirty  # downstream of a rebuilt stage always rebuilds
        )

        if needs and upstream[name] != rec_ver:
            patch_recipe(name, upstream[name])

        # If this exact package version already exists on the public channel,
        # the current run is a recipe-only/forced/downstream rebuild. Derive
        # the next build revision from the public win-64 distribution metadata,
        # not from potentially stale checked-in recipe state.
        if needs and upstream[name] == chan[name]:
            published_build_number = channel_win64_max_build_number(name, upstream[name])
            advance_build_number(name, published_build_number)

        plan[name] = {"version": upstream[name], "rebuild": bool(needs)}
        dirty = dirty or needs

    pathlib.Path("plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
