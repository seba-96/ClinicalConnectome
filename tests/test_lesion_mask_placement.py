from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bids_converter.converter import create_bids_ready_tree


class LesionMaskPlacementTests(unittest.TestCase):
    def test_lesion_space_is_required_when_lesions_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            lesion = src / "sub-0001" / "anat" / "sub-0001_lesion.nii.gz"
            lesion.parent.mkdir(parents=True)
            lesion.write_bytes(b"fake")

            with self.assertRaisesRegex(ValueError, "--lesion-space"):
                create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

    def test_t1w_lesion_masks_are_placed_under_subject_anat(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            lesion = src / "sub-0001" / "anat" / "sub-0001_lesion.nii.gz"
            lesion.parent.mkdir(parents=True)
            lesion.write_bytes(b"fake")

            create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True, lesion_space="T1w")

            expected = dst / "sub-0001" / "anat" / "sub-0001_lesion_roi.nii.gz"
            self.assertTrue(expected.exists())

    def test_non_t1w_lesion_masks_are_placed_under_derivatives_manual_masks(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            lesion = src / "sub-0001" / "anat" / "sub-0001_lesion.nii.gz"
            lesion.parent.mkdir(parents=True)
            lesion.write_bytes(b"fake")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                lesion_space="MNI152NLin2009cAsym",
            )

            expected = (
                dst
                / "derivatives"
                / "manual_masks"
                / "sub-0001"
                / "anat"
                / "sub-0001_space-MNI152NLin2009cAsym_label-lesion_mask.nii.gz"
            )
            self.assertTrue(expected.exists())

    def test_multiple_lesions_require_subdir_or_pattern_selector(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            anat = src / "sub-0001" / "anat"
            anat.mkdir(parents=True)
            (anat / "sub-0001_lesion_a.nii.gz").write_bytes(b"fake")
            (anat / "sub-0001_lesion_b.nii.gz").write_bytes(b"fake")

            with self.assertRaisesRegex(ValueError, "--lesion-source-subdir|--lesion-pattern"):
                create_bids_ready_tree(
                    source_dir=src,
                    target_dir=dst,
                    overwrite=True,
                    lesion_space="MNI152NLin2009cAsym",
                )

    def test_multiple_lesions_can_be_selected_by_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            anat = src / "sub-0001" / "anat"
            anat.mkdir(parents=True)
            (anat / "sub-0001_lesion_primary.nii.gz").write_bytes(b"fake")
            (anat / "sub-0001_lesion_secondary.nii.gz").write_bytes(b"fake")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                lesion_space="MNI152NLin2009cAsym",
                lesion_pattern="*primary*",
            )

            expected_primary = (
                dst
                / "derivatives"
                / "manual_masks"
                / "sub-0001"
                / "anat"
                / "sub-0001_space-MNI152NLin2009cAsym_label-lesion_mask.nii.gz"
            )
            expected_secondary = (
                dst
                / "derivatives"
                / "manual_masks"
                / "sub-0001"
                / "anat"
                / "sub-0001_space-MNI152NLin2009cAsym_desc-sub-0001-lesion-secondary_label-lesion_mask.nii.gz"
            )
            self.assertTrue(expected_primary.exists())
            self.assertFalse(expected_secondary.exists())


if __name__ == "__main__":
    unittest.main()

