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

# --- win64 extras: ScaLAPACK + MUMPS (static, linked into libpetsc.dll) ---
# Sources are fetched here rather than as extra recipe sources: rattler
# extracts every source into the same work dir and the MUMPS tarball's
# root-level files (LICENSE, ...) collide with PETSc's. Pinned sha256s,
# stdlib-only python.
scalapack_url="https://github.com/Reference-ScaLAPACK/scalapack/archive/refs/tags/v2.2.0.zip"
scalapack_sha="7652f8857bc9e9529fc635860bc0a7c0a787b35627d773b4eb96573773537a35"
mumps_url="https://mumps-solver.org/MUMPS_5.7.3.tar.gz"
mumps_sha="84a47f7c4231b9efdf4d4f631a2cae2bdd9adeaabc088261d15af040143ed112"

python - "$source_dir" "$scalapack_url" "$scalapack_sha" "$mumps_url" "$mumps_sha" <<'PY'
import hashlib, pathlib, sys, tarfile, urllib.request, zipfile

work = pathlib.Path(sys.argv[1])

def fetch(url, sha, name):
    dest = work / name
    if dest.exists():
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
    if h.hexdigest() != sha:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"sha256 mismatch for {url}")
    tmp.rename(dest)

fetch(sys.argv[2], sys.argv[3], "scalapack-2.2.0-src.zip")
fetch(sys.argv[4], sys.argv[5], "MUMPS_5.7.3.tar.gz")

if not (work / "scalapack-2.2.0").is_dir():
    with zipfile.ZipFile(work / "scalapack-2.2.0-src.zip") as z:
        z.extractall(work)
if not (work / "MUMPS_5.7.3").is_dir():
    with tarfile.open(work / "MUMPS_5.7.3.tar.gz") as t:
        t.extractall(work)
PY

# Toolchain notes (see repo README "MUMPS" section / spike evidence):
#   * flang needs flang-rt_win-64 or nothing Fortran links
#   * flang defaults to the static CRT; -fms-runtime-lib=dll keeps it /MD
#   * this CMake defaults empty-config Ninja builds to Debug (/MDd) which
#     breaks CRT consistency -> force Release everywhere, including inside
#     ScaLAPACK's nested BLACS/INSTALL configure (env vars propagate there,
#     -D flags do not)
#   * MSYS2_ARG_CONV_EXCL=* is set by build.bat: /nologo and /out: survive
export I_MPI_ROOT="$libprefix"
# archives carry their upstream top-level dirs, which is what the paths
# below expect
scalapack_dir="$source_dir/scalapack-2.2.0"
mumps_dir="$source_dir/MUMPS_5.7.3"

if [ ! -d "$scalapack_dir" ] || [ ! -d "$mumps_dir" ]; then
  echo "win64 extra sources missing after fetch (scalapack/mumps)" >&2; exit 1
fi

flangrt=$(ls "$BUILD_PREFIX"/Library/lib/clang/*/lib/x86_64-pc-windows-msvc/flang_rt.runtime.dynamic.lib 2>/dev/null | head -n1)
iomp5="$libprefix/lib/libiomp5md.lib"
for f in "$flangrt" "$iomp5"; do
  test -f "$f" || { echo "missing $f" >&2; exit 1; }
done

export FFLAGS="-fms-runtime-lib=dll"
export CFLAGS="-MD"
export CMAKE_BUILD_TYPE=Release
export CMAKE_POLICY_VERSION_MINIMUM=3.5
export CMAKE_GENERATOR=Ninja
# VS activation exports CMAKE_GENERATOR_PLATFORM=x64 and
# CMAKE_GENERATOR_TOOLSET=v143; Ninja rejects both
unset CMAKE_GENERATOR_PLATFORM CMAKE_GENERATOR_TOOLSET

# ScaLAPACK: bypass FindMPI on WIN32 (conda impi layout breaks its wrapper
# detection, and its Fortran try-compiles never wire impi.lib in). Static
# scalapack only needs MPI headers at compile time.
python - "$scalapack_dir/CMakeLists.txt" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1]); t = p.read_text()
old = "#set(MPI_COMPILER ${MPI_BASE_DIR}/bin/mpicc)\n\nfind_package(MPI)"
new = """#set(MPI_COMPILER ${MPI_BASE_DIR}/bin/mpicc)

if(WIN32)
   message(STATUS "WIN32 MPI bypass: using I_MPI_ROOT=$ENV{I_MPI_ROOT}")
   set(MPI_FOUND TRUE)
   set(MPI_INCLUDE_PATH "$ENV{I_MPI_ROOT}/include")
   include_directories(${MPI_INCLUDE_PATH})
else()
find_package(MPI)"""
assert old in t, "scalapack CMakeLists anchor not found"
t = t.replace(old, new, 1)
anchor = 'message(FATAL_ERROR "--> MPI Library NOT FOUND -- please set MPI_BASE_DIR accordingly --")\nendif()'
assert anchor in t, "scalapack endif anchor not found"
t = t.replace(anchor, anchor + "\nendif()", 1)
p.write_text(t)
PY

cmake -S "$scalapack_dir" -B "$scalapack_dir/build" -G Ninja \
  -DCMAKE_C_COMPILER=cl \
  -DCMAKE_Fortran_COMPILER=flang \
  -DBUILD_SHARED_LIBS=OFF \
  -DBUILD_TESTING=OFF \
  -DCMAKE_INSTALL_PREFIX="$source_dir/scalapack-install" \
  -DMPIEXEC_EXECUTABLE="$mpi_exec" \
  -DBLAS_LIBRARIES="$source_dir/openblas.lib" \
  -DLAPACK_LIBRARIES="$source_dir/openblas.lib"
cmake --build "$scalapack_dir/build" --target scalapack scalapack-F

# MUMPS: PORD ordering only for now (-Dmetis/-Dscotch can be added later);
# examples disabled; Windows mangling override removed so CDEFS=-DAdd_ wins
sed -i '/^\tcd examples; \$(MAKE) \(s\|d\|c\|z\|all\)$/d;' "$mumps_dir/Makefile"
sed -i 's/defined(UPPER) || defined(MUMPS_WIN32)/defined(UPPER)/g' \
  "$mumps_dir/src/mumps_c.c" "$mumps_dir/src/mumps_common.h"

cat > "$mumps_dir/Makefile.inc" <<EOF
PLAT    =
LIBEXT  = .lib
LIBEXT_SHARED = .so
SONAME  =
FPIC_OPT =
OUTC    = -o
OUTF    = -o
RM      = rm -f
CC      = clang
FC      = flang
FL      = flang
AR      = lib /nologo /out:
RANLIB  = /bin/true
LPORDDIR = \$(topdir)/PORD/lib/
IPORD    = -I\$(topdir)/PORD/include/
LPORD    = -L\$(LPORDDIR) -lpord\$(PLAT)
ORDERINGSF  = -Dpord
ORDERINGSC  = \$(ORDERINGSF)
LORDERINGS = \$(LPORD)
IORDERINGSF =
IORDERINGSC = \$(IPORD)
LAPACK = "$source_dir/openblas.lib"
SCALAP = "$scalapack_dir/build/lib/scalapack.lib" "$scalapack_dir/build/lib/scalapack-F.lib"
INCPAR  = -I"$mpi_include"
LIBPAR  = \$(SCALAP) "$mpi_lib/impi.lib" "$iomp5"
INCSEQ  =
LIBSEQ  =
LIBBLAS = \$(LAPACK)
LIBOTHERS =
CDEFS   = -DAdd_
OPTF    = -O2 -fms-runtime-lib=dll -fopenmp -I\$(topdir)
OPTC    = -O2 -D_MT -D_DLL -I.
OPTL    = -O2 -fms-runtime-lib=dll -fopenmp
INCS    = \$(INCPAR)
LIBS    = \$(LIBPAR)
LIBSEQNEEDED =
EOF

mkdir -p "$mumps_dir/include"
cp "$mumps_dir/src/mumps_int_def32_h.in" "$mumps_dir/include/mumps_int_def.h"

# minimal omp_lib module shim, built BEFORE mumps: conda-forge flang ships
# no omp_lib.mod, and -fopenmp activates `USE OMP_LIB` sentinels in MUMPS.
# Compiled inside $mumps_dir so the .mod files sit on the -I$(topdir) path.
cat > "$mumps_dir/omp_lib_shim.f90" <<'EOF'
module omp_lib_kinds
  use iso_c_binding, only: c_intptr_t, c_int
  implicit none
  integer(kind=c_int), parameter :: omp_lock_kind = c_intptr_t
  integer(kind=c_int), parameter :: omp_nest_lock_kind = c_intptr_t
end module omp_lib_kinds
module omp_lib
  use iso_c_binding, only: c_int
  use omp_lib_kinds
  implicit none
  interface
    subroutine omp_init_lock(s) bind(c, name="omp_init_lock")
      import :: omp_lock_kind
      integer(omp_lock_kind) :: s
    end subroutine omp_init_lock
    subroutine omp_destroy_lock(s) bind(c, name="omp_destroy_lock")
      import :: omp_lock_kind
      integer(omp_lock_kind) :: s
    end subroutine omp_destroy_lock
    subroutine omp_set_lock(s) bind(c, name="omp_set_lock")
      import :: omp_lock_kind
      integer(omp_lock_kind) :: s
    end subroutine omp_set_lock
    subroutine omp_unset_lock(s) bind(c, name="omp_unset_lock")
      import :: omp_lock_kind
      integer(omp_lock_kind) :: s
    end subroutine omp_unset_lock
    function omp_test_lock(s) bind(c, name="omp_test_lock")
      import :: omp_lock_kind, c_int
      logical(c_int) :: omp_test_lock
      integer(omp_lock_kind) :: s
    end function omp_test_lock
    function omp_get_thread_num() bind(c, name="omp_get_thread_num")
      import :: c_int
      integer(c_int) :: omp_get_thread_num
    end function omp_get_thread_num
    function omp_get_num_threads() bind(c, name="omp_get_num_threads")
      import :: c_int
      integer(c_int) :: omp_get_num_threads
    end function omp_get_num_threads
    function omp_get_max_threads() bind(c, name="omp_get_max_threads")
      import :: c_int
      integer(c_int) :: omp_get_max_threads
    end function omp_get_max_threads
    subroutine omp_set_num_threads(n) bind(c, name="omp_set_num_threads")
      import :: c_int
      integer(c_int), value :: n
    end subroutine omp_set_num_threads
    function omp_get_dynamic() bind(c, name="omp_get_dynamic")
      import :: c_int
      logical(c_int) :: omp_get_dynamic
    end function omp_get_dynamic
    subroutine omp_set_dynamic(d) bind(c, name="omp_set_dynamic")
      import :: c_int
      logical(c_int), value :: d
    end subroutine omp_set_dynamic
    function omp_get_nested() bind(c, name="omp_get_nested")
      import :: c_int
      logical(c_int) :: omp_get_nested
    end function omp_get_nested
    subroutine omp_set_nested(n) bind(c, name="omp_set_nested")
      import :: c_int
      logical(c_int), value :: n
    end subroutine omp_set_nested
    function omp_get_wtime() bind(c, name="omp_get_wtime")
      import :: c_int
      double precision :: omp_get_wtime
    end function omp_get_wtime
  end interface
end module omp_lib
EOF
(cd "$mumps_dir" && flang -c -O2 -fopenmp -fms-runtime-lib=dll omp_lib_shim.f90) || exit 1

make -C "$mumps_dir" -j"$cpu_count" d

# append the shim object to the fresh mumps_common archive
cp "$mumps_dir/lib/libmumps_common.lib" "$mumps_dir/lib/mc_tmp.lib"
lib /nologo /out:"$mumps_dir/lib/mc_merged.lib" \
  "$mumps_dir/lib/mc_tmp.lib" "$mumps_dir/omp_lib_shim.o"
mv -f "$mumps_dir/lib/mc_merged.lib" "$mumps_dir/lib/libmumps_common.lib"

# install into prefix so PETSc metadata references ${PREFIX}-relative paths;
# unprefixed names because -l<name> lookups expect no "lib" prefix on Windows
mkdir -p "$libprefix/include" "$libprefix/lib"
cp "$mumps_dir/include/dmumps_c.h" "$mumps_dir/include/mumps_compat.h" \
   "$mumps_dir/include/mumps_c_types.h" "$mumps_dir/include/mumps_int_def.h" \
   "$libprefix/include/"
cp "$mumps_dir/lib/libdmumps.lib"        "$libprefix/lib/dmumps.lib"
cp "$mumps_dir/lib/libmumps_common.lib"  "$libprefix/lib/mumps_common.lib"
cp "$mumps_dir/lib/libpord.lib"          "$libprefix/lib/pord.lib"
cp "$scalapack_dir/build/lib/scalapack.lib"   "$libprefix/lib/"
cp "$scalapack_dir/build/lib/scalapack-F.lib" "$libprefix/lib/"
# static flang runtime must ship inside prefix so petsc metadata stays
# ${PREFIX}-relative and consumers can relink
cp "$flangrt" "$libprefix/lib/"

# PETSc's framework refuses any FC-needing external package while
# --with-fc=0, twice: once in framework.py's serialEvaluation and again in
# package.py's consistencyChecks. ScaLAPACK/MUMPS arrive as prebuilt static
# archives (nothing Fortran is compiled by PETSc itself, their function
# checks only use Fortran-mangled names from C, and enabling FC would make
# PETSc parse ifort-built mpi.mod files flang cannot read) - exempt both
# packages from those checks.
python - "$source_dir/config/BuildSystem/config/framework.py" \
         "$source_dir/config/BuildSystem/config/package.py" <<'PY'
from pathlib import Path
import sys

edits = [
    ("framework.py",
     "and (self.argDB['with-fc'] == '0'): raise RuntimeError("
     "'Package '+child.package+' requested requires Fortran but compiler "
     "turned off.')",
     "and (self.argDB['with-fc'] == '0') and child.package not in "
     "('scalapack', 'mumps'): raise RuntimeError("
     "'Package '+child.package+' requested requires Fortran but compiler "
     "turned off.')"),
    ("package.py",
     "if 'FC'  in self.buildLanguages and not hasattr(self.compilers, 'FC'):",
     "if 'FC'  in self.buildLanguages and not hasattr(self.compilers, 'FC') "
     "and self.package not in ('scalapack', 'mumps'):"),
]
for arg, old, new in zip(sys.argv[1:], [e[1] for e in edits], [e[2] for e in edits]):
    p = Path(arg)
    t = p.read_text()
    n = t.count(old)
    assert n >= 1, f"anchor not found in {p.name}"
    # package.py has TWO copies of the FC gate (external + download paths)
    p.write_text(t.replace(old, new))
PY

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
  --with-mumps=1 \
  --with-mumps-include="$libprefix/include" \
  --with-mumps-lib="$libprefix/lib/dmumps.lib $libprefix/lib/mumps_common.lib \
$libprefix/lib/pord.lib $libprefix/lib/scalapack.lib \
$libprefix/lib/scalapack-F.lib $iomp5 $libprefix/lib/flang_rt.runtime.dynamic.lib \
$source_dir/openblas.lib" \
  --with-scalapack=1 \
  --with-scalapack-include="$libprefix/include" \
  --with-scalapack-lib="$libprefix/lib/scalapack.lib $libprefix/lib/scalapack-F.lib \
$libprefix/lib/flang_rt.runtime.dynamic.lib" \
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
test -f "$libprefix/include/dmumps_c.h"
for m in dmumps mumps_common pord scalapack scalapack-F; do
  test -f "$libprefix/lib/$m.lib" || { echo "missing $m.lib" >&2; exit 1; }
done
echo "Windows PETSc package layout and metadata checks passed"
