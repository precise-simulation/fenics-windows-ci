#!/usr/bin/env bash
# Windows PETSc build: native python + m2-bash + win32fe(MSVC) + Intel MPI + OpenBLAS.
set -euo pipefail

source_dir="${SRC_DIR:?SRC_DIR is not set}"
prefix="${PREFIX:?PREFIX is not set}"
build_prefix="${BUILD_PREFIX:?BUILD_PREFIX is not set}"

# rattler-build hands us backslash paths; everything downstream wants forward slashes
source_dir="${source_dir//\\//}"
prefix="${prefix//\\//}"
build_prefix="${build_prefix//\\//}"

# conda Windows layout: package files live under <PREFIX>/Library
libprefix="$prefix/Library"
mpi_include="$libprefix/include"
mpi_lib="$libprefix/lib"
mpi_exec="$libprefix/bin/mpiexec.exe"
cpu_count="${CPU_COUNT:-4}"

echo "source_dir=$source_dir"
echo "libprefix=$libprefix"

for path in \
  "$mpi_include/mpi.h" \
  "$mpi_lib/impi.lib" \
  "$mpi_exec" \
  "$libprefix/bin/openblas.dll"; do
  test -f "$path" || { echo "Missing Windows PETSc input: $path" >&2; exit 1; }
done

cd "$source_dir"
export PETSC_DIR="$source_dir"
export PETSC_ARCH=arch-conda-win64
export PATH="$libprefix/bin:$libprefix/lib:$PATH"
export OPENBLAS_NUM_THREADS=1

# --- OpenBLAS import library (package ships only the DLL) ---
python - "$libprefix/bin/openblas.dll" > openblas.def <<'PY'
import re, subprocess, sys
out = subprocess.check_output(["dumpbin", "/exports", sys.argv[1]], text=True)
syms = re.findall(r"^\s*\d+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+(\S+)\s*$", out, re.M)
print("EXPORTS")
print("\n".join(syms))
PY
lib /nologo /def:openblas.def /machine:x64 /out:openblas.lib

# --- configure via the win32fe wrappers ---
python ./configure \
  --with-cc="$PETSC_DIR/lib/petsc/bin/win32fe/win32fe.exe cl" \
  --with-ar="$PETSC_DIR/lib/petsc/bin/win32fe/win32fe.exe lib" \
  --with-ranlib="$build_prefix/Library/usr/bin/true.exe" \
  --with-cxx=0 \
  --with-fc=0 \
  --with-debugging=0 \
  --with-shared-libraries=1 \
  --with-scalar-type=real \
  --with-64-bit-indices=0 \
  --with-mpi=1 \
  --with-mpi-include="$mpi_include" \
  --with-mpi-lib="$mpi_lib/impi.lib" \
  --with-mpiexec="$mpi_exec -localonly" \
  --with-blaslapack-lib="$source_dir/openblas.lib" \
  --with-cuda=0 \
  --with-hdf5=0 \
  --with-fftw=0 \
  --with-x=0 \
  --with-ssl=0 \
  --prefix="$libprefix"

# msys sh eats backslashes in make recipes/lists; normalize separators
confdir="$PETSC_DIR/$PETSC_ARCH/lib/petsc/conf"
(cd "$PETSC_DIR" && PETSC_ARCH="$PETSC_ARCH" python config/gmakegen.py)
sed -i 's|\\|/|g' "$confdir/petscvariables" "$confdir/petscrules" "$confdir/files"

make MAKE_NP="$cpu_count"
make install

# --- packaging layout: DLL belongs in bin ---
mkdir -p "$libprefix/bin"
test -f "$libprefix/lib/libpetsc.dll"
mv "$libprefix/lib/libpetsc.dll" "$libprefix/bin/libpetsc.dll"

# --- rewrite absolute build paths out of installed metadata ---
source_win="$source_dir"
prefix_win="$libprefix"
build_prefix_win="$build_prefix"
python - "$libprefix" "$prefix" "$source_dir" "$source_win" "$build_prefix" "$build_prefix_win" "$prefix_win" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
values = []
for raw in sys.argv[2:]:
    fwd = raw.replace("\\", "/")
    bck = raw.replace("/", "\\")
    values.extend((raw, fwd, bck, bck.replace("\\", "\\\\")))
values = sorted({value for value in values if value}, key=len, reverse=True)
replacement = "${PREFIX}/Library"

for path in root.rglob("*"):
    if not path.is_file():
        continue
    try:
        data = path.read_bytes()
        if b"\0" in data:
            continue
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        continue
    updated = text
    for value in values:
        updated = updated.replace(value, replacement)
    if updated != text:
        path.write_text(updated, encoding="utf-8")
PY

pc="$libprefix/lib/pkgconfig/PETSc.pc"
python - "$pc" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = []
for line in path.read_text(encoding="utf-8").splitlines():
    if line.startswith("prefix="):
        line = "prefix=${pcfiledir}/../.."
    elif line.startswith("exec_prefix="):
        line = "exec_prefix=${prefix}"
    elif line.startswith("includedir="):
        line = "includedir=${prefix}/include"
    elif line.startswith("libdir="):
        line = "libdir=${prefix}/lib"
    elif line.startswith("ccompiler="):
        line = "ccompiler=cl"
    elif line.startswith("cxxcompiler="):
        line = "cxxcompiler=cl"
    elif line.startswith("Cflags:"):
        line += " -Zc:preprocessor"
    elif line.startswith("mpiexec="):
        line = "mpiexec=mpiexec.exe -localonly"
    elif line.startswith("Libs.private:"):
        # libpetsc.dll already links impi/openblas at runtime, and neither
        # ships an import library consumers could resolve - drop them
        def keep(field):
            base = field.replace("\\", "/").split("/")[-1].strip('"').lower()
            return base not in ("impi.lib", "openblas.lib")
        line = " ".join(field for field in line.split() if keep(field))
    lines.append(line)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

rm -f "$libprefix/lib/petsc/conf/configure-hash"
find "$libprefix/lib/petsc" -name '*.pyc' -delete
rm -rf "$libprefix/share/petsc/examples/src" "$libprefix/share/petsc/datafiles"

# --- verify no build-prefix leakage remains ---
python - "$libprefix" "$prefix" "$source_dir" "$source_win" "$build_prefix" "$build_prefix_win" "$prefix_win" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
values = []
for raw in sys.argv[2:]:
    fwd = raw.replace("\\", "/")
    bck = raw.replace("/", "\\")
    values.extend((raw, fwd, bck, bck.replace("\\", "\\\\")))
values = [value for value in set(values) if value]
leaks = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    try:
        data = path.read_bytes()
        if b"\0" in data:
            continue
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        continue
    if any(value in text for value in values):
        leaks.append(str(path))
if leaks:
    print("Unremoved source/build-prefix metadata:", *leaks, sep="\n", file=sys.stderr)
    raise SystemExit(1)
PY

python - "$pc" <<'PY'
from pathlib import Path
import sys

line = next(line for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
            if line.startswith("Libs.private:"))
fields = line.split()[1:]
bad = [f for f in fields
       if f.replace("\\", "/").split("/")[-1].strip('"').lower() in ("impi.lib", "openblas.lib")]
if bad:
    raise SystemExit(f"PETSc.pc retains unresolvable import-library names: {bad}")
PY

test -f "$libprefix/include/petsc.h"
test -f "$libprefix/lib/libpetsc.lib"
test -f "$libprefix/bin/libpetsc.dll"
test -f "$libprefix/lib/pkgconfig/PETSc.pc"
echo "Windows PETSc package layout and metadata checks passed"
