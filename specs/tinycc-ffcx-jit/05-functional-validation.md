# Phase 5: broad functional validation

**Status:** proposed.

## Objective

Run the same broad FFCx/CFFI coverage used to qualify LLVM-MinGW, but with the TinyCC backend selected explicitly and with the TinyCC-specific ABI, import, hardening, concurrency, and provenance contracts exercised as regressions.

The goal is to discover unsupported generated-C constructs, ABI/CRT edge cases, packing/bitfield mismatches, PE hardening/unwind problems, cache problems, thread/MPI behavior differences, foreign-binary-input regressions, system-library leakage, and compiler-specific numerical failures before performance/size can influence the decision.

## Required matrix

At minimum reproduce the current LLVM-MinGW Phase 5 coverage:

- standard GIL-enabled CPython 3.12, 3.13, and 3.14;
- standard GIL-enabled Python 3.15 preview when available in the existing CI path;
- fresh JIT and subsequent cache reload;
- scalar Poisson baseline;
- vector/tensor forms;
- cell/interior/exterior-facet forms;
- coefficient/constant-heavy forms;
- representative higher-order elements;
- paths containing spaces;
- two-rank MPI compile/cache semantics;
- PE import/export, CRT, mitigation, relocation, and unwind inspection for generated modules.

Free-threaded CPython is not part of this matrix unless a later proposal explicitly adds its ABI/import-library and activation-concurrency requirements.

Reuse existing test generation and numerical assertions wherever possible so TinyCC and LLVM-MinGW are compared on exactly the same source/forms.

## Generated-source corpus

Retain every generated C source involved in the matrix as a CI artifact.

For each source record:

- TinyCC compile result;
- compile/link command line;
- warnings/errors;
- source hash;
- Python version;
- form/test identity;
- selected TinyCC standard mode;
- effective packing/bitfield flag policy;
- backend/compiler patch identity.

This corpus becomes the compatibility contract for future TinyCC upgrades. A new compiler revision must compile the same corpus before it can replace the pinned revision.

## Numerical equivalence

Compare TinyCC results directly with the existing LLVM-MinGW reference for the same tests.

Require:

- same solve success/failure outcome;
- existing tolerance checks pass unchanged;
- no compiler-specific NaN/Inf behavior;
- no unexplained differences in assembled vectors/matrices or reported error norms.

If a difference is due to floating-point optimization choices, characterize it before relaxing any tolerance. Do not weaken tests merely to make TinyCC pass.

## ABI and layout regression

Re-run the Phase-1 cross-compiler ABI probes from the installed Phase-3 package.

Require:

- relevant UFCx struct sizes, alignments, and field offsets match the qualified MSVC/LLVM-MinGW consumer contract;
- calling-convention probes remain unchanged;
- `long double` size/alignment/relevance remains consistent with the qualification record;
- representative packed-layout probes remain consistent;
- the qualified bitfield-layout policy remains explicit.

If Phase 1 determined that `-mms-bitfields` is required, fail if any TinyCC compile command omits it. If Phase 1 proved it unnecessary, retain the evidence/test that establishes why the relevant interfaces remain safe.

## Stress/repeatability

Add repeated fresh JIT cycles within one process and across new processes to catch compiler/adapter state leakage.

Suggested stress set:

- 100 minimal CFFI compile/load cycles;
- 20 fresh FFCx module compilations across distinct cache keys;
- concurrent MPI ranks hitting one TinyCC cache namespace;
- repeated backend switching LLVM-MinGW -> TinyCC -> LLVM-MinGW.

For every backend transition, prove from diagnostics that the target backend performs at least one fresh compilation in its own physical cache namespace before a same-backend cache hit is accepted. Also prove the backend-specific cache root was selected before FFCx's first cache lookup.

Do not require unsafe forced unloading of CPython extension modules merely to create an artificial unload test; process-restart coverage is the relevant isolation mechanism.

## Thread-concurrency and activation stress

Validate the shared Phase-4 activation lock under standard GIL-enabled CPython:

- start two TinyCC JIT requests from separate Python threads and prove their process-global activation windows do not interleave;
- start TinyCC and LLVM-MinGW JIT requests concurrently and prove each completes under its own backend/cache identity without mixed environment/hooks;
- exercise same-thread same-backend nesting if the production caller path can nest activation;
- explicitly exercise conflicting same-thread backend nesting and require a deterministic error;
- inject a compilation failure while the activation lock is held, then run a successful JIT to prove complete state restoration;
- record lock/backend diagnostics sufficient to distinguish serialization from accidental success.

The expected behavior is safe serialization, not same-process parallel compilation through mutable global CFFI/setuptools state.

## Python-link integrity

For every supported Python version and representative JIT module:

- capture the logical libraries and `.def` inputs passed to TinyCC;
- fail if `python312`, `python313`, `python314`, `python315`, or another minor-version Python library is requested;
- inspect PE imports and require `python3.dll` with no minor-version Python DLL;
- record whether `Py_NO_LINK_LIB` is supported/used for the active headers;
- verify that versions without that macro still acquire no implicit Python autolink dependency.

Command capture plus final PE imports are authoritative; the presence of `Py_NO_LINK_LIB` alone is not treated as proof.

## CRT/allocator stress

Current TinyCC Win64 defaults to `msvcrt.dll` unless Phase 1 establishes a different qualified configuration. Treat the qualified Phase-1 CRT model as immutable backend metadata and fail if a compiler upgrade changes it unexpectedly.

For a mixed CRT, stress:

- buffers crossing CFFI/Python boundaries;
- strings and error paths;
- repeated process-level module creation/load;
- allocations performed by generated wrappers;
- exception/error handling;
- any FILE/handle/locale/errno ownership identified in Phase 1.

A crash-free small Poisson solve is not sufficient evidence for a mixed-CRT boundary.

## System-library integrity

Exercise the Phase-1/2 system-library policy from the installed package.

If approved Windows system-DLL lookup is used:

- record the exact approved system roots;
- prove no Visual Studio, Windows Kits/SDK, Python `libs`/`PCbuild`, or arbitrary ambient library directory participates;
- inspect PE imports and compare them with the qualified allowlist/reference;
- fail on new unexpected non-system runtime imports.

If fully explicit packaged definitions are used, prove that implicit system/import-library search has not reappeared.

## PE security/unwind integrity

For representative generated modules on every supported Python version:

- record `DllCharacteristics`;
- require the Phase-1-qualified ASLR/dynamic-base and NX baseline;
- require high-entropy VA on x64 where the chosen baseline specifies it;
- verify relocation metadata needed by the selected ASLR model;
- inspect `.pdata`/x64 unwind metadata for generated functions according to the Phase-1 contract;
- compare unexpected import/system-DLL changes against the LLVM-MinGW reference.

Where Phase 1 qualified TinyCC's supported linker controls for dynamic base/high-entropy VA/NX, assert that those controls are present in the adapter diagnostics. A source-patched hardening path is acceptable only when the qualification record shows supported options were insufficient.

A TinyCC update that silently drops required mitigation or unwind properties fails qualification even when numerical tests remain green.

## Foreign input regression tests

Exercise the strict adapter boundary with negative cases:

- versioned Python library request;
- MSVC `.lib`;
- foreign `.obj`/`.o`;
- arbitrary non-qualified archive;
- unsupported `extra_objects`;
- unsupported `cffi_libraries` request;
- host SDK/MSVC/Python development library directory injection.

Each case must fail before an ambient/alternate linker can participate.

## Tasks

1. Parameterize the existing Phase 5 validation for backend selection where practical.
2. Run the full standard GIL-enabled CPython matrix under TinyCC.
3. Preserve generated C and compile/link diagnostics.
4. Compare numerical results with LLVM-MinGW.
5. Re-run ABI/packing/bitfield/`long double` probes from the installed package.
6. Add repeated compile/load stress across same-process and new-process runs.
7. Validate mandatory physical cache isolation, pre-cache-lookup root selection, and fresh compilation across backend switches.
8. Validate thread-concurrency, nested activation, conflicting-backend rejection, and exception restoration through the shared runtime lock.
9. Validate MPI behavior and cache-root propagation.
10. Validate Stable-ABI link integrity on every supported Python version, including explicit handling of versions without `Py_NO_LINK_LIB`.
11. Validate the qualified CRT boundary and allocator/ownership stress.
12. Validate the qualified system-library-resolution policy and absence of SDK/compiler-development leakage.
13. Validate PE mitigation, relocation, and x64 unwind properties and the expected TinyCC hardening controls.
14. Run foreign-object/library negative tests.
15. Record unsupported-warning inventory without suppressing it globally.

## Exit criteria

Phase 5 passes when TinyCC completes the full existing functional matrix and stress tests on supported standard GIL-enabled Python versions with no ABI/packing/bitfield, CRT, PE-security/unwind, cache, thread-activation, MPI, Python-link, system-library, object/library-boundary, or numerical regression and with no ambient compiler fallback.
