#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "usage: $0 --phase03-runtime <runtime> --overlay <zip> --arch <arm64|x86_64> --evidence <dir>" >&2
    exit 2
}

phase03_runtime=""
overlay=""
target_arch=""
evidence=""
while (($#)); do
    case "$1" in
        --phase03-runtime) phase03_runtime="$2"; shift 2 ;;
        --overlay) overlay="$2"; shift 2 ;;
        --arch) target_arch="$2"; shift 2 ;;
        --evidence) evidence="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "unknown argument: $1" >&2; usage ;;
    esac
done

[[ "$target_arch" == arm64 || "$target_arch" == x86_64 ]] || usage
[[ -d "$phase03_runtime" && -f "$overlay" && -n "$evidence" ]] || usage

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
phase03_runtime="$(cd "$phase03_runtime" && pwd -P)"
overlay="$(cd "$(dirname "$overlay")" && pwd -P)/$(basename "$overlay")"
evidence="$(python3 - "$evidence" <<'PY'
import pathlib, sys
print(pathlib.Path(sys.argv[1]).resolve(strict=False))
PY
)"
mkdir -p "$evidence"

case "$target_arch" in
    arm64)
        expected_mex_sha=23f172fb23db8cd599891246683a72ef343ac8717799a2c7a661c3f7babbc60e
        expected_core_shared_map_sha=8fbb6dffb90498c7099ab1e9e1f0db697a5c5814f178c8a860e1661b1d2383df
        expected_numpy_payload_map_sha=d7a840c84cd5d4219478d931a683ef924f265d68c2d0a6e6f49a2fa0c3f41445
        expected_lock_sha=566b1f9fd653871bbac8ba535ff75719cce74a43acc7fcca2f114869a5dc0944
        expected_zig_sha=3cc2bab367e185cdfb27501c4b30b1b0653c28d9f73df8dc91488e66ece5fa6b
        ;;
    x86_64)
        expected_mex_sha=188bc10b098e96ceb7791acd68953375d026fb0fa476fb079e0032b76d2bc50c
        expected_core_shared_map_sha=575cacd0081f3d303c041c8ae1862c095b8fd52cd519be1a7ce75a467f04a370
        expected_numpy_payload_map_sha=b35e3f59780f77e7130b2f2a73fcaac6480230d2ef0af06b75d19fbe26aa3ca6
        expected_lock_sha=34941247f237f6e36a564422860f27138e44dd6b0d20726e253aa2d5b2fb58a6
        expected_zig_sha=375b6909fc1495d16fc2c7db9538f707456bfc3373b14ee83fdd3e22b3d43f7f
        ;;
esac

work="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/fenics overlay qualification ${target_arch}"
runtime="$work/runtime with spaces"
poison="$work/ambient poison"
cache="$work/jit cache with spaces"
rm -rf "$work"
mkdir -p "$work" "$poison" "$cache"
ditto "$phase03_runtime" "$runtime"

python3 - "$runtime" "$evidence/inherited-before.json" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1]).resolve()
output = pathlib.Path(sys.argv[2]).resolve()
entries = {}
for path in sorted(root.rglob("*")):
    rel = path.relative_to(root).as_posix()
    mode = oct(os.lstat(path).st_mode & 0o777)
    if path.is_symlink():
        target = os.readlink(path)
        entries[rel] = {
            "kind": "symlink",
            "mode": mode,
            "target": target,
            "sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
        }
    elif path.is_file():
        data = path.read_bytes()
        entries[rel] = {
            "kind": "file",
            "mode": mode,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
output.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

python3 - "$overlay" "$runtime" "$target_arch" "$expected_lock_sha" "$expected_zig_sha" \
    "$evidence/overlay-install.json" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys
import zipfile

archive_path = pathlib.Path(sys.argv[1]).resolve()
runtime = pathlib.Path(sys.argv[2]).resolve()
architecture, expected_lock_sha, expected_zig_sha = sys.argv[3:6]
evidence_path = pathlib.Path(sys.argv[6]).resolve()
summary_path = pathlib.Path(str(archive_path) + ".json")
if not summary_path.is_file():
    raise SystemExit(f"overlay outer summary is missing: {summary_path}")
summary = json.loads(summary_path.read_text(encoding="utf-8"))
archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
if summary.get("artifact") != archive_path.name or summary.get("sha256") != archive_sha:
    raise SystemExit("overlay outer summary archive identity mismatch")

def safe_path(value: str) -> pathlib.PurePosixPath:
    path = pathlib.PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "" in path.parts:
        raise SystemExit(f"unsafe overlay archive path: {value!r}")
    return path

with zipfile.ZipFile(archive_path) as archive:
    infos = archive.infolist()
    names = [item.filename for item in infos]
    if len(names) != len(set(names)):
        raise SystemExit("overlay archive contains duplicate paths")
    for info in infos:
        relative = safe_path(info.filename)
        target = runtime.joinpath(*relative.parts)
        if target.exists() or target.is_symlink():
            raise SystemExit(f"overlay would overwrite Phase-03 runtime path: {relative}")
        mode = (info.external_attr >> 16) & 0o177777
        data = archive.read(info)
        target.parent.mkdir(parents=True, exist_ok=True)
        if stat.S_ISLNK(mode):
            link = data.decode("utf-8")
            link_path = pathlib.Path(link)
            if link_path.is_absolute():
                raise SystemExit(f"unsafe overlay archive symlink: {relative} -> {link}")
            resolved_link = (target.parent / link_path).resolve(strict=False)
            try:
                resolved_link.relative_to(runtime)
            except ValueError as exc:
                raise SystemExit(f"overlay archive symlink escapes runtime: {relative} -> {link}") from exc
            os.symlink(link, target)
        else:
            target.write_bytes(data)
            target.chmod(mode & 0o777)

manifest_path = runtime / "fenics-embed-manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
if summary.get("manifest_sha256") != manifest_sha:
    raise SystemExit("overlay outer summary manifest identity mismatch")
if manifest.get("format_version") != 1 or manifest.get("architecture") != architecture:
    raise SystemExit("overlay manifest architecture/format mismatch")
if manifest.get("consumer_python") != "3.12.10" or manifest.get("python_abi") != "cp312":
    raise SystemExit("overlay manifest consumer CPython contract mismatch")
if manifest.get("numpy") != {
    "ownership": "bridge-phase03",
    "producer_payload_excluded": True,
    "version": "2.5.2",
}:
    raise SystemExit("overlay manifest NumPy ownership contract mismatch")
if manifest.get("producer", {}).get("package_lock_sha256") != expected_lock_sha:
    raise SystemExit("overlay manifest package-lock identity mismatch")
if manifest.get("zig", {}).get("sha256") != expected_zig_sha:
    raise SystemExit("overlay manifest Zig identity mismatch")

expected_paths = {entry["path"] for entry in manifest.get("files", [])}
expected_archive_paths = expected_paths | {"fenics-embed-manifest.json"}
if set(names) != expected_archive_paths:
    raise SystemExit(
        "overlay archive path set differs from manifest payload plus manifest self: "
        f"missing={sorted(expected_archive_paths - set(names))!r} "
        f"extra={sorted(set(names) - expected_archive_paths)!r}"
    )
for entry in manifest.get("files", []):
    path = runtime.joinpath(*safe_path(entry["path"]).parts)
    if entry["kind"] == "symlink":
        if not path.is_symlink():
            raise SystemExit(f"manifest symlink missing: {entry['path']}")
        data = os.readlink(path).encode("utf-8")
        mode = oct(os.lstat(path).st_mode & 0o777)
    else:
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"manifest file missing: {entry['path']}")
        data = path.read_bytes()
        mode = oct(path.stat().st_mode & 0o777)
    if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"] or mode != entry["mode"]:
        raise SystemExit(f"overlay manifest integrity mismatch: {entry['path']}")

evidence = {
    "format_version": 1,
    "architecture": architecture,
    "overlay_sha256": archive_sha,
    "manifest_sha256": manifest_sha,
    "manifest_file_count": len(expected_paths),
    "archive_path_set_check": "pass",
    "outer_summary_check": "pass",
    "overwrite_check": "pass",
    "integrity_check": "pass",
}
evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

python3 - "$runtime" "$evidence/inherited-before.json" "$expected_mex_sha" \
    "$expected_core_shared_map_sha" "$expected_numpy_payload_map_sha" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import sys

runtime = pathlib.Path(sys.argv[1]).resolve()
before = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
expected_mex_sha, expected_core_map, expected_numpy_map = sys.argv[3:]

for rel, entry in before.items():
    path = runtime.joinpath(*pathlib.PurePosixPath(rel).parts)
    mode = oct(os.lstat(path).st_mode & 0o777)
    if entry["kind"] == "symlink":
        if not path.is_symlink():
            raise SystemExit(f"inherited symlink changed type: {rel}")
        target = os.readlink(path)
        if mode != entry["mode"] or target != entry["target"]:
            raise SystemExit(f"inherited symlink changed: {rel}")
    else:
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"inherited file changed type: {rel}")
        data = path.read_bytes()
        if mode != entry["mode"] or len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise SystemExit(f"inherited file changed: {rel}")

if hashlib.sha256((runtime / "bridge.mex").read_bytes()).hexdigest() != expected_mex_sha:
    raise SystemExit("overlay changed the qualified bridge MEX")
provenance = json.loads((runtime / "build-provenance-macos.json").read_text(encoding="utf-8"))
manifest = json.loads((runtime / "numpy-payload-manifest-macos.json").read_text(encoding="utf-8"))
if provenance.get("core_shared_map_sha256") != expected_core_map:
    raise SystemExit("Phase-03 core shared-map identity changed")
if provenance.get("numpy", {}).get("payload_map_sha256") != expected_numpy_map:
    raise SystemExit("Phase-03 NumPy provenance identity changed")
if manifest.get("payload_file_count") != 923 or manifest.get("payload_map_sha256") != expected_numpy_map:
    raise SystemExit("Phase-03 NumPy payload-map identity changed")

site = runtime / "Python.framework/Versions/3.12/lib/python3.12/site-packages"
expected_paths = {item["path"] for item in manifest["files"]}
for item in manifest["files"]:
    path = site.joinpath(*pathlib.PurePosixPath(item["path"]).parts)
    if item["kind"] == "symlink":
        data = os.readlink(path).encode("utf-8")
        mode = oct(os.lstat(path).st_mode & 0o777)
    else:
        data = path.read_bytes()
        mode = oct(path.stat().st_mode & 0o777)
    if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"] or mode != item["mode"]:
        raise SystemExit(f"Phase-03 NumPy payload changed: {item['path']}")

def numpy_owned(relative: str) -> bool:
    return (
        relative.startswith("numpy/")
        or relative.startswith("numpy.libs/")
        or re.match(r"^numpy-[^/]+\.dist-info/", relative) is not None
    )

actual_numpy_paths = {
    path.relative_to(site).as_posix()
    for path in site.rglob("*")
    if (path.is_file() or path.is_symlink()) and numpy_owned(path.relative_to(site).as_posix())
}
if actual_numpy_paths != expected_paths:
    raise SystemExit(
        "Phase-03 NumPy payload path set changed: "
        f"missing={sorted(expected_paths - actual_numpy_paths)!r} "
        f"extra={sorted(actual_numpy_paths - expected_paths)!r}"
    )
print("phase03_inherited_runtime_identity_after_overlay=pass")
PY

for name in cc clang gcc xcrun brew python python3; do
    cat >"$poison/$name" <<EOF
#!/usr/bin/env bash
echo "ambient tool invoked unexpectedly: $name" >&2
exit 97
EOF
    chmod +x "$poison/$name"
done

runtime_python="$runtime/Python.framework/Versions/3.12/bin/python3.12"
test -x "$runtime_python"
python_cmd=("$runtime_python")
if [[ "$target_arch" == x86_64 ]]; then
    python_cmd=(/usr/bin/arch -x86_64 "$runtime_python")
fi

export PATH="$poison:/usr/bin:/bin"
export PYTHONPATH="$poison"
export PYTHONUSERBASE="$poison"
export PYTHONNOUSERSITE=1
export DYLD_LIBRARY_PATH="$poison"
export DYLD_FALLBACK_LIBRARY_PATH="$poison"
export XDG_CACHE_HOME="$cache"
unset PYTHONHOME SDKROOT DEVELOPER_DIR CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH LIBRARY_PATH COMPILER_PATH GCC_EXEC_PREFIX
unset CC CXX CPP LD LDSHARED PETSC_DIR FENICS_ZIG_EXE FENICS_ZIG_TARGET

"${python_cmd[@]}" -I -B - "$runtime" "$target_arch" <<'PY' 2>&1 | tee "$evidence/import.log"
from pathlib import Path
import json
import platform
import sys

runtime = Path(sys.argv[1]).resolve()
expected_arch = sys.argv[2]
assert platform.python_version() == "3.12.10", platform.python_version()
assert platform.machine() == expected_arch, (platform.machine(), expected_arch)

import fenics_embed_runtime
first = fenics_embed_runtime.activate()
second = fenics_embed_runtime.activate()
assert first == runtime == second, (first, runtime, second)

import basix
import dolfinx
import ffcx
import mpi4py
import numpy
import petsc4py
import ufl

bridge_site = runtime / "Python.framework/Versions/3.12/lib/python3.12/site-packages"
private_site = runtime / "fenics-runtime/conda/lib/python3.12/site-packages"
assert Path(numpy.__file__).resolve().is_relative_to(bridge_site), numpy.__file__
for module in (basix, dolfinx, ffcx, mpi4py, petsc4py, ufl):
    assert Path(module.__file__).resolve().is_relative_to(private_site), module.__file__
assert numpy.__version__ == "2.5.2"
assert dolfinx.__version__ == "0.11.0"
assert ffcx.__version__ == "0.11.0"
assert basix.__version__ == "0.11.0"
assert ufl.__version__ == "2026.1.0"
assert petsc4py.__version__ == "3.25.6"
assert mpi4py.__version__ == "4.1.2"
assert Path(petsc4py.get_config()["PETSC_DIR"]).resolve() == runtime / "fenics-runtime/conda"

print(json.dumps({
    "python": platform.python_version(),
    "architecture": platform.machine(),
    "numpy": numpy.__version__,
    "dolfinx": dolfinx.__version__,
    "petsc4py": petsc4py.__version__,
    "mpi4py": mpi4py.__version__,
    "ffcx": ffcx.__version__,
    "basix": basix.__version__,
    "ufl": ufl.__version__,
    "activation_root": str(first),
}, sort_keys=True))
print("macos_fenics_overlay_import=pass")
PY

# Execute the real acceptance fixture only after activation.  The wrapper is
# intentionally synthesized in a whitespace-safe temporary path while the
# runtime and cache themselves retain spaces.
solve_driver="$work/run-poisson.py"
cat >"$solve_driver" <<'PY'
from pathlib import Path
import runpy
import sys
import fenics_embed_runtime

root = fenics_embed_runtime.activate()
assert fenics_embed_runtime.activate() == root
runpy.run_path(sys.argv[1], run_name="__main__")
PY
"${python_cmd[@]}" -I -B "$solve_driver" "$repo_root/scripts/test-poisson.py" 2>&1 | tee "$evidence/poisson.log"
grep -Eq '^L2 error:' "$evidence/poisson.log"

find "$cache" -type f -name '*.so' -print | sort >"$evidence/jit-modules.txt"
test -s "$evidence/jit-modules.txt"
while IFS= read -r module; do
    file "$module" | tee -a "$evidence/jit-mach-o.txt"
    file "$module" | grep -q "$target_arch"
    otool -L "$module" | tee -a "$evidence/jit-otool-L.txt"
    if otool -L "$module" | grep -E '/opt/homebrew|/usr/local|Cellar|/Users/'; then
        echo "fresh JIT module links to forbidden ambient path: $module" >&2
        exit 1
    fi
    minos="$(otool -l "$module" | awk '$1 == "minos" {print $2; exit}')"
    test "$minos" = 14.0 || {
        echo "fresh JIT module has unexpected minimum macOS version: $module: $minos" >&2
        exit 1
    }
done <"$evidence/jit-modules.txt"

/usr/bin/python3 - "$runtime" "$evidence/inherited-before.json" <<'PY'
import hashlib
import json
import os
import pathlib
import sys

runtime = pathlib.Path(sys.argv[1]).resolve()
before = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
for rel, entry in before.items():
    path = runtime.joinpath(*pathlib.PurePosixPath(rel).parts)
    mode = oct(os.lstat(path).st_mode & 0o777)
    if entry["kind"] == "symlink":
        if not path.is_symlink() or os.readlink(path) != entry["target"] or mode != entry["mode"]:
            raise SystemExit(f"inherited runtime changed during overlay execution: {rel}")
    else:
        data = path.read_bytes()
        if mode != entry["mode"] or len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise SystemExit(f"inherited runtime changed during overlay execution: {rel}")
print("phase03_inherited_runtime_post_test_identity=pass")
PY

shasum -a 256 "$overlay" | tee "$evidence/overlay-sha256.txt"
echo "macos_fenics_embedded_runtime_overlay=pass"
