#!/usr/bin/env python3
"""Decide which stages of the win-64 fenics stack need rebuilding.

Compares upstream releases against the published precise-simulation channel,
patches recipe version/sha256 when an update is needed, and emits plan.json.

Rebuild rules:
  - petsc rebuilds when upstream petsc != channel petsc (or --force)
  - petsc4py rebuilds when petsc rebuilt or its own version changed
  - dolfinx   rebuilds when either upstream dependency rebuilt/changed
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
import urllib.request

CHANNEL_USER = "precise-simulation"
RECIPES = pathlib.Path(__file__).resolve().parent.parent / "recipes"
ORDER = ["petsc", "petsc4py", "dolfinx"]


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


def upstream_version(name: str) -> str:
    if name in ("petsc", "petsc4py"):
        return http_json(f"https://pypi.org/pypi/{name}/json")["info"]["version"]
    # dolfinx: latest GitHub release tag (vX.Y.Z)
    tag = http_json("https://api.github.com/repos/fenics/dolfinx/releases/latest")["tag_name"]
    return tag.lstrip("v")


def vkey(v: str):
    """Sort key that understands 0.11.0 < 0.11.0.post0."""
    key = []
    for tok in re.findall(r"\d+|[a-z]+", v):
        key.append((1, int(tok), "") if tok.isdigit() else (0, 0, tok))
    return key


def channel_versions() -> dict[str, str | None]:
    # anaconda.org package names differ from our stage names for dolfinx
    channel_pkg = {"petsc": "petsc", "petsc4py": "petsc4py", "dolfinx": "fenics-dolfinx"}
    out = {}
    for name in ORDER:
        try:
            data = http_json(f"https://api.anaconda.org/package/{CHANNEL_USER}/{channel_pkg[name]}")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            out[name] = None
        else:
            versions = data["versions"]
            out[name] = max(versions, key=vkey) if versions else None
    return out


def read_recipe(name: str) -> tuple[str, str]:
    """Return (version, sha256) currently pinned in the recipe."""
    text = (RECIPES / name / "recipe.yaml").read_text(encoding="utf-8")
    ver = re.search(r'version:\s*"([^"]+)"', text).group(1)
    sha = re.search(r"sha256:\s*([0-9a-f]{64})", text).group(1)
    return ver, sha


def patch_recipe(name: str, new_version: str) -> None:
    """Update version + recomputed source sha256 inside recipe.yaml."""
    path = RECIPES / name / "recipe.yaml"
    text = path.read_text(encoding="utf-8")
    old_ver = re.search(r'version:\s*"([^"]+)"', text).group(1)

    if name == "dolfinx":
        url = f"https://github.com/fenics/dolfinx/archive/refs/tags/v{new_version}.tar.gz"
    else:
        url = f"https://pypi.org/packages/source/{name[0]}/{name}/{name}-{new_version}.tar.gz"

    # only redownload when the version actually changed
    sha = download_sha256(url) if new_version != old_ver else re.search(
        r"sha256:\s*([0-9a-f]{64})", text).group(1)

    text = re.sub(r'(version:\s*")([^"]+)(")', rf"\g<1>{new_version}\g<3>", text, count=1)
    text = re.sub(r"(sha256:\s*)([0-9a-f]{64})", rf"\g<1>{sha}", text, count=1)
    path.write_text(text, encoding="utf-8")
    print(f"[plan] {name}: recipe pinned to {new_version} (sha256 {sha[:12]}...)", file=sys.stderr)


def bump_build_number(name: str) -> None:
    path = RECIPES / name / "recipe.yaml"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"(\n\s+build:\s*)(\d+)", text)
    if m:  # simple context form (petsc4py/dolfinx use expressions; skip those)
        text = text[:m.start()] + m.group(1) + str(int(m.group(2)) + 1) + text[m.end():]
        path.write_text(text, encoding="utf-8")


def main() -> int:
    force_all = os.environ.get("FORCE_ALL", "").lower() in ("true", "1")

    chan = channel_versions()
    upstream = {name: upstream_version(name) for name in ORDER}
    print(f"[plan] upstream : {upstream}", file=sys.stderr)
    print(f"[plan] channel  : {chan}", file=sys.stderr)

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
        if needs and upstream[name] == rec_ver and (force_all or dirty or upstream[name] != chan[name]):
            bump_build_number(name)
        plan[name] = {"version": upstream[name], "rebuild": bool(needs)}
        dirty = dirty or needs

    pathlib.Path("plan.json").write_text(json.dumps(plan, indent=2))
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
