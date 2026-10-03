# Stage 7 package promotion

The preferred Windows micro-Clang backend is released by promoting the exact
conda package that passed Stage-7 downstream qualification. Release promotion
does not rebuild LLVM, re-prune the sysroot, or repackage the backend.

Qualified package identity:

- downstream qualification run: 37100978194
- downstream head: dbcc097f2a1084d89b92b280c96d98dc5a7f8a9d
- workflow artifact: micro-clang-phase4-stage7-package-channel
- artifact id: 11265769926
- artifact digest: sha256:fa9596c0a4c327848ea3efbde7234596f7944f1df54421975542a6c8365da5e2
- package: fenics-jit-micro-clang-20260826-h9490d1a_1.conda
- package bytes: 31,890,069
- package SHA-256: d8a3510eb08615cb890dbf8f6da8b0d26f573e16a7b0bbee657edf563d40ad01

The package was built from the Full-LTO backend produced by focused Stage-7
measurement run 37100266040. The staged source identity recorded by the
qualified package channel is:

- source head: 52a3da9bfc999492d2cfb3fac6aaece446cbe638
- staged payload bytes: 108,891,293
- installed-manifest SHA-256: 408b5bffdb62da06230165b3b51335ed6b088710f50624ddcfcea6acbad0fcc9
- runtime-wrapper SHA-256: 7f5c6a59a8e4b4e286f105bd94b27308fa162debf0814cecc9534a7ebb2c6d66

The micro-clang-release workflow downloads the pinned qualification artifact,
verifies the package and staged-source identities, clean-installs the exact
build with no LLVM-MinGW or TinyCC backend, activates the shared selector with
FENICS_JIT_COMPILER=micro-clang, and runs a compiler smoke test.

Pull requests verify promotion only. A push of these promotion files to main
publishes the exact verified conda file to the precise-simulation Anaconda
channel. Future micro-Clang releases must update this promotion record to a
newly qualified package. Normal FEniCS stack builds consume the published
package and do not rebuild the approximately 67-minute Full-LTO compiler.
