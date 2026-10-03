# Phase 4 stage 3

Stage 2 qualified at **163.0088 MiB**, still **54.8088 MiB** above the
108.2 MiB continuation gate. Stage 3 is therefore a closure-driven target
sysroot experiment; Phase 5 remains blocked.

## Candidate

Use the dependency files and LLD maps captured by the qualified Stage-2
Python 3.12-3.14 matrix. Starting from the qualified Stage-2 package:

1. preserve every header/archive observed by those traces;
2. preserve an explicit broader C/UCRT/POSIX header safety set even when a
   finite trace set does not observe a member;
3. preserve MinGW/UCRT startup/runtime archives and common/default desktop
   Windows import libraries independently of trace observation;
4. remove only unobserved non-core headers and optional import archives;
5. record every removed path/byte count and the retained unobserved safety
   sets;
6. reconstruct the package from an independent clean root and require stable
   metadata/manifest/size hashes;
7. rerun relocation smoke plus the complete Python 3.12-3.14 private
   qualification, including MPI/concurrency/numerical/ABI/PE/hermeticity;
8. keep closure tracing enabled so a failed or still-oversized candidate has
   concrete evidence for the next reversible step.

## Guardrails

Do not prune core C/UCRT/POSIX coverage merely to reach the numerical target.
Do not remove observed archives. Preserve startup/runtime/default Windows
libraries even when unobserved. The production selector/default remains
unchanged. Phase 5 may start only after a qualified complete backend is
<=108.2 MiB.
