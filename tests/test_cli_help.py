from __future__ import annotations

import unittest

from bids_converter.cli import build_parser


class CliHelpTests(unittest.TestCase):
    def test_help_mentions_participant_mapping(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("participant_id_dmp", help_text)
        self.assertIn("--lesion-space", help_text)
        self.assertIn("--lesion-source-subdir", help_text)
        self.assertIn("--lesion-pattern", help_text)
        self.assertIn("--intendedfor-fmri-only", help_text)
        self.assertIn("--intendedfor-dwi-only", help_text)
        self.assertIn("bundled template", help_text)
        self.assertIn("source_dir", help_text)

    def test_intendedfor_flags_are_mutually_exclusive(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "/tmp/in",
                "/tmp/out",
                "--intendedfor-fmri-only",
                "--intendedfor-dwi-only",
            ])

    def test_lesion_selector_flags_are_mutually_exclusive(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "/tmp/in",
                "/tmp/out",
                "--lesion-source-subdir",
                "manual_masks",
                "--lesion-pattern",
                "*lesion*",
            ])


if __name__ == "__main__":
    unittest.main()


