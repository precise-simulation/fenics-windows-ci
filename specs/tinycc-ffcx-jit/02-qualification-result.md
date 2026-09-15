# Phase 2 qualification result

**Status:** done.

This result records completion of the owned TinyCC CFFI adapter gate defined by `02-cffi-adapter.md`.

## Qualified implementation

- Pull request: #11 (`impl/tinycc-ffcx-jit-phase1`).
- Qualified TinyCC revision: `0fb54300b56512754221d80adda85ddb9815bceb`.
- Qualification run: `tinycc-jit` #9, run ID `34657651612`, head `674b754d38c8dcdfd1c9cd6daddbfcdb8d6c0fc9`.
- Supported matrix: CPython 3.12, 3.13, and 3.14.
- Qualified dependency pair observed on CPython 3.12: CFFI 2.1.1 and setuptools 84.0.0; the package contract is initially constrained to the corresponding `2.1.*` / `84.*` families.
- CPython 3.15 remains informational/non-blocking and currently has no compatible `fenics-dolfinx` environment in the configured channels.

## Gate outcome

The supported matrix passes the production adapter qualification:

- owned `cffi._shimmed_dist_utils.Distribution` interception and direct source-to-`.pyd` `build_ext` path;
- deterministic suppression of external distutils/setuptools configuration;
- process-wide reentrant activation lock with same-backend nesting, conflicting-policy rejection, thread serialization, and exception-safe restoration;
- paths containing spaces and non-default build directories;
- explicit rejection of unsupported important compiler flags, foreign object/library inputs, and versioned Python libraries;
- deterministic Stable-ABI `python3.def` linking;
- explicit `-mms-bitfields`, CPython Win64, mixed-CRT ownership, system-DLL, and PE-hardening policies;
- backend cache identity `tinycc-0fb54300b565-aaa86e30769a96f90b37` derived from compiler and adapter policy identity;
- fresh CFFI and FFCx/DOLFINx Poisson JIT operation on Python 3.12-3.14.

The qualified policy metadata is:

```text
adapter_schema          tinycc-cffi-adapter-v2
external_config         suppress-all-v1
python_link             stable-abi-python3-def-v1
pe_hardening            dynamicbase-highentropyva-nxcompat-v1
crt                     msvcrt-owned-allocation-boundary-v1
abi                     mingw32-mswin64-msbitfields-longdouble8-v1
system_library          windows-system-dll-resolution-v1
```

Cross-backend concurrency remains intentionally deferred to Phase 4B, when both backends are controlled by the common runtime selector and can be tested under one ownership contract.

## Phase decision

**GO.** Phase 2 is complete. Phase 3 may package the qualified compiler and adapter as `fenics-jit-tinycc`, provided the package owns only its backend-specific tree, records build-chain/source provenance, passes clean-rebuild/relocatability tests, and satisfies the early footprint gate.
