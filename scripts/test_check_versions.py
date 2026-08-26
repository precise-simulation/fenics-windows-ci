import pathlib
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import check_versions


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


class Hdf5UpstreamTest(unittest.TestCase):
    @patch.object(
        check_versions,
        "http_json",
        return_value={"versions": ["1.14.5", "1.14.6", "1.9.0", "2.2.0"]},
    )
    def test_latest_hdf5_version(self, http_json):
        self.assertEqual(check_versions.upstream_version("hdf5"), "1.14.6")
        http_json.assert_called_once_with(
            "https://api.anaconda.org/package/conda-forge/hdf5"
        )

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
                "  url: https://support.hdfgroup.org/releases/hdf5/v1_14/"
                "v1_14_6/downloads/hdf5-1.14.6.tar.gz\n"
                f"  sha256: {'0' * 64}\n",
                encoding="utf-8",
            )
            with patch.object(check_versions, "RECIPES", root):
                check_versions.patch_recipe("hdf5", "1.14.7")

            updated = recipe.read_text(encoding="utf-8")
            expected_url = (
                "https://support.hdfgroup.org/releases/hdf5/v1_14/"
                "downloads/hdf5-1.14.7.tar.gz"
            )
            self.assertIn(expected_url, updated)
            self.assertIn(f"sha256: {'a' * 64}", updated)
            download_sha256.assert_called_once_with(expected_url)


if __name__ == "__main__":
    unittest.main()
