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
        return_value={"versions": ["1.14.5", "1.14.6", "1.9.0"]},
    )
    def test_latest_hdf5_version(self, http_json):
        self.assertEqual(check_versions.upstream_version("hdf5"), "1.14.6")
        http_json.assert_called_once_with(
            "https://api.anaconda.org/package/conda-forge/hdf5"
        )


if __name__ == "__main__":
    unittest.main()
