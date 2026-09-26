#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
    echo "usage: $0 <work-dir> <stage-dir> <evidence-dir>" >&2
    exit 2
fi

WORK="$(mkdir -p "$1" && cd "$1" && pwd)"
STAGE="$(mkdir -p "$2" && cd "$2" && pwd)"
EVIDENCE="$(mkdir -p "$3" && cd "$3" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

LLVM_MINGW_RELEASE=20260826
LLVM_MINGW_COMMIT=14614551fb5fc0f725933e4959c75c06d347acfa
LLVM_COMMIT=ea7d852a70e8bdfaf601d6626a760f9771b2c4b4
MINGW_W64_COMMIT=a3d708261d5ba659205067cb82cae36e7ae8bbb0
ARCHIVE="llvm-mingw-20260826-ucrt-x86_64.zip"
ARCHIVE_SHA256=ae601f4e0f72bbdf441ad2df8bb16f037e2e9251559ea6b37b4057aef39c06c3
ARCHIVE_URL="https://github.com/mstorsjo/llvm-mingw/releases/download/$LLVM_MINGW_RELEASE/$ARCHIVE"

rm -rf "$WORK/bootstrap" "$WORK/llvm-mingw" "$WORK/host-install" "$STAGE"
mkdir -p "$WORK/bootstrap" "$WORK/host-install" "$STAGE" "$EVIDENCE"

archive_path="$WORK/$ARCHIVE"
if [[ ! -f "$archive_path" ]]; then
    curl --fail --location --retry 3 --output "$archive_path" "$ARCHIVE_URL"
fi
actual_archive_sha="$(sha256sum "$archive_path" | awk '{print $1}')"
if [[ "$actual_archive_sha" != "$ARCHIVE_SHA256" ]]; then
    echo "bootstrap archive SHA-256 mismatch: expected $ARCHIVE_SHA256 got $actual_archive_sha" >&2
    exit 1
fi

unzip -q "$archive_path" -d "$WORK/bootstrap"
BOOTSTRAP="$WORK/bootstrap/llvm-mingw-$LLVM_MINGW_RELEASE-ucrt-x86_64"
if [[ ! -x "$BOOTSTRAP/bin/clang.exe" ]]; then
    echo "bootstrap clang is missing: $BOOTSTRAP/bin/clang.exe" >&2
    exit 1
fi

git init "$WORK/llvm-mingw"
git -C "$WORK/llvm-mingw" remote add origin https://github.com/mstorsjo/llvm-mingw.git
git -C "$WORK/llvm-mingw" fetch --depth 1 origin "$LLVM_MINGW_COMMIT"
git -C "$WORK/llvm-mingw" checkout --detach FETCH_HEAD
actual_llvm_mingw="$(git -C "$WORK/llvm-mingw" rev-parse HEAD)"
[[ "$actual_llvm_mingw" == "$LLVM_MINGW_COMMIT" ]]

LLVM_SRC="$WORK/llvm-mingw/llvm-project"
git init "$LLVM_SRC"
git -C "$LLVM_SRC" remote add origin https://github.com/llvm/llvm-project.git
git -C "$LLVM_SRC" config core.sparseCheckout true
cat > "$LLVM_SRC/.git/info/sparse-checkout" <<'EOF'
/llvm/
/clang/
/lld/
/cmake/
/third-party/
/compiler-rt/
/libunwind/
/libcxx/
/libcxxabi/
/runtimes/
/libc/
EOF
git -C "$LLVM_SRC" fetch --depth 1 origin "$LLVM_COMMIT"
git -C "$LLVM_SRC" checkout --detach FETCH_HEAD
actual_llvm="$(git -C "$LLVM_SRC" rev-parse HEAD)"
[[ "$actual_llvm" == "$LLVM_COMMIT" ]]

# LLVM 23's top-level configure always imports FindLibcCommonUtils, even when
# the libc project is disabled. Keep libc in the source checkout so configure
# can create the interface target; this does not enable or build LLVM libc.
if [[ ! -d "$LLVM_SRC/libc" ]]; then
    echo "LLVM libc source directory is required by LLVM 23 configure" >&2
    exit 1
fi

export PATH="$BOOTSTRAP/bin:$PATH"
export TOOLCHAIN_ARCHS=x86_64
# Keep the host C++ runtime shared, matching the Stage-AW Windows toolchain.
# The earlier forced-static experiment reproducibly made source-built llvm-ar
# and Clang treat ordinary ENOENT lookups as fatal across the LLVM/Clang DLL
# boundary. Stage-AW ships a shared libc++.dll/libunwind.dll closure, so Phase
# 1 should establish functionality with that model before any later size work.
export LLVM_CMAKEFLAGS="-DLLVM_TARGETS_TO_BUILD=X86 -DLLVM_INCLUDE_TESTS=OFF -DCLANG_INCLUDE_TESTS=OFF -DLLD_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_EXAMPLES=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF -DLLVM_ENABLE_ZLIB=OFF -DLLVM_ENABLE_ZSTD=OFF -DLLVM_ENABLE_LIBXML2=OFF -DLLVM_ENABLE_CURL=OFF -DLLVM_ENABLE_TERMINFO=OFF -DLLVM_ENABLE_LIBEDIT=OFF"

bootstrap_version="$("$BOOTSTRAP/bin/clang.exe" --version | tr '\n' ' ')"
cmake_version="$(cmake --version | head -n1)"
ninja_version="$(ninja --version)"
gcc_version="$(gcc --version | head -n1)"

pushd "$WORK/llvm-mingw" >/dev/null
./build-llvm.sh "$WORK/host-install" --with-clang --disable-lldb --disable-clang-tools-extra
popd >/dev/null

cp -a "$WORK/host-install/." "$STAGE/"

# Reproduce the llvm-mingw target wrapper contract from the exact Stage-AW
# build-script revision. The wrapper is a native Windows helper; GCC here is
# only the build-time bootstrap for that helper and is not shipped.
pushd "$WORK/llvm-mingw" >/dev/null
# Tell the upstream wrapper installer the native Windows host explicitly.
# Without --host it probes ./clang-$CLANG_MAJOR after the source install; the
# host install only guarantees clang.exe at this point, which caused exit 127.
if ! PATH="$STAGE/bin:$BOOTSTRAP/bin:$PATH" TOOLCHAIN_ARCHS=x86_64 TARGET_OSES=mingw32 CC=gcc \
    bash -x ./install-wrappers.sh --host=x86_64-w64-mingw32 "$STAGE" \
        > "$EVIDENCE/install-wrappers.log" 2>&1; then
    cat "$EVIDENCE/install-wrappers.log" >&2
    exit 1
fi

# A source-built llvm-ar that can create a previously nonexistent archive is
# an early sentinel for correct Windows error-category behavior in the host
# LLVM runtime. Do not mask this with external binutils: the same failure mode
# also breaks Clang header search when a candidate include path is absent.
cat > "$WORK/archive-smoke.c" <<'EOF'
int micro_clang_archive_smoke(void) { return 7; }
EOF
"$STAGE/bin/x86_64-w64-mingw32-clang.exe" -c "$WORK/archive-smoke.c" -o "$WORK/archive-smoke.o"
rm -f "$WORK/archive-smoke.a"
if ! "$STAGE/bin/llvm-ar.exe" rcs "$WORK/archive-smoke.a" "$WORK/archive-smoke.o"; then
    echo "source-built llvm-ar cannot create a new archive; host runtime linkage is not usable" >&2
    exit 1
fi
"$STAGE/bin/llvm-ranlib.exe" "$WORK/archive-smoke.a"
[[ -s "$WORK/archive-smoke.a" ]]

{
    echo "runtime-build ar:"
    "$STAGE/bin/llvm-ar.exe" --version
    echo
    echo "runtime-build ranlib:"
    "$STAGE/bin/llvm-ranlib.exe" --version
    echo
    echo "archive smoke:"
    ls -l "$WORK/archive-smoke.a"
} > "$EVIDENCE/archive-wrapper-preflight.txt" 2>&1

# Build mingw-w64 in the upstream runtime-build layout first. Upstream uses a
# relative symlink from x86_64-w64-mingw32/include to the generic header tree.
# On the GitHub Windows/MSYS2 runner that link is visible to MSYS tools but the
# native source-built Clang cannot reliably traverse it during CRT configure.
# Keep the same logical sysroot layout, but materialize that one target header
# tree as a physical copy for the runtime build. The duplicate is removed when
# the final Windows distribution layout is produced below.
python - "$WORK/llvm-mingw/build-mingw-w64.sh" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = """        if [ ! -e "$PREFIX/$arch-w64-mingw32/include" ]; then
            ln -sfn ../generic-w64-mingw32/include "$PREFIX/$arch-w64-mingw32/include"
        fi
"""
new = """        if [ ! -e "$PREFIX/$arch-w64-mingw32/include" ]; then
            mkdir -p "$PREFIX/$arch-w64-mingw32/include"
            cp -a "$PREFIX/generic-w64-mingw32/include/." "$PREFIX/$arch-w64-mingw32/include/"
        fi
"""
if text.count(old) != 1:
    raise SystemExit("unexpected build-mingw-w64.sh header-link block")
path.write_text(text.replace(old, new), encoding="utf-8")
PY
git diff -- build-mingw-w64.sh > "$EVIDENCE/llvm-mingw-local-build.patch"
local_patch_sha="$(sha256sum "$EVIDENCE/llvm-mingw-local-build.patch" | awk '{print $1}')"

if ! PATH="$STAGE/bin:$PATH" TOOLCHAIN_ARCHS=x86_64 \
    AR="$STAGE/bin/llvm-ar.exe" RANLIB="$STAGE/bin/llvm-ranlib.exe" \
    ./build-mingw-w64.sh "$STAGE" \
        --with-default-msvcrt=ucrt \
        --with-default-win32-winnt=0x601 \
        --enable-cfguard; then
    crt_config="$WORK/llvm-mingw/mingw-w64/mingw-w64-crt/build-x86_64/config.log"
    if [[ -f "$crt_config" ]]; then
        cp "$crt_config" "$EVIDENCE/mingw-w64-crt-config.log"
    fi
    exit 1
fi

# Fail immediately if the completed target sysroot is not usable by the exact
# source-built wrapper before starting compiler-rt/libc++.
cat > "$WORK/mingw-header-smoke.c" <<'EOF'
#include <windows.h>
#include <stdlib.h>
#include <xmmintrin.h>
int micro_clang_mingw_header_smoke(void) { return EXIT_SUCCESS; }
EOF
"$STAGE/bin/x86_64-w64-mingw32-clang.exe" -v -std=c17 -c \
    "$WORK/mingw-header-smoke.c" -o "$WORK/mingw-header-smoke.o" \
    > "$EVIDENCE/mingw-header-smoke.txt" 2>&1 || {
        cat "$EVIDENCE/mingw-header-smoke.txt" >&2
        exit 1
    }

actual_mingw="$(git -C "$WORK/llvm-mingw/mingw-w64" rev-parse HEAD)"
if [[ "$actual_mingw" != "$MINGW_W64_COMMIT" ]]; then
    echo "mingw-w64 revision mismatch: expected $MINGW_W64_COMMIT got $actual_mingw" >&2
    exit 1
fi

PATH="$STAGE/bin:$PATH" TOOLCHAIN_ARCHS=x86_64 \
    ./build-compiler-rt.sh "$STAGE" --enable-cfguard

# libunwind.a is part of the qualified C link model. Build the upstream
# runtime set from the same LLVM monorepo revision, static-only, then remove
# the C++ pieces after installation.
PATH="$STAGE/bin:$PATH" TOOLCHAIN_ARCHS=x86_64 \
    ./build-libcxx.sh "$STAGE" --enable-shared --enable-cfguard

# The source-built host Clang/LLVM DLLs use the shared libc++/libunwind model
# used by Stage-AW. During the runtime build they resolve the immutable
# bootstrap DLLs from PATH; replace that build-time dependency with the
# freshly source-built, same-revision runtime DLLs before packaging.
for host_runtime in libc++.dll libunwind.dll; do
    runtime_src="$STAGE/x86_64-w64-mingw32/bin/$host_runtime"
    if [[ ! -f "$runtime_src" ]]; then
        echo "source-built host runtime DLL is missing: $runtime_src" >&2
        exit 1
    fi
    cp "$runtime_src" "$STAGE/bin/$host_runtime"
done
popd >/dev/null

# Convert the successfully built upstream sysroot layout to the native Windows
# distribution layout used by Stage-AW: target headers live at root include/.
generic_include="$STAGE/generic-w64-mingw32/include"
if [[ ! -f "$generic_include/crtdefs.h" || ! -f "$generic_include/stdio.h" ]]; then
    echo "source-built mingw-w64 generic headers are missing" >&2
    exit 1
fi
mkdir -p "$STAGE/include"
cp -a "$generic_include/." "$STAGE/include/"
rm -rf "$STAGE/generic-w64-mingw32" "$STAGE/x86_64-w64-mingw32/include"
if [[ ! -f "$STAGE/include/crtdefs.h" || ! -f "$STAGE/include/stdio.h" ]]; then
    echo "packaged mingw-w64 root headers are missing" >&2
    exit 1
fi

rm -rf "$STAGE/include/c++" "$STAGE/share/libc++"
find "$STAGE/x86_64-w64-mingw32/lib" -maxdepth 1 -type f \
    \( -name 'libc++*.a' -o -name 'libc++abi*.a' \) -delete
find "$STAGE/x86_64-w64-mingw32/bin" -maxdepth 1 -type f \
    \( -name 'libc++*.dll' -o -name 'libunwind*.dll' \) -delete 2>/dev/null || true

resource_runtime="$STAGE/lib/clang/23/lib"
if [[ -d "$resource_runtime" ]]; then
    find "$resource_runtime" -type f ! -name 'libclang_rt.builtins-x86_64.a' -delete
    find "$resource_runtime" -depth -type d -empty -delete
fi

builtins="$STAGE/lib/clang/23/lib/windows/libclang_rt.builtins-x86_64.a"
unwind="$STAGE/x86_64-w64-mingw32/lib/libunwind.a"
for required in "$builtins" "$unwind" \
                "$STAGE/bin/clang-23.exe" \
                "$STAGE/bin/ld.lld.exe" \
                "$STAGE/bin/llvm-readobj.exe" \
                "$STAGE/bin/llvm-dlltool.exe" \
                "$STAGE/bin/libc++.dll" \
                "$STAGE/bin/libunwind.dll"; do
    if [[ ! -f "$required" ]]; then
        echo "required source-built toolchain file missing: $required" >&2
        exit 1
    fi
done

# Artifact transports do not consistently preserve Windows symlink semantics.
# Materialize the qualified target wrapper as a real executable.
target_clang="$STAGE/bin/x86_64-w64-mingw32-clang.exe"
if [[ -e "$target_clang" ]]; then
    cp -L "$target_clang" "$STAGE/bin/.micro-target-clang.exe"
    rm -f "$target_clang"
    mv "$STAGE/bin/.micro-target-clang.exe" "$target_clang"
else
    cp "$STAGE/bin/clang-target-wrapper.exe" "$target_clang"
fi

# Remove host executables not required by the FFCx JIT contract. Retain all
# host DLLs for the conservative Phase-1 closure; Phase 4 will minimize them
# only from measured evidence.
for exe in "$STAGE"/bin/*.exe; do
    name="$(basename "$exe")"
    case "$name" in
        clang-23.exe|x86_64-w64-mingw32-clang.exe|ld.lld.exe|llvm-readobj.exe|llvm-dlltool.exe)
            ;;
        *)
            rm -f "$exe"
            ;;
    esac
done

for required in \
    "$STAGE/bin/clang-23.exe" \
    "$STAGE/bin/x86_64-w64-mingw32-clang.exe" \
    "$STAGE/bin/ld.lld.exe" \
    "$STAGE/bin/llvm-readobj.exe" \
    "$STAGE/bin/llvm-dlltool.exe" \
    "$STAGE/bin/libc++.dll" \
    "$STAGE/bin/libunwind.dll"; do
    [[ -f "$required" ]]
done

cat > "$WORK/smoke.c" <<'EOF'
__declspec(dllexport) int micro_clang_smoke(void) { return 42; }
EOF
"$STAGE/bin/x86_64-w64-mingw32-clang.exe" -shared "$WORK/smoke.c" -o "$WORK/smoke.dll"
[[ -f "$WORK/smoke.dll" ]]

"$STAGE/bin/x86_64-w64-mingw32-clang.exe" --version > "$EVIDENCE/clang-version.txt"
"$STAGE/bin/x86_64-w64-mingw32-clang.exe" -dumpmachine > "$EVIDENCE/target.txt"
"$STAGE/bin/x86_64-w64-mingw32-clang.exe" -### -O2 -std=c17 -c "$WORK/smoke.c" -o "$WORK/smoke.obj" \
    > "$EVIDENCE/driver-defaults.txt" 2>&1 || {
        cat "$EVIDENCE/driver-defaults.txt" >&2
        exit 1
    }
"$STAGE/bin/ld.lld.exe" --version > "$EVIDENCE/lld-version.txt"

cmake_cache="$WORK/llvm-mingw/llvm-project/llvm/build-withclang/CMakeCache.txt"
if [[ -f "$cmake_cache" ]]; then
    cp "$cmake_cache" "$EVIDENCE/llvm-cmake-cache.txt"
fi

python - "$STAGE" "$EVIDENCE" "$actual_archive_sha" "$actual_llvm_mingw" "$actual_llvm" "$actual_mingw" \
    "$bootstrap_version" "$cmake_version" "$ninja_version" "$gcc_version" "$LLVM_CMAKEFLAGS" "$local_patch_sha" <<'PY'
import hashlib
import json
import pathlib
import sys

(stage_s, evidence_s, archive_sha, llvm_mingw, llvm, mingw, bootstrap, cmake, ninja, gcc, cmake_flags, local_patch_sha) = sys.argv[1:]
stage = pathlib.Path(stage_s)
evidence = pathlib.Path(evidence_s)

manifest = []
for path in sorted(p for p in stage.rglob("*") if p.is_file()):
    data = path.read_bytes()
    manifest.append(
        {
            "path": path.relative_to(stage).as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    )

total = sum(item["bytes"] for item in manifest)
(evidence / "retained-manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
provenance = {
    "schema": "fenics-jit-micro-clang-phase1-build-v1",
    "llvm_mingw_release": "20260826",
    "llvm_mingw_commit": llvm_mingw,
    "llvm_commit": llvm,
    "compiler_rt_commit": llvm,
    "mingw_w64_commit": mingw,
    "local_build_patches": {
        "llvm_mingw_build_mingw_w64_sha256": local_patch_sha,
        "reason": "materialize the x86_64 target include tree because native Windows Clang cannot reliably traverse the MSYS runtime-build symlink",
    },
    "mingw_w64_header_layout": "upstream triplet sysroot during runtime build with a physical x86_64 target include copy; converted to root include/ for Windows packaging",
    "runtime_build_header_flags": "none; source-built target wrapper uses triplet sysroot discovery",
    "runtime_build_preprocessor": "source-built target Clang wrapper",
    "bootstrap_archive_sha256": archive_sha,
    "runtime_build_archive_tools": "source-built LLVM llvm-ar/llvm-ranlib",
    "host_cxx_runtime_linkage": "shared source-built libc++/libunwind; Stage-AW-compatible host DLL model",
    "bootstrap_compiler": bootstrap.strip(),
    "cmake": cmake.strip(),
    "ninja": ninja.strip(),
    "wrapper_bootstrap_compiler": gcc.strip(),
    "llvm_cmake_flags": cmake_flags,
    "toolchain_archs": ["x86_64"],
    "host_projects": ["clang", "lld"],
    "installed_bytes": total,
    "installed_mib": round(total / (1024 * 1024), 4),
    "file_count": len(manifest),
    "runtime_policy": {
        "crt": "ucrt",
        "default_win32_winnt": "0x601",
        "cfguard": True,
        "rtlib": "compiler-rt",
        "unwindlib": "libunwind",
        "linker": "lld",
    },
}
(evidence / "build-provenance.json").write_text(
    json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(provenance, indent=2, sort_keys=True))
PY

# A source-built Stage-AW-matching payload must never contain the immutable
# binary reference archive or bootstrap path.
if grep -R -I -l -F "$BOOTSTRAP" "$STAGE" >/dev/null 2>&1; then
    echo "bootstrap path leaked into source-built stage" >&2
    exit 1
fi

echo "micro-Clang source toolchain built successfully"
echo "stage=$STAGE"
