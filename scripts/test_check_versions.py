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
                {"petsc": None, "petsc4py": None, "dolfinx": None},
            )

        with patch.object(
            check_versions,
            "http_json",
            side_effect=urllib.error.HTTPError("url", 500, "failed", None, None),
        ):
            with self.assertRaises(urllib.error.HTTPError):
                check_versions.channel_versions()


if __name__ == "__main__":
    unittest.main()
