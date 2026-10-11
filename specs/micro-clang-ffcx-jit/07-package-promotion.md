# Stage 7 package promotion

The preferred Windows micro-Clang backend is released by promoting the exact
conda package that passed Stage-7 downstream qualification. Release promotion
does not rebuild LLVM, re-prune the sysroot, or repackage the backend.

Qualified Python 3.15 compatibility package identity:

- downstream qualification run: 38111201186
- downstream head: f4fcd90b3cdc960c7f6e5d2eb2ee6a1407490423
- workflow artifact: micro-clang-phase4-stage7-package-channel
- artifact id: 11690504463
- artifact digest: sha256:1ed76766ca6befb2756af99619adac00c20d6a531b84095c4622cf0d7b6ea819
- package: fenics-jit-micro-clang-20260826-h9490d1a_2.conda
- package bytes: 31,892,148
- package SHA-256: 3cb9a8b2a1c16c3cba1bd89dc587637028a4fec8c5343380e4c7f4a67fa5de4d

The compatibility build is derived from the exact previously published and
qualified build-1 package. The requalification workflow verifies that public
package before extracting its backend, adds only the Python 3.15 Stable-ABI
import-library alias, refreshes package metadata/manifests, and builds build 2.
The base package identity is:

- package: fenics-jit-micro-clang-20260826-h9490d1a_1.conda
- package bytes: 31,890,069
- package SHA-256: d8a3510eb08615cb890dbf8f6da8b0d26f573e16a7b0bbee657edf563d40ad01
- qualification run: 37100978194
- qualification head: dbcc097f2a1084d89b92b280c96d98dc5a7f8a9d

The derived staged-source identity is:

- staged payload bytes: 109,094,136
- installed-manifest SHA-256: 205cb2af5fef7bf9b2456322a4dc188db247edad828fa6b399d3e225f7e3c3b5
- runtime-wrapper SHA-256: 7f5c6a59a8e4b4e286f105bd94b27308fa162debf0814cecc9534a7ebb2c6d66

The micro-clang-release workflow downloads the pinned qualification artifact,
verifies the package, base-package, and derived-source identities, then
clean-installs the exact build under Python 3.12 and 3.15 with no LLVM-MinGW
or TinyCC backend. It verifies the versioned Stable-ABI import libraries,
implicit shared-selector activation, and a compiler smoke test on both Python
versions. The downstream qualification run additionally executes a fresh FFCx
Poisson JIT on Python 3.12 through 3.15 and the micro-Clang-only standalone
bundle proof.

Pull requests verify promotion only. A push of these promotion files to main
publishes the exact verified conda file to the precise-simulation Anaconda
channel. Future micro-Clang releases must update this promotion record to a
newly qualified package. Normal FEniCS stack builds consume the published
package and do not rebuild the approximately 67-minute Full-LTO compiler.
