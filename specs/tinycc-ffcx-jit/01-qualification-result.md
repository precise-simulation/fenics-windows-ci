# Phase 1 qualification result

**Status:** done.

This result records the completed compatibility gate defined by `01-compatibility-proof.md`. It also records qualified observations that supersede planning assumptions in that proposal where the experiment produced different evidence.

## Qualified implementation

- Pull request: #11 (`impl/tinycc-ffcx-jit-phase1`).
- Qualified TinyCC development revision: `0fb54300b56512754221d80adda85ddb9815bceb`.
- Final Phase-1 qualification run: `tinycc-jit` #4, run ID `34653589218`, head `a485220295e107a787b766dc817e4e9455993fde`.
- Earlier full qualification run #3, run ID `34650827981`, also passed on the implementation head before the CI trigger cleanup.
- Supported matrix: CPython 3.12, 3.13, and 3.14.
- CPython 3.15 remains informational/non-blocking and currently does not have a compatible `fenics-dolfinx` environment in the configured channels.
- TinyCC 0.9.27 remains a non-blocking historical reference and does not pass the current bootstrap/reference path; the pinned development revision is therefore the baseline for later phases.

## Gate outcome

The supported matrix passes the Phase-1 proof with TinyCC as the JIT compiler/linker after the bootstrap stage:

- owned CFFI `Distribution` interception and direct source-to-`.pyd` `build_ext` path;
- hostile distutils/setuptools configuration isolation;
- Stable-ABI `python3.dll` linking without a minor-version Python DLL request/import;
- official CPython Win64 target model with 8-byte pointer, `size_t`, and `Py_ssize_t` widths;
- `-mms-bitfields` ABI policy and packing/bitfield probes;
- fresh FFCx/DOLFINx Poisson JIT, import, assembly, and solve;
- mixed-CRT ownership stress using internal TinyCC allocations and Python allocator APIs at the Python/CFFI boundary;
- rejection of unsupported foreign object/library inputs;
- required PE dynamic-base, high-entropy-VA, NX compatibility, relocations, and x64 unwind/exception metadata;
- hermetic JIT execution without Visual Studio, host Windows SDK development inputs, LLVM-MinGW, GCC, Clang, or another external linker participating in the runtime JIT step.

## Qualified corrections to proposal assumptions

### CI triggering

`00-ci-policy.md` supersedes the original manual-only workflow requirement. TinyCC qualification now runs automatically for narrowly scoped TinyCC-relevant pull-request changes, while `workflow_dispatch` remains available for explicit requalification.

### `long double`

The pinned TinyCC Windows PE target reports `sizeof(long double) == 8` and `alignof(long double) == 8`. This matches the Windows double-sized ABI model used by the relevant consumer boundary. The implementation retains an explicit regression assertion for this PE target model.

The proposal text describing the qualified Windows target as 16-byte/16-aligned `long double` is therefore not applicable to the pinned Windows PE configuration and must not be treated as a remaining Phase-1 blocker.

### CRT model

The generated TinyCC modules retain TinyCC's `msvcrt.dll` runtime model. Phase 1 selected the mixed-CRT qualification path rather than introducing a TinyCC UCRT patch. The proof keeps TinyCC-owned allocation/free operations internal and uses Python allocator APIs for Python/CFFI ownership; the allocation stress tests pass on all supported interpreters.

## Phase decision

**GO.** Phase 1 is complete and the epic may proceed to Phase 2 (`02-cffi-adapter.md`). Phase 2 must turn the qualified prototype behavior into the production owned adapter/activation contract and must preserve all Phase-1 ABI, hermeticity, Stable-ABI, PE-security, CRT-ownership, and cache-identity requirements.
