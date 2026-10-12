import unittest
from pathlib import Path

import validate_support_policy


class SupportPolicyTests(unittest.TestCase):
    def test_repository_matches_support_policy(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual([], validate_support_policy.validate(root))


if __name__ == "__main__":
    unittest.main()
