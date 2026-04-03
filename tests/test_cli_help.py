from __future__ import annotations

import unittest

from bids_converter.cli import build_parser


class CliHelpTests(unittest.TestCase):
    def test_help_mentions_participant_mapping(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("--participant-id-map", help_text)
        self.assertIn("original_participant_id", help_text)
        self.assertIn("bundled template", help_text)
        self.assertIn("--source-dir", help_text)


if __name__ == "__main__":
    unittest.main()


