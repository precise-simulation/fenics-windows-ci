import json
import pathlib
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import check_versions


REFERENCE = {
    "platform": "linux-64",
    "specs": check_versions.REFERENCE_SPECS,
    "virtual_package_overrides": check_versions.REFERENCE_VIRTUAL_PACKAGE_OVERRIDES,
    "dolfinx_family": "0.11",
    "petsc_family": "3.25",
    "packages": {
        "fenics-dolfinx": {"version": "0.11.0"},
        "petsc": {"version": "3.25.5"},
        "petsc4py": {"version": "3.25.5"},
        "slepc": {"version": "3.25.2"},
        "slepc4py": {"version": "3.25.2"},
        "hdf5": {"version": "1.14.6"},
        "mpi": {"name": "mpich", "version": "4.3.1"},
    },
}


def reference_solve(slepc_version="3.25.2"):
    records = []
    for name, version, build in [
        ("fenics-dolfinx", "0.11.0", "real_h1"),
        ("petsc", "3.25.5", "real_h2"),
        ("petsc4py", "3.25.5", "real_h3"),
        ("slepc", slepc_version, "real_h4"),
        ("slepc4py", "3.25.2", "real_h5"),
        ("hdf5", "1.14.6", "mpi_mpich_h6"),
        ("mpich", "4.3.1", "h7"),
    ]:
        records.append({"name": name, "version": version, "build_string": build})
    return {"actions": {"LINK": records}}


def write_recipe(root, name, version):
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "recipe.yaml").write_text(
        f'context:\n  version: "{version}"\n  build: 1\nsource:\n  sha256: {"0" * 64}\n',
        encoding="utf-8",
    )


class ChannelVersionsTest(unittest.TestCase):
    def test_only_404_means_not_published(self):
        with patch.object(
            check_versions,
            "http_json",
            side_effect=urllib.error.HTTPError("url", 404, "missing", None, None),
        ):
            self.assertEqual(
                check_versions.channel_versions(),
                {"hdf5": None, "petsc": None, "petsc4py": None, "dolfinx": None},
            )
        with patch.object(
            check_versions,
            "http_json",
            side_effect=urllib.error.HTTPError("url", 500, "failed", None, None),
        ):
            with self.assertRaises(urllib.error.HTTPError):
                check_versions.channel_versions()


class ReferenceTest(unittest.TestCase):
    def test_run_reference_solve_targets_linux_without_installing(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": '{"actions": {}}', "stderr": ""})()
        with patch.object(check_versions.subprocess, "run", return_value=completed) as run:
            check_versions.run_reference_solve("micromamba")
        cmd = run.call_args.args[0]
        self.assertIn("--dry-run", cmd)
        self.assertEqual(cmd[cmd.index("--platform") + 1], "linux-64")
        self.assertEqual(cmd[-len(check_versions.REFERENCE_SPECS) :], check_versions.REFERENCE_SPECS)
        solve_env = run.call_args.kwargs["env"]
        for key, value in check_versions.REFERENCE_VIRTUAL_PACKAGE_OVERRIDES.items():
            self.assertEqual(solve_env[key], value)

    def test_build_reference_records_expected_packages(self):
        result = check_versions.build_reference(reference_solve())
        self.assertEqual(result["petsc_family"], "3.25")
        self.assertEqual(result["packages"]["mpi"]["name"], "mpich")
        self.assertEqual(result["packages"]["petsc"]["build_string"], "real_h2")
        self.assertEqual(
            result["virtual_package_overrides"],
            check_versions.REFERENCE_VIRTUAL_PACKAGE_OVERRIDES,
        )

    def test_build_reference_rejects_incoherent_slepc_family(self):
        with self.assertRaisesRegex(RuntimeError, "incoherent"):
            check_versions.build_reference(reference_solve(slepc_version="3.26.0"))

    def test_family_migration_fails_before_build(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            write_recipe(root, "petsc", "3.25.4")
            write_recipe(root, "petsc4py", "3.25.4")
            write_recipe(root, "hdf5", "1.14.6")
            write_recipe(root, "dolfinx", "0.11.0")
            reference = json.loads(json.dumps(REFERENCE))
            reference["packages"]["petsc"]["version"] = "3.26.1"
            reference["packages"]["petsc4py"]["version"] = "3.26.1"
            with patch.object(check_versions, "RECIPES", root):
                with self.assertRaisesRegex(RuntimeError, "migration detected"):
                    check_versions.assert_supported_families(reference)

    def test_exact_dolfinx_petsc_pin_forms_are_rejected(self):
        exact_specs = (
            "petsc ==3.25.4 real_*",
            "petsc 3.25.4 real_*",
            "petsc=3.25.4=real_*",
            "petsc = 3.25.4 real_*",
            "petsc 3.25.4.* real_*",
            "petsc 3.25.4.post1 real_*",
            "petsc4py 3.25.4",
            '"petsc 3.25.4 real_*"',
            "'petsc4py=3.25.4'",
        )
        for spec in exact_specs:
            with self.subTest(spec=spec), tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                recipe = root / "dolfinx"
                recipe.mkdir()
                (recipe / "recipe.yaml").write_text(
                    f"requirements:\n  host:\n    - {spec}\n",
                    encoding="utf-8",
                )
                with patch.object(check_versions, "RECIPES", root):
                    with self.assertRaisesRegex(RuntimeError, "exact PETSc-family"):
                        check_versions.assert_dolfinx_dependency_policy()

    def test_dolfinx_petsc_family_constraints_are_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            recipe = root / "dolfinx"
            recipe.mkdir()
            (recipe / "recipe.yaml").write_text(
                "requirements:\n"
                "  host:\n"
                "    - petsc * real_*\n"
                "    - petsc 3.25.* real_*\n"
                "    - petsc >=3.25,<3.26 real_*\n"
                "    - petsc ${{ version_xy }}.* ${{ scalar }}_*\n"
                "    - petsc4py\n",
                encoding="utf-8",
            )
            with patch.object(check_versions, "RECIPES", root):
                check_versions.assert_dolfinx_dependency_policy()

    def test_variant_hdf5_value_is_synchronized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            recipe = root / "petsc"
            recipe.mkdir()
            variant = recipe / "variants-win64.yaml"
            variant.write_text("hdf5:\n- 1.14.6\nmpi:\n- impi\n", encoding="utf-8")
            with patch.object(check_versions, "RECIPES", root):
                check_versions.patch_variant_value("petsc", "hdf5", "1.14.7")
            self.assertIn("hdf5:\n- 1.14.7\n", variant.read_text(encoding="utf-8"))

    def test_reference_targets_use_reference_dolfinx_version(self):
        reference = json.loads(json.dumps(REFERENCE))
        reference["packages"]["fenics-dolfinx"]["version"] = "0.11.7"
        targets = check_versions.reference_targets(reference)
        self.assertEqual(targets["dolfinx"], "0.11.7")
        self.assertEqual(targets["petsc"], "3.25.5")


class RecipePatchTest(unittest.TestCase):
    @patch.object(check_versions, "download_sha256", return_value="a" * 64)
    def test_patch_hdf5_updates_source_url(self, download_sha256):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            recipe_dir = root / "hdf5"
            recipe_dir.mkdir()
            recipe = recipe_dir / "recipe.yaml"
            recipe.write_text(
                'version: "1.14.6"\n'
                "source:\n"
                "  url: https://support.hdfgroup.org/releases/hdf5/v1_14/downloads/hdf5-1.14.6.tar.gz\n"
                f"  sha256: {'0' * 64}\n",
                encoding="utf-8",
            )
            with patch.object(check_versions, "RECIPES", root):
                check_versions.patch_recipe("hdf5", "1.14.7")
            expected_url = "https://support.hdfgroup.org/releases/hdf5/v1_14/downloads/hdf5-1.14.7.tar.gz"
            updated = recipe.read_text(encoding="utf-8")
            self.assertIn(expected_url, updated)
            download_sha256.assert_called_once_with(expected_url)


if __name__ == "__main__":
    unittest.main()
