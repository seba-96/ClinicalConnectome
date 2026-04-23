from __future__ import annotations

import unittest

from bids_converter.cli import build_parser


class CliHelpTests(unittest.TestCase):
    def test_help_mentions_participant_mapping(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("participant_id_dmp", help_text)
        self.assertIn("--lesion-space", help_text)
        self.assertIn("--lesion-resample", help_text)
        self.assertIn("--lesion-split", help_text)
        self.assertIn("--lesion-split-label", help_text)
        self.assertIn("--lesion-split-primary-desc", help_text)
        self.assertIn("--lesion-config", help_text)
        self.assertIn("--target-read-only", help_text)
        self.assertIn("--no-target-read-only", help_text)
        self.assertIn("--figure-dir", help_text)
        self.assertIn("--lesion-source-subdir", help_text)
        self.assertIn("--lesion-pattern", help_text)
        self.assertIn("--validate-bids", help_text)
        self.assertIn("--no-validate-bids", help_text)
        self.assertIn("--intendedfor-fmri-only", help_text)
        self.assertIn("--intendedfor-dwi-only", help_text)
        self.assertIn("--fmap-fmri-pattern", help_text)
        self.assertIn("--fmap-dwi-pattern", help_text)
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

    def test_fmap_pattern_flags_are_repeatable(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "/tmp/in",
            "/tmp/out",
            "--fmap-fmri-pattern",
            "fMRI_rest_pa",
            "--fmap-fmri-pattern",
            "*fieldmap*",
            "--fmap-dwi-pattern",
            "dMRI_pa",
        ])

        self.assertEqual(args.fmap_fmri_pattern, ["fMRI_rest_pa", "*fieldmap*"])
        self.assertEqual(args.fmap_dwi_pattern, ["dMRI_pa"])

    def test_lesion_resample_flag_is_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "/tmp/in",
            "/tmp/out",
            "--lesion-resample",
        ])
        self.assertTrue(args.lesion_resample)

    def test_lesion_split_labels_are_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "/tmp/in",
            "/tmp/out",
            "--lesion-split",
            "--lesion-split-label",
            "1:core",
            "--lesion-split-label",
            "2:edema",
            "--lesion-split-combined-desc",
            "edemacore",
        ])
        self.assertTrue(args.lesion_split)
        self.assertEqual(args.lesion_split_label, [([1], "core"), ([2], "edema")])
        self.assertEqual(args.lesion_split_combined_desc, "edemacore")

    def test_grouped_lesion_split_labels_are_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "/tmp/in",
            "/tmp/out",
            "--lesion-split-label",
            "1,2,3:core",
        ])
        self.assertEqual(args.lesion_split_label, [([1, 2, 3], "core")])

    def test_target_read_only_defaults_to_true(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["/tmp/in", "/tmp/out"])
        self.assertTrue(args.target_read_only)

    def test_lesion_config_json_is_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "/tmp/in",
            "/tmp/out",
            "--lesion-config",
            '{"pattern":"*space-FLAIR_les*","space":"FLAIR","resample":true}',
        ])
        self.assertEqual(len(args.lesion_config), 1)
        self.assertEqual(args.lesion_config[0]["space"], "FLAIR")


if __name__ == "__main__":
    unittest.main()


