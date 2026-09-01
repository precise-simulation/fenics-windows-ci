import unittest

import resolve_reference_stack as resolver


class ReferenceResolverTest(unittest.TestCase):
    def test_build_reference_records_expected_packages(self):
        records = []
        for name, version, build in [
            ("fenics-dolfinx", "0.11.0", "real_h1"),
            ("petsc", "3.25.5", "real_h2"),
            ("petsc4py", "3.25.5", "real_h3"),
            ("slepc", "3.25.2", "real_h4"),
            ("slepc4py", "3.25.2", "real_h5"),
            ("hdf5", "1.14.6", "mpi_mpich_h6"),
            ("mpich", "4.3.1", "h7"),
        ]:
            records.append({"name": name, "version": version, "build_string": build})
        result = resolver.build_reference({"actions": {"LINK": records}})
        self.assertEqual(result["petsc_family"], "3.25")
        self.assertEqual(result["packages"]["mpi"]["name"], "mpich")

    def test_build_reference_rejects_mixed_family(self):
        records = [
            {"name": "fenics-dolfinx", "version": "0.11.0"},
            {"name": "petsc", "version": "3.25.5"},
            {"name": "petsc4py", "version": "3.25.5"},
            {"name": "slepc", "version": "3.26.0"},
            {"name": "slepc4py", "version": "3.25.2"},
            {"name": "hdf5", "version": "1.14.6"},
            {"name": "mpich", "version": "4.3.1"},
        ]
        with self.assertRaisesRegex(RuntimeError, "incoherent"):
            resolver.build_reference({"actions": {"LINK": records}})


if __name__ == "__main__":
    unittest.main()
