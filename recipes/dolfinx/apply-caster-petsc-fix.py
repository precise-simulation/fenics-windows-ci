"""Apply Windows fixes to the DOLFINx Python sources before building.

Both fixes are idempotent and assert loudly if the expected source state
is not found.

1. caster_petsc.h: nanobind >= 2.8's NB_TYPE_CASTER declares explicit
   conversion operators (Value*, Value&, Value&&) which, together with the
   `operator TYPE()` that DOLFINx's PETSc opaque-handle caster adds, make
   conversion to the handle type ambiguous under MSVC ("ambiguous
   user-defined conversion"). Replaces the NB_TYPE_CASTER use with an
   explicit minimal expansion (see caster-petsc-msvc-nanobind.patch).

2. fem/petsc.py: get_petsc_lib() only searches for libpetsc.so/.dylib.
   On Windows the shared library is libpetsc.dll under <PETSC_DIR>/bin,
   and get_petsc_lib() runs at import time of dolfinx.fem.petsc, so
   without this fix every `from dolfinx.fem.petsc import ...` fails.
"""

import sys
from pathlib import Path

CASTER_OLD = (
    "    NB_TYPE_CASTER(TYPE, const_name(#NAME))                                    \\\n"
)
CASTER_NEW = (
    "    using Value = TYPE;                                                        \\\n"
    "    static constexpr auto Name = const_name(#NAME);                            \\\n"
    "    template <typename T_> using Cast = movable_cast_t<T_>;                    \\\n"
    "    template <typename T_> static constexpr bool can_cast()                    \\\n"
    "    {                                                                          \\\n"
    "      return true;                                                             \\\n"
    "    }                                                                          \\\n"
)
CASTER_OLD_TAIL = (
    "    operator TYPE() { return value; }                                          \\\n  }\n"
)
CASTER_NEW_TAIL = (
    "    operator TYPE() { return value; }                                          \\\n"
    "    TYPE value;                                                                \\\n"
    "  }\n"
)

PETSCLIB_OLD = """    candidate_paths = [
        os.path.join(petsc_dir, petsc_arch, "lib", "libpetsc.so"),
        os.path.join(petsc_dir, petsc_arch, "lib", "libpetsc.dylib"),
    ]
"""
PETSCLIB_NEW = """    candidate_paths = [
        os.path.join(petsc_dir, petsc_arch, "lib", "libpetsc.so"),
        os.path.join(petsc_dir, petsc_arch, "lib", "libpetsc.dylib"),
        # Windows (conda layout): the DLL lives in <PETSC_DIR>/bin
        os.path.join(petsc_dir, "bin", "libpetsc.dll"),
        os.path.join(petsc_dir, petsc_arch, "lib", "libpetsc.dll"),
    ]
"""


def fix_caster_petsc(src_dir: Path) -> None:
    path = src_dir / "python" / "dolfinx" / "wrappers" / "dolfinx_wrappers" / "caster_petsc.h"
    text = path.read_text()
    if CASTER_NEW in text:
        assert CASTER_OLD not in text, "caster_petsc.h is in a mixed state"
        print("caster_petsc.h: MSVC nanobind fix already applied")
        return
    assert text.count(CASTER_OLD) == 1, f"caster_petsc.h: expected 1 NB_TYPE_CASTER, found {text.count(CASTER_OLD)}"
    assert text.count(CASTER_OLD_TAIL) == 1, "caster_petsc.h: expected 1 operator TYPE()"
    path.write_text(text.replace(CASTER_OLD, CASTER_NEW).replace(CASTER_OLD_TAIL, CASTER_NEW_TAIL))
    print("caster_petsc.h: applied MSVC nanobind fix")


def fix_petsc_lib(src_dir: Path) -> None:
    path = src_dir / "python" / "dolfinx" / "fem" / "petsc.py"
    text = path.read_text()
    if 'libpetsc.dll' in text:
        assert PETSCLIB_OLD not in text, "fem/petsc.py is in a mixed state"
        print("fem/petsc.py: Windows libpetsc.dll fix already applied")
        return
    assert text.count(PETSCLIB_OLD) == 1, f"fem/petsc.py: expected 1 candidate_paths block, found {text.count(PETSCLIB_OLD)}"
    path.write_text(text.replace(PETSCLIB_OLD, PETSCLIB_NEW))
    print("fem/petsc.py: applied Windows libpetsc.dll fix")


if __name__ == "__main__":
    src = Path(sys.argv[1])
    fix_caster_petsc(src)
    fix_petsc_lib(src)
