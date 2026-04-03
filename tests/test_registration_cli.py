from __future__ import annotations

import unittest

from clinical_connectome.register_cli import build_parser


class RegistrationCliTests(unittest.TestCase):
    def test_positional_roots_are_required(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["/tmp/bids", "/tmp/out"])
        self.assertEqual(str(args.bids_root), "/tmp/bids")
        self.assertEqual(str(args.output_root), "/tmp/out")

    def test_help_mentions_mask_pattern(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("--lesion-mask-pattern", help_text)
        self.assertIn("{t1_base}", help_text)
        self.assertIn("--bet-frac", help_text)

    def test_fast_flag_is_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["/tmp/bids", "/tmp/out", "--fast"])
        self.assertTrue(args.fast)

    def test_preprocessing_flags_default_to_enabled(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["/tmp/bids", "/tmp/out"])
        self.assertFalse(args.no_n4_bias_correction)
        self.assertFalse(args.no_brain_extraction)

    def test_preprocessing_can_be_disabled(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["/tmp/bids", "/tmp/out", "--no-n4-bias-correction", "--no-brain-extraction"])
        self.assertTrue(args.no_n4_bias_correction)
        self.assertTrue(args.no_brain_extraction)

    def test_bet_frac_defaults_to_none_and_can_be_set(self) -> None:
        parser = build_parser()
        args_default = parser.parse_args(["/tmp/bids", "/tmp/out"])
        args_custom = parser.parse_args(["/tmp/bids", "/tmp/out", "--bet-frac", "0.35"])
        self.assertIsNone(args_default.bet_frac)
        self.assertAlmostEqual(args_custom.bet_frac, 0.35)

    def test_registration_synquick_transform_type_is_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["/tmp/bids", "/tmp/out", "--transform-type", "RegistrationSynQuick"])
        self.assertEqual(args.transform_type, "RegistrationSynQuick")

    def test_keep_temp_flag_is_parsed(self) -> None:
        parser = build_parser()
        args_default = parser.parse_args(["/tmp/bids", "/tmp/out"])
        args_keep = parser.parse_args(["/tmp/bids", "/tmp/out", "--keep-temp"])
        self.assertFalse(args_default.keep_temp)
        self.assertTrue(args_keep.keep_temp)


if __name__ == "__main__":
    unittest.main()
