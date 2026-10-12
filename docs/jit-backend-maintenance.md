# JIT backend maintenance runbook

The authoritative current support state is [`config/support-policy.json`](../config/support-policy.json). New scripts should read that file instead of introducing another hard-coded Python/backend matrix.

Historical qualification-result files are evidence from the time they ran. Do not rewrite them when current support policy changes; update the policy file, README, and current-status sections instead.

## New CPython minor

Use preview first, promotion second.

### Preview

1. Add the candidate only to `python.preview`.
2. Confirm `fenics-dolfinx` resolves from the intended channels.
3. Qualify the default micro-Clang Stable-ABI path.
4. Add/test the LLVM-MinGW minor-version import-library alias while retaining `python3.dll` as the Stable-ABI runtime target.
5. Run TinyCC header/compiler probes. Check TLS spelling, Python link names, CFFI behavior, and update versioned-Python rejection patterns if needed.
6. Keep preview jobs non-blocking until the full backend qualification passes.
7. Treat free-threaded Python as a separate ABI target.

### Promotion

1. Move the minor from `python.preview` to `python.supported`.
2. Update runtime constraints and import-library aliases.
3. Keep TinyCC's upper Python bound one minor above the highest supported standard-GIL interpreter.
4. Update README requirements.
5. Run `python scripts/validate_support_policy.py`.
6. Require blocking default-backend qualification on every supported minor.
7. Require TinyCC and LLVM-MinGW qualification on every supported minor.
8. Publish optional backends through `optional-jit-release`.
9. Require public-channel verification from `precise-simulation` + `conda-forge`.
10. Require the post-merge stack run to finish green.

Branch-local artifacts alone do not constitute a shipped Python minor.

## TinyCC revision

A new TinyCC revision is a new qualification target. Update the policy, recipe version/build/revision, backend cache identity, and adapter schema if behavior changes.

Re-run package reproducibility, self-test, CFFI/config isolation, Stable-ABI link checks, CRT/system-library boundaries, PE hardening/relocation/unwind checks, negative-input cases, fresh JIT/cache reload, MPI/concurrency, supported-Python matrix, standalone qualification, and optional-release public-channel verification.

TinyCC currently requires `python-gil`. Do not remove that requirement or admit `Py_GIL_DISABLED` without a separate free-threaded ABI qualification.

## LLVM-MinGW revision

For an upstream LLVM-MinGW change:

1. update release/archive identity and SHA-256;
2. rebuild the minimized toolchain;
3. revalidate pruning assumptions;
4. regenerate Stable-ABI import-library aliases for supported Python minors;
5. rerun package and full optional-backend qualification;
6. update the support-policy version/build;
7. publish and verify through the optional-JIT release workflow.

Do not reuse historical minimization measurements as proof for a different upstream payload.

## micro-Clang revision

micro-Clang is the production default. A revision must requalify source identities, build/pruning configuration, package identity, DOLFINx dependency pin, selector behavior, ABI3 coverage, fresh serial JIT, MPI cache sharing, standalone/Nuitka behavior, embedded-runtime pins where applicable, and public package promotion.

Do not infer micro-Clang qualification from LLVM-MinGW qualification.

## Optional backend release

The publication owner for LLVM-MinGW and TinyCC is `.github/workflows/optional-jit-release.yml`.

A release is complete only after:

1. exact packages are built from intended recipes;
2. local qualification passes for every supported Python minor;
3. upload to the configured channel succeeds;
4. clean public-channel environments resolve the exact builds;
5. post-publication qualification passes on every supported minor;
6. evidence artifacts are retained.

Use manual `publish=true` for normal future releases.

## Package identity

Increment a conda build number when package contents, metadata, compatibility behavior, or qualification contract changes without an upstream version change. Change the package version when the represented upstream source/release identity changes.

Never replace a qualified payload under an existing identity without explicit requalification.

## Failure and cleanup

If public-channel verification fails, preserve logs/hashes, stop promotion of that build, fix forward with a new build number, and repeat qualification/public verification.

After merge and green post-merge CI, delete merged feature/release branches. Keep historical qualification evidence immutable.

## Review checklist

Before merging a support/revision change, confirm:

- support-policy JSON updated;
- policy validator green;
- recipes and package identities consistent;
- README/current-status documentation updated;
- historical evidence unchanged;
- local qualification green;
- public release/verification path identified;
- free-threaded scope explicit;
- post-merge stack verification planned.
