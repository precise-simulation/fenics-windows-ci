#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "usage: $0 <overlay-zip> <arm64|x86_64> <evidence-dir>" >&2
    exit 2
fi

overlay_zip="$1"
target_arch="$2"
evidence_dir="$3"

case "$target_arch" in
    arm64)
        arch_flag=-arm64
        numpy_asset=numpy-2.5.2-cp312-cp312-macosx_14_0_arm64.whl
        numpy_url=https://files.pythonhosted.org/packages/f3/f4/29e78102a80601cf034d4e9767022cffeca2c3b4c926e1754572ca95593d/numpy-2.5.2-cp312-cp312-macosx_14_0_arm64.whl
        numpy_sha256=6e8172ddfcf5cf74b811d372b570b83c60bd2de87a6fbfbebdadb4a9bd9c6cbb
        ;;
    x86_64)
        arch_flag=-x86_64
        numpy_asset=numpy-2.5.2-cp312-cp312-macosx_14_0_x86_64.whl
        numpy_url=https://files.pythonhosted.org/packages/11/4b/dcd3b7eadaf4035d2c7a4289d232523a6964f602598ef7674e4bd7291f93/numpy-2.5.2-cp312-cp312-macosx_14_0_x86_64.whl
        numpy_sha256=65f188481f1669e26f62b701e8205d19e460fa4a9b52a1414ba382330e4a3414
        ;;
    *)
        echo "unsupported target architecture: $target_arch" >&2
        exit 2
        ;;
esac

python_version=3.12.10
python_asset=python-3.12.10-macos11.pkg
python_url="https://www.python.org/ftp/python/${python_version}/${python_asset}"
python_sha256=8373e58da4ea146b3eb1c1f9834f19a319440b6b679b06050b1f9ee3237aa8e4

[[ -f "$overlay_zip" ]] || { echo "overlay ZIP is missing: $overlay_zip" >&2; exit 1; }
overlay_zip="$(cd "$(dirname "$overlay_zip")" && pwd -P)/$(basename "$overlay_zip")"
mkdir -p "$evidence_dir"
evidence_dir="$(cd "$evidence_dir" && pwd -P)"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
base_temp="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
work="$base_temp/fenics overlay consumer $target_arch"
download_dir="$base_temp/fenics-consumer-download-$target_arch"
expanded_pkg="$base_temp/fenics-consumer-python-pkg-$target_arch"
runtime_root="$work/runtime with spaces"
baseline_json="$work/inherited-runtime-baseline.json"
poison_bin="$work/poison bin"
poison_lib="$work/poison lib"
clean_home="$work/clean home"
jit_cache="$work/jit cache with spaces"

rm -rf "$work" "$download_dir" "$expanded_pkg"
mkdir -p "$work" "$download_dir" "$runtime_root" "$poison_bin" "$poison_lib" "$clean_home" "$jit_cache"

python_pkg="$download_dir/$python_asset"
numpy_wheel="$download_dir/$numpy_asset"

curl --fail --location --retry 3 --retry-all-errors --output "$python_pkg" "$python_url"
actual_python_sha256="$(shasum -a 256 "$python_pkg" | awk '{print $1}')"
[[ "$actual_python_sha256" == "$python_sha256" ]] || {
    echo "CPython package SHA-256 mismatch: $actual_python_sha256 != $python_sha256" >&2
    exit 1
}
printf '%s  %s\n' "$actual_python_sha256" "$python_asset" > "$evidence_dir/consumer-python-sha256.txt"
pkgutil --check-signature "$python_pkg" > "$evidence_dir/consumer-python-signature.txt"

pkgutil --expand-full "$python_pkg" "$expanded_pkg"
framework="$(find "$expanded_pkg" -type d -path '*/Python_Framework.pkg/Payload' -print -quit)"
if [[ -z "$framework" || ! -d "$framework/Versions/3.12" ]]; then
    framework="$(find "$expanded_pkg" -type d -name Python.framework -print -quit)"
fi
[[ -n "$framework" && -d "$framework/Versions/3.12" ]] || {
    echo "could not locate Python.framework payload in expanded CPython package" >&2
    find "$expanded_pkg" -maxdepth 4 -type d -print >&2 || true
    exit 1
}
ditto "$framework" "$runtime_root/Python.framework"

python_exe="$runtime_root/Python.framework/Versions/3.12/bin/python3.12"
[[ -x "$python_exe" ]] || { echo "consumer CPython is missing: $python_exe" >&2; exit 1; }
/usr/bin/lipo -archs "$python_exe" | tee "$evidence_dir/consumer-python-architectures.txt"
/usr/bin/lipo -archs "$python_exe" | tr ' ' '\n' | grep -Fxq "$target_arch"

python_home="$runtime_root/Python.framework/Versions/3.12"
# The python.org executable carries framework install-name semantics.  Set the
# relocated framework search path after /usr/bin/arch starts so SIP cannot
# strip it from the target interpreter launch.
arch_cmd=(/usr/bin/arch "$arch_flag" /usr/bin/env
    "PYTHONHOME=$python_home"
    "DYLD_FRAMEWORK_PATH=$runtime_root")
"${arch_cmd[@]}" "$python_exe" -I - "$target_arch" "$runtime_root" <<'PY' | tee "$evidence_dir/consumer-python-runtime.txt"
from pathlib import Path
import platform
import sys

expected_arch = sys.argv[1]
root = Path(sys.argv[2]).resolve()
expected_prefix = (root / "Python.framework" / "Versions" / "3.12").resolve()
actual_prefix = Path(sys.prefix).resolve()
if platform.machine() != expected_arch:
    raise SystemExit(f"consumer Python architecture mismatch: {platform.machine()} != {expected_arch}")
if sys.version_info[:3] != (3, 12, 10):
    raise SystemExit(f"consumer Python version mismatch: {platform.python_version()} != 3.12.10")
if actual_prefix != expected_prefix:
    raise SystemExit(f"relocated consumer sys.prefix mismatch: {actual_prefix} != {expected_prefix}")
print(f"python_version={platform.python_version()}")
print(f"python_architecture={platform.machine()}")
print(f"python_prefix={actual_prefix}")
PY

curl --fail --location --retry 3 --retry-all-errors --output "$numpy_wheel" "$numpy_url"
actual_numpy_sha256="$(shasum -a 256 "$numpy_wheel" | awk '{print $1}')"
[[ "$actual_numpy_sha256" == "$numpy_sha256" ]] || {
    echo "NumPy wheel SHA-256 mismatch: $actual_numpy_sha256 != $numpy_sha256" >&2
    exit 1
}
printf '%s  %s\n' "$actual_numpy_sha256" "$numpy_asset" > "$evidence_dir/consumer-numpy-sha256.txt"

"${arch_cmd[@]}" "$python_exe" -I -m pip install \
    --disable-pip-version-check \
    --no-deps \
    --no-index \
    "$numpy_wheel" \
    > "$evidence_dir/consumer-numpy-install.log" 2>&1

"${arch_cmd[@]}" "$python_exe" -I - "$runtime_root" <<'PY' | tee "$evidence_dir/consumer-numpy-runtime.txt"
from pathlib import Path
import numpy
import platform
import sys

root = Path(sys.argv[1]).resolve()
site = (root / "Python.framework" / "Versions" / "3.12" / "lib" / "python3.12" / "site-packages").resolve()
module = Path(numpy.__file__).resolve()
if numpy.__version__ != "2.5.2":
    raise SystemExit(f"unexpected NumPy version: {numpy.__version__}")
if module != site and site not in module.parents:
    raise SystemExit(f"NumPy escaped consumer site-packages: {module}")
print(f"numpy_version={numpy.__version__}")
print(f"numpy_module={module}")
print(f"numpy_architecture={platform.machine()}")
PY

# Snapshot all inherited consumer files/symlinks before layering the overlay.
"${arch_cmd[@]}" "$python_exe" -I - "$runtime_root" "$baseline_json" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys

root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2])
entries = {}
for path in sorted(root.rglob("*")):
    rel = path.relative_to(root).as_posix()
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode):
        entries[rel] = {"type": "symlink", "target": os.readlink(path)}
    elif stat.S_ISREG(st.st_mode):
        entries[rel] = {
            "type": "file",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mode": stat.S_IMODE(st.st_mode),
        }
output.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"inherited_runtime_entries={len(entries)}")
PY
cp "$baseline_json" "$evidence_dir/inherited-runtime-baseline.json"

# The overlay may merge directories but must never replace a consumer-owned
# file or symlink.
"${arch_cmd[@]}" "$python_exe" -I - "$overlay_zip" "$runtime_root" <<'PY'
from pathlib import Path
import sys
import zipfile

archive = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
with zipfile.ZipFile(archive) as zf:
    for info in zf.infolist():
        rel = Path(info.filename)
        if rel.is_absolute() or ".." in rel.parts:
            raise SystemExit(f"unsafe overlay member: {info.filename}")
        dest = root / rel
        if info.is_dir():
            if dest.exists() and not dest.is_dir():
                raise SystemExit(f"overlay directory collides with inherited non-directory: {rel}")
            continue
        if dest.exists() or dest.is_symlink():
            raise SystemExit(f"overlay would overwrite inherited runtime path: {rel}")
print("overlay_overwrite_check=pass")
PY

ditto -x -k "$overlay_zip" "$runtime_root"
bootstrap="$runtime_root/Python.framework/Versions/3.12/lib/python3.12/site-packages/fenics_embed_runtime.py"
[[ -f "$bootstrap" ]] || { echo "overlay bootstrap is missing after staging" >&2; exit 1; }
[[ -x "$runtime_root/fenics-runtime/zig/zig" ]] || { echo "overlay Zig is missing after staging" >&2; exit 1; }

for name in cc clang clang++ c++ gcc g++ xcrun brew python python3 pkg-config cmake; do
    cat > "$poison_bin/$name" <<EOF_POISON
#!/usr/bin/env bash
echo "ambient tool invoked unexpectedly: $name" >&2
exit 97
EOF_POISON
    chmod +x "$poison_bin/$name"
done

export PATH="$poison_bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME="$clean_home"
export XDG_CACHE_HOME="$jit_cache"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$work/poison pythonpath"
export PYTHONUSERBASE="$work/poison userbase"
export DYLD_LIBRARY_PATH="$poison_lib"
export DYLD_FALLBACK_LIBRARY_PATH="$poison_lib"
unset CONDA_PREFIX CONDA_DEFAULT_ENV MAMBA_ROOT_PREFIX SDKROOT DEVELOPER_DIR \
    CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH ZIBRARY_PATH COMPILER_PATH \
    GCC_EXEC_PREFIX CC CXX CPP DLSHARED PETSC_DIR PETSC_ARCH

"${arch_cmd[@]}" "$python_exe" -I - \
    "$target_arch" "$runtime_root" "$repo_root/scripts/test-poisson.py" \
    "$evidence_dir/consumer-runtime.json" <<'PY' 2>&1 | tee "$evidence_dir/consumer-runtime.log"
from __future__ import annotations

import contextlib
import ctypes
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import runpy
import sys

expected_arch = sys.argv[1]
root = Path(sys.argv[2]).resolve()
poisson = Path(sys.argv[3]).resolve()
evidence = Path(sys.argv[4])

if platform.machine() != expected_arch:
    raise SystemExit(f"consumer execution architecture mismatch: {platform.machine()} != {expected_arch}")

import fenics_embed_runtime

first = Path(fenics_embed_runtime.activate()).resolve()
second = Path(fenics_embed_runtime.activate()).resolve()
if first != root or second != root:
    raise SystemExit(f"activation root mismatch: {first}, {second}, expected {root}")

import basix
import dolfinx
import ffcx
import mpi4py
from mpi4py import MPI
import numpy
import petsc4py
from petsc4py import PETSc
import ufl

versions = {
    "numpy": numpy.__version__,
    "dolfinx": dolfinx.__version__,
    "petsc4py": petsc4py.__version__,
    "mpi4py": mpi4py.__version__,
    "ffcx": ffcx.__version__,
    "basix": basix.__version__,
    "ufl": ufl.__version__,
}
expected_versions = {
    "numpy": "2.5.2",
    "dolfinx": "0.11.0",
    "petsc4py": "3.25.6",
    "mpi4py": "4.1.2",
    "ffcx": "0.11.0",
    "basix": "0.11.0",
    "ufl": "2026.1.0",
}
if versions != expected_versions:
    raise SystemExit(f"consumer stack version mismatch: {versions} != {expected_versions}")

private_prefix = (root / "fenics-runtime" / "conda").resolve()
consumer_site = (root / "Python.framework" / "Versions" / "3.12" / "lib" / "python3.12" / "site-packages").resolve()
module_paths = {}
for name, module in (
    ("numpy", numpy),
    ("dolfinx", dolfinx),
    ("petsc4py", petsc4py),
    ("mpi4py", mpi4py),
    ("ffcx", ffcx),
    ("basix", basix),
    ("ufl", ufl),
):
    path = Path(module.__file__).resolve()
    module_paths[name] = str(path)
    if name == "numpy":
        if path != consumer_site and consumer_site not in path.parents:
            raise SystemExit(f"NumPy is not consumer-owned: {path}")
        if path == private_prefix or private_prefix in path.parents:
            raise SystemExit(f"NumPy leaked from overlay prefix: {path}")
    elif path != private_prefix and private_prefix not in path.parents:
        raise SystemExit(f"{name} escaped private overlay prefix: {path}")

petsc_config = petsc4py.get_config()
if Path(petsc_config.get("PETSC_DIR", "")).resolve() != private_prefix or petsc_config.get("PETSC_ARCH", None) != "":
    raise SystemExit(f"petsc4py configuration did not relocate: {petsc_config}")

cc = Path(os.environ.get("CC", "")).resolve()
zig = Path(os.environ.get("FENICS_ZIG_EXE", "")).resolve()
if not cc.is_file():
    raise SystemExit(f"generated Zig compiler shim is missing: {cc}")
# The generated shim deliberately lives in a whitespace-safe temporary
# directory, not inside the relocated runtime path.
if cc == root or root in cc.parents:
    raise SystemExit(f"generated Zig compiler shim unexpectedly lives inside runtime: {cc}")
if zig != (root / "fenics-runtime" / "zig" / "zig").resolve():
    raise SystemExit(f"activation escaped bundled Zig: {zig}")

# Force PETSc/MPI initialization and a fresh FFCx JIT/solve.
PETSc.Sys.getVersion()
if MPI.COMM_SELF.Get_rank() != 0:
    raise SystemExit("unexpected MPI COMM_SELF rank")
stdout = io.StringIO()
with contextlib.redirect_stdout(stdout):
    runpy.run_path(str(poisson), run_name="__main__")
poisson_output = stdout.getvalue()
print(poisson_output, end="")
errors = re.findall(r"^L2 error:\s*([^\s]+)\s*$", poisson_output, flags=re.MULTILINE)
if len(errors) != 1:
    raise SystemExit(f"expected exactly one L2 error line, got {errors}")
l2_error = float(errors[0])
if not math.isfinite(l2_error) or l2_error < 0.0 or l2_error >= 0.01:
    raise SystemExit(f"Poisson L2 error outside qualified bound: {l2_error}")

# Enumerate already-loaded Mach-O images and prove PETSc/MPI providers are the
# private overlay closure rather than Homebrew or another ambient installation.
process = ctypes.CDLL(None)
process._dyld_image_count.restype = ctypes.c_uint32
process._dyld_get_image_name.argtypes = [ctypes.c_uint32]
process._dyld_get_image_name.restype = ctypes.c_char_p
images = []
for index in range(process._dyld_image_count()):
    raw = process._dyld_get_image_name(index)
    if raw:
        images.append(raw.decode("utf-8", errors="surrogateescape"))
provider_images = {
    "petsc": [path for path in images if "libpetsc" in Path(path).name.lower()],
    "mpi": [path for path in images if Path(path).name.lower().startswith(("libmpi", "libmpich"))],
}
for label, paths in provider_images.items():
    if not paths:
        raise SystemExit(f"no loaded {label} provider image was observed")
    for raw in paths:
        path = Path(raw).resolve()
        if path != private_prefix and private_prefix not in path.parents:
            raise SystemExit(f"loaded {label} provider escaped overlay prefix: {path}")

record = {
    "status": "pass",
    "python": platform.python_version(),
    "architecture": platform.machine(),
    "activation_root": str(first),
    "versions": versions,
    "module_paths": module_paths,
    "petsc_config": petsc_config,
    "cc": str(cc),
    "zig": str(zig),
    "l2_error": l2_error,
    "provider_images": provider_images,
}
evidence.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(record, sort_keys=True))
PY

jit_modules="$evidence_dir/jit-modules.txt"
find "$jit_cache" -type f -name '*.so' -print | sort > "$jit_modules"
if [[ ! -s "$jit_modules" ]]; then
    echo "fresh consumer FFCx JIT produced no Mach-O extension modules" >&2
    exit 1
fi

while IFS= read -r module; do
    /usr/bin/file "$module" | tee -a "$evidence_dir/jit-mach-o.txt"
    /usr/bin/file "$module" | grep -q "$target_arch"
    /usr/bin/otool -L "$module" | tee -a "$evidence_dir/jit-otool-L.txt"
    if /usr/bin/otool -L "$module" | grep -E '/opt/homebrew|/usr/local|Cellar|/Users/'; then
        echo "fresh JIT module links to a forbidden ambient path: $module" >&2
        exit 1
    fi
    minos="$(/usr/bin/otool -l "$module" | awk '$1 == "minos" {print $2; exit}')"
    [[ "$minos" == 14.0 ]] || {
        echo "fresh JIT module has unexpected macOS minimum $minos: $module" >&2
        exit 1
    }
done < "$jit_modules"

# Re-check every inherited file/symlink byte and mode after overlay activation,
# imports and JIT execution. New overlay/cache files are intentionally ignored.
"${arch_cmd[@]}" "$python_exe" -I - "$runtime_root" "$baseline_json" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys

root = Path(sys.argv[1]).resolve()
baseline = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
for rel, expected in baseline.items():
    path = root / rel
    if not path.exists() and not path.is_symlink():
        raise SystemExit(f"inherited runtime path disappeared: {rel}")
    st = path.lstat()
    if expected["type"] == "symlink":
        if not stat.S_ISLNK(st.st_mode) or os.readlink(path) != expected["target"]:
            raise SystemExit(f"inherited runtime symlink changed: {rel}")
    elif expected["type"] == "file":
        if not stat.S_ISREG(st.st_mode):
            raise SystemExit(f"inherited runtime file changed type: {rel}")
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        actual_mode = stat.S_IMODE(st.st_mode)
        if actual_sha != expected["sha256"] or actual_mode != expected["mode"]:
            raise SystemExit(f"inherited runtime file changed: {rel}")
print(f"inherited_runtime_preservation=pass entries={len(baseline)}")
PY

echo "public_consumer_overlay_qualification=pass"
