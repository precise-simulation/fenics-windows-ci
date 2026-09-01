import json
import pathlib
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import check_versions


REFERENCE = {
    "schema": 1,
    "platform": "linux-64",
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
    def test_load_reference_accepts_same_minor_family(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = pathlib.Path(temp_dir) / "reference.json"
            path.write_text(json.dumps(REFERENCE), encoding="utf-8")
            self.assertEqual(check_versions.load_reference(path)["petsc_family"], "3.25")

    def test_load_reference_rejects_incoherent_slepc_family(self):
        reference = json.loads(json.dumps(REFERENCE))
        reference["packages"]["slepc"]["version"] = "3.26.0"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = pathlib.Path(temp_dir) / "reference.json"
            path.write_text(json.dumps(reference), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "incoherent"):
                check_versions.load_reference(path)

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

    def test_exact_dolfinx_petsc_pin_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            recipe = root / "dolfinx"
            recipe.mkdir()
            (recipe / "recipe.yaml").write_text(
                "requirements:\n  host:\n    - petsc ==3.25.4 real_*\n",
                encoding="utf-8",
            )
            with patch.object(check_versions, "RECIPES", root):
                with self.assertRaisesRegex(RuntimeError, "exact PETSc-family"):
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
