#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "usage: $0 --bridge-repo <checkout> --arch <arm64|x86_64> --output-runtime <path> --evidence <dir>" >&2
    exit 2
}

bridge_repo=""
target_arch=""
output_runtime=""
evidence=""
while (($#)); do
    case "$1" in
        --bridge-repo) bridge_repo="$2"; shift 2 ;;
        --arch) target_arch="$2"; shift 2 ;;
        --output-runtime) output_runtime="$2"; shift 2 ;;
        --evidence) evidence="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "unknown argument: $1" >&2; usage ;;
    esac
done

[[ "$target_arch" == arm64 || "$target_arch" == x86_64 ]] || usage
[[ -d "$bridge_repo/.git" || -f "$bridge_repo/.git" ]] || { echo "bridge checkout is missing: $bridge_repo" >&2; exit 1; }
[[ -n "$output_runtime" && -n "$evidence" ]] || usage

qualified_revision=cf5fecea11bd1c727d8ff2d9fc5ea1b74d323d8d
bridge_repo="$(cd "$bridge_repo" && pwd -P)"
test "$(git -C "$bridge_repo" rev-parse HEAD)" = "$qualified_revision" || {
    echo "bridge checkout is not the exact qualified Phase-03 revision" >&2
    exit 1
}

output_runtime="$(python3 - "$output_runtime" <<'PY'
import pathlib, sys
print(pathlib.Path(sys.argv[1]).resolve(strict=False))
PY
)"
evidence="$(python3 - "$evidence" <<'PY'
import pathlib, sys
print(pathlib.Path(sys.argv[1]).resolve(strict=False))
PY
)"
mkdir -p "$evidence" "$(dirname "$output_runtime")"
rm -rf "$output_runtime"

case "$target_arch" in
    arm64)
        python_asset_id=244701302
        python_asset=python-3.12.10-darwin-arm64.tar.gz
        python_archive_sha=4b313adc4862a77522d3a4761461015548fe065866f417e9d0a5ee3aa8a981eb
        python_toolcache_arch=arm64
        wheel_name=numpy-2.5.2-cp312-cp312-macosx_14_0_arm64.whl
        wheel_url=https://files.pythonhosted.org/packages/f3/f4/29e78102a80601cf034d4e9767022cffeca2c3b4c926e1754572ca95593d/numpy-2.5.2-cp312-cp312-macosx_14_0_arm64.whl
        wheel_sha=6e8172ddfcf5cf74b811d372b570b83c60bd2de87a6fbfbebdadb4a9bd9c6cbb
        expected_mex_sha=23f172fb23db8cd599891246683a72ef343ac8717799a2c7a661c3f7babbc60e
        qualified_core_provenance_sha=cfe6d5746ec5c45272e33a318ef988b87b828e25ccabf89423d8e1d7bc08ca77
        expected_core_shared_map_sha=8fbb6dffb90498c7099ab1e9e1f0db697a5c5814f178c8a860e1661b1d2383df
        expected_numpy_payload_map_sha=d7a840c84cd5d4219478d931a683ef924f265d68c2d0a6e6f49a2fa0c3f41445
        qualified_numpy_provenance_sha=cb589f66692151c4f8dfcfcb36164ed8ecbdfc83f189e35708fbe9337f6ecd5b
        expected_numpy_manifest_sha=957e7dfb1e4a246ada9f2f9713ebf980de0301fa24476e8f48a92cface7347a0
        expected_numpy_native_census_sha=a4061c9932031270feeaa00bc986dcb8288c4e0ae740cc70cd1f0dc73ec45860
        expected_phase03_qualification_sha=dc6b848f2ec2e7fe6de9ad86f4f9bd0ec37d6c180b02f3ff651fa63f21cc0542
        ;;
    x86_64)
        python_asset_id=244701305
        python_asset=python-3.12.10-darwin-x64.tar.gz
        python_archive_sha=d6158059a6bdac75fcefc3052cef46c336575a36cd66600dd371ca76d4e43f73
        python_toolcache_arch=x64
        wheel_name=numpy-2.5.2-cp312-cp312-macosx_14_0_x86_64.whl
        wheel_url=https://files.pythonhosted.org/packages/11/4b/dcd3b7eadaf4035d2c7a4289d232523a6964f602598ef7674e4bd7291f93/numpy-2.5.2-cp312-cp312-macosx_14_0_x86_64.whl
        wheel_sha=65f188481f1669e26f62b701e8205d19e460fa4a9b52a1414ba382330e4a3414
        expected_mex_sha=188bc10b098e96ceb7791acd68953375d026fb0fa476fb079e0032b76d2bc50c
        qualified_core_provenance_sha=481bf49d641dad664064c528dcc5e9549c7f1c10a2db477520beb4dbce808873
        expected_core_shared_map_sha=575cacd0081f3d303c041c8ae1862c095b8fd52cd519be1a7ce75a467f04a370
        expected_numpy_payload_map_sha=b35e3f59780f77e7130b2f2a73fcaac6480230d2ef0af06b75d19fbe26aa3ca6
        qualified_numpy_provenance_sha=e13f92e14eb4c206156678ff236579bb6b857c08e98d32645d109be75b02972b
        expected_numpy_manifest_sha=45ceeeadb54e43969b74059bc1bba5dafe37a49b2334fb29f275257f99533801
        expected_numpy_native_census_sha=2edb07f2902aa79d2654ffbfb1342b302d59ff0b56c04aa6e520249face20570
        expected_phase03_qualification_sha=d7c496e29fd8518e79ca57abc40c66381a9f6eaa8e44365cb39567a8112bd2e2
        ;;
esac
expected_core_profile_sha=d1e6e9f24df974e4c75706d8dd4728911b230bb7162cdfe2689ef4b487263835
expected_staged_framework_sha=3b8548572d49de187aad18b0a176b6a5d204b64da623942e681e97ce85a525e0
expected_staged_executable_sha=564913c68be0bcbd38867413ea778df0290d25a443225ba1a66c3b62dc5daf50

work="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/bridge-phase03-${target_arch}"
rm -rf "$work"
mkdir -p "$work/assets" "$work/python-setup" "$work/toolcache" "$work/core-runtime"

python_archive="$work/assets/$python_asset"
python_hashes="$work/assets/hashes.sha256"
GH_TOKEN="${GH_TOKEN:-}" python3 - \
    "$python_asset_id" "$python_asset" "$python_archive" "$python_hashes" <<'PY'
import json
import os
import pathlib
import shutil
import sys
import urllib.request

archive_id = int(sys.argv[1])
archive_name = sys.argv[2]
archive_path = pathlib.Path(sys.argv[3])
hashes_path = pathlib.Path(sys.argv[4])
assets = {archive_id: (archive_name, archive_path), 244701301: ("hashes.sha256", hashes_path)}
token = os.environ.get("GH_TOKEN", "")
for asset_id, (expected_name, target) in assets.items():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "fenics-macos-overlay-producer",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/actions/python-versions/releases/assets/{asset_id}",
        headers=headers,
    )
    with urllib.request.urlopen(request) as response:
        metadata = json.load(response)
    if metadata.get("id") != asset_id or metadata.get("name") != expected_name:
        raise SystemExit(f"pinned CPython asset mismatch: {metadata!r}")
    url = metadata.get("browser_download_url")
    if not url:
        raise SystemExit(f"pinned CPython asset has no browser URL: {asset_id}")
    target.parent.mkdir(parents=True, exist_ok=True)
    download = urllib.request.Request(url, headers={"User-Agent": "fenics-macos-overlay-producer"})
    with urllib.request.urlopen(download) as response, target.open("wb") as stream:
        shutil.copyfileobj(response, stream)
PY

test "$(shasum -a 256 "$python_archive" | awk '{print $1}')" = "$python_archive_sha"
grep -F "$python_archive_sha" "$python_hashes" >/dev/null

tar -xzf "$python_archive" -C "$work/python-setup"
export AGENT_TOOLSDIRECTORY="$work/toolcache"
(cd "$work/python-setup" && bash ./setup.sh)
python_real="$AGENT_TOOLSDIRECTORY/Python/3.12.10/$python_toolcache_arch/bin/python3.12"
test -x "$python_real"
python_cmd="$python_real"
if [[ "$target_arch" == x86_64 ]]; then
    test "$(uname -m)" = arm64
    test "$(/usr/bin/arch -x86_64 /usr/bin/uname -m)" = x86_64
    python_cmd="$work/python3.12-x86_64"
    cat >"$python_cmd" <<EOF
#!/usr/bin/env bash
exec /usr/bin/arch -x86_64 "$python_real" "\$@"
EOF
    chmod +x "$python_cmd"
fi

"$python_cmd" -I - "$target_arch" <<'PY'
import platform, sys
expected = sys.argv[1]
assert platform.python_implementation() == "CPython"
assert platform.python_version() == "3.12.10"
assert platform.machine() == expected, (platform.machine(), expected)
print(f"bridge_phase03_python={sys.executable}")
print(f"bridge_phase03_python_architecture={platform.machine()}")
PY

pushd "$bridge_repo" >/dev/null
rm -rf build runtime
chmod +x \
    tools/build-macos.sh \
    tools/stage-macos-runtime.sh \
    tools/prepare-macos-release-runtime.sh \
    tools/stage-macos-numpy-runtime.sh

build_args=(--python "$python_cmd" --arch "$target_arch")
if [[ "$target_arch" == x86_64 ]]; then
    # Exact Phase-03 x86_64 qualification fixed the deployment target at 14.0.
    # Native arm64 qualification intentionally used the runner default and its
    # frozen MEX hash binds that different build invocation.
    build_args+=(--deployment-target 14.0)
fi
tools/build-macos.sh "${build_args[@]}" 2>&1 | tee "$evidence/bridge-build.log"
actual_mex_sha="$(shasum -a 256 build/macos-phase01/bridge.mex | awk '{print $1}')"
test "$actual_mex_sha" = "$expected_mex_sha" || {
    echo "qualified Phase-03 MEX identity drifted: $actual_mex_sha != $expected_mex_sha" >&2
    exit 1
}

tools/stage-macos-runtime.sh \
    --python "$python_cmd" \
    --python-archive "$python_archive" \
    --python-hashes "$python_hashes" \
    --arch "$target_arch" \
    2>&1 | tee "$evidence/core-staging.log"
tools/prepare-macos-release-runtime.sh \
    --runtime runtime \
    --expected-mex-sha "$expected_mex_sha" \
    --arch "$target_arch" \
    --census-output "$evidence/prepared-runtime-census.json" \
    2>&1 | tee "$evidence/core-preparation.log"

test "$(shasum -a 256 runtime/RUNTIME_PROFILE | awk '{print $1}')" = "$expected_core_profile_sha"
test "$(shasum -a 256 runtime/bridge.mex | awk '{print $1}')" = "$expected_mex_sha"
python3 - runtime/build-provenance-macos.json \
    "$target_arch" "$python_asset_id" "$python_asset" "$python_archive_sha" \
    "$expected_mex_sha" "$expected_staged_framework_sha" "$expected_staged_executable_sha" <<'PY'
import json
import pathlib
import sys

provenance = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
architecture = sys.argv[2]
asset_id = int(sys.argv[3])
asset_name = sys.argv[4]
archive_sha, mex_sha, framework_sha, executable_sha = sys.argv[5:9]
python = provenance.get("python", {})
expected = {
    "implementation": "CPython",
    "version": "3.12.10",
    "architecture": architecture,
    "release": "3.12.10-14343898437",
    "archive_asset_id": asset_id,
    "checksum_asset_id": 244701301,
    "archive_name": asset_name,
    "archive_sha256": archive_sha,
    "staged_framework_sha256": framework_sha,
    "staged_executable_sha256": executable_sha,
    "staging_source": "verified-actions-python-versions-package-payload",
}
for key, value in expected.items():
    if python.get(key) != value:
        raise SystemExit(f"stable core Python provenance mismatch for {key}: {python.get(key)!r} != {value!r}")
if provenance.get("runtime_profile") != "core" or provenance.get("numpy") != {"bundled": False}:
    raise SystemExit("reconstructed core runtime profile is invalid")
if provenance.get("bridge", {}).get("mex_sha256") != mex_sha:
    raise SystemExit("reconstructed core MEX provenance is invalid")
print("bridge_phase03_core_stable_provenance=pass")
PY
ditto runtime "$work/core-runtime"

wheel="$work/assets/$wheel_name"
curl --fail --location --retry 3 --retry-all-errors --output "$wheel" "$wheel_url"
test "$(shasum -a 256 "$wheel" | awk '{print $1}')" = "$wheel_sha"

tools/stage-macos-numpy-runtime.sh \
    --core-runtime "$work/core-runtime" \
    --output-runtime "$output_runtime" \
    --numpy-wheel "$wheel" \
    --numpy-url "$wheel_url" \
    --expected-mex-sha "$expected_mex_sha" \
    --arch "$target_arch" \
    --census-output "$evidence/macos-numpy-native-census.json" \
    2>&1 | tee "$evidence/numpy-staging.log"
popd >/dev/null

test "$(shasum -a 256 "$output_runtime/numpy-payload-manifest-macos.json" | awk '{print $1}')" = "$expected_numpy_manifest_sha"
test "$(shasum -a 256 "$output_runtime/bridge.mex" | awk '{print $1}')" = "$expected_mex_sha"
test "$(shasum -a 256 "$evidence/macos-numpy-native-census.json" | awk '{print $1}')" = "$expected_numpy_native_census_sha"
test "$(tr -d '\r\n' < "$output_runtime/RUNTIME_PROFILE")" = numpy

python3 - \
    "$output_runtime/build-provenance-macos.json" \
    "$output_runtime/numpy-payload-manifest-macos.json" \
    "$target_arch" "$expected_core_shared_map_sha" "$expected_numpy_payload_map_sha" \
    "$python_asset_id" "$python_asset" "$python_archive_sha" \
    "$expected_staged_framework_sha" "$expected_staged_executable_sha" "$expected_mex_sha" <<'PY'
import json
import pathlib
import sys

provenance = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
manifest = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
(
    architecture,
    core_shared_map_sha,
    payload_map_sha,
    asset_id,
    asset_name,
    archive_sha,
    framework_sha,
    executable_sha,
    mex_sha,
) = sys.argv[3:12]
asset_id = int(asset_id)
if provenance.get("runtime_profile") != "numpy":
    raise SystemExit("reconstructed Phase-03 runtime is not the NumPy profile")
python = provenance.get("python", {})
stable_python = {
    "implementation": "CPython",
    "version": "3.12.10",
    "architecture": architecture,
    "release": "3.12.10-14343898437",
    "archive_asset_id": asset_id,
    "checksum_asset_id": 244701301,
    "archive_name": asset_name,
    "archive_sha256": archive_sha,
    "staged_framework_sha256": framework_sha,
    "staged_executable_sha256": executable_sha,
    "staging_source": "verified-actions-python-versions-package-payload",
}
for key, value in stable_python.items():
    if python.get(key) != value:
        raise SystemExit(f"stable NumPy-runtime Python provenance mismatch for {key}: {python.get(key)!r} != {value!r}")
if provenance.get("bridge", {}).get("mex_sha256") != mex_sha:
    raise SystemExit("reconstructed Phase-03 MEX provenance mismatch")
numpy = provenance.get("numpy", {})
if numpy.get("version") != "2.5.2" or numpy.get("payload_map_sha256") != payload_map_sha:
    raise SystemExit("reconstructed Phase-03 NumPy provenance identity mismatch")
if provenance.get("core_shared_map_sha256") != core_shared_map_sha:
    raise SystemExit("reconstructed Phase-03 core shared-map identity mismatch")
if manifest.get("payload_file_count") != 923 or manifest.get("payload_map_sha256") != payload_map_sha:
    raise SystemExit("reconstructed Phase-03 NumPy payload manifest identity mismatch")
print(f"phase03_numpy_payload_map_sha256={payload_map_sha}")
print("bridge_phase03_numpy_runtime_identity=pass")
PY

cat >"$evidence/bridge-phase03-identity.txt" <<EOF
revision=$qualified_revision
architecture=$target_arch
python_archive_sha256=$python_archive_sha
mex_sha256=$expected_mex_sha
qualified_reference_core_provenance_sha256=$qualified_core_provenance_sha
core_shared_map_sha256=$expected_core_shared_map_sha
numpy_payload_map_sha256=$expected_numpy_payload_map_sha
qualified_reference_numpy_provenance_sha256=$qualified_numpy_provenance_sha
numpy_manifest_sha256=$expected_numpy_manifest_sha
numpy_native_census_sha256=$expected_numpy_native_census_sha
qualified_phase03_evidence_sha256=$expected_phase03_qualification_sha
EOF

# Consumer qualification must not be able to fall back to the CPython source
# toolcache used to reconstruct Phase 03.  The staged runtime is the only Python
# installation that remains available from this reconstruction work directory.
rm -rf "$work/python-setup" "$work/toolcache" "$work/python3.12-x86_64"

echo "bridge_phase03_runtime=$output_runtime"
echo "bridge_phase03_runtime_reconstruction=pass"
