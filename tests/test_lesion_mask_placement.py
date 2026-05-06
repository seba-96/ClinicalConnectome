from __future__ import annotations

import tempfile
import unittest
import stat
from pathlib import Path

import nibabel as nib
import numpy as np

from bids_converter.converter import create_bids_ready_tree


class LesionMaskPlacementTests(unittest.TestCase):
    @staticmethod
    def _write_nifti(
        path: Path,
        shape: tuple[int, int, int],
        voxel_size: tuple[float, float, float],
        affine: np.ndarray | None = None,
    ) -> None:
        used_affine = affine if affine is not None else np.diag([*voxel_size, 1.0])
        image = nib.Nifti1Image(np.ones(shape, dtype=np.float32), affine=used_affine)
        nib.save(image, str(path))

    @staticmethod
    def _read_png_size(path: Path) -> tuple[int, int]:
        data = path.read_bytes()
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("Invalid PNG signature")
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return width, height

    @staticmethod
    def _write_label_nifti(path: Path, data: np.ndarray, voxel_size: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> None:
        image = nib.Nifti1Image(data.astype(np.float32), np.diag([*voxel_size, 1.0]))
        nib.save(image, str(path))

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

            expected = dst / "sub-0001" / "anat" / "sub-0001_space-T1w_lesion_roi.nii.gz"
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

    def test_t1w_lesion_is_resampled_and_overlay_plot_is_generated(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            figures = Path(dst_tmp) / "figures"

            t1w = src / "sub-0001" / "anat" / "sub-0001_T1w.nii.gz"
            lesion = src / "sub-0001" / "anat" / "sub-0001_lesion.nii.gz"
            t1w.parent.mkdir(parents=True)
            self._write_nifti(t1w, shape=(10, 10, 10), voxel_size=(1.0, 1.0, 1.0))
            self._write_nifti(lesion, shape=(6, 6, 6), voxel_size=(2.0, 2.0, 2.0))

            result = create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                lesion_space="T1w",
                figure_dir=figures,
            )

            converted_t1w = dst / "sub-0001" / "anat" / "sub-0001_T1w.nii.gz"
            converted_lesion = dst / "sub-0001" / "anat" / "sub-0001_space-T1w_lesion_roi.nii.gz"
            overlay_png = figures / "sub-0001" / "anat" / "sub-0001_space-T1w_lesion_roi_overlay.png"
            t1w_png = figures / "sub-0001" / "anat" / "sub-0001_T1w_axial.png"
            subject_html = figures / "sub-0001.html"

            t1w_img = nib.load(str(converted_t1w))
            lesion_img = nib.load(str(converted_lesion))

            self.assertEqual(lesion_img.shape[:3], t1w_img.shape[:3])
            self.assertTrue(np.allclose(lesion_img.affine, t1w_img.affine))
            self.assertTrue(t1w_png.exists())
            self.assertTrue(overlay_png.exists())
            self.assertTrue(subject_html.exists())
            html_content = subject_html.read_text(encoding="utf-8")
            self.assertIn("sub-0001/anat/sub-0001_T1w_axial.png", html_content)
            self.assertIn("sub-0001/anat/sub-0001_space-T1w_lesion_roi_overlay.png", html_content)
            self.assertEqual(self._read_png_size(t1w_png), (1800, 300))
            self.assertEqual(self._read_png_size(overlay_png), (1800, 300))
            self.assertEqual(result["lesions_resampled"], 1)
            self.assertEqual(result["overlay_figures"], 1)
            self.assertGreaterEqual(result["scan_figures"], 1)
            self.assertEqual(result["subject_html_pages"], 1)

    def test_dwi_native_lesion_raises_when_orientation_differs(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            dwi = src / "sub-0001" / "dwi" / "sub-0001_dwi.nii.gz"
            lesion = src / "sub-0001" / "dwi" / "sub-0001_lesion.nii.gz"
            dwi.parent.mkdir(parents=True)

            self._write_nifti(dwi, shape=(8, 8, 8), voxel_size=(2.0, 2.0, 2.0))
            flipped_affine = np.diag([-2.0, 2.0, 2.0, 1.0])
            self._write_nifti(lesion, shape=(8, 8, 8), voxel_size=(2.0, 2.0, 2.0), affine=flipped_affine)

            with self.assertRaisesRegex(ValueError, "orientation"):
                create_bids_ready_tree(
                    source_dir=src,
                    target_dir=dst,
                    overwrite=True,
                    lesion_space="dwi",
                )

    def test_flair_native_lesion_raises_when_voxel_size_differs(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            flair = src / "sub-0001" / "anat" / "sub-0001_FLAIR.nii.gz"
            lesion = src / "sub-0001" / "anat" / "sub-0001_lesion.nii.gz"
            flair.parent.mkdir(parents=True)

            self._write_nifti(flair, shape=(8, 8, 8), voxel_size=(1.0, 1.0, 1.0))
            self._write_nifti(lesion, shape=(8, 8, 8), voxel_size=(1.5, 1.0, 1.0))

            with self.assertRaisesRegex(ValueError, "voxel size"):
                create_bids_ready_tree(
                    source_dir=src,
                    target_dir=dst,
                    overwrite=True,
                    lesion_space="FLAIR",
                )

    def test_native_lesion_resample_targets_only_declared_lesion_space(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            anat = src / "sub-0001" / "anat"
            dwi_dir = src / "sub-0001" / "dwi"
            anat.mkdir(parents=True)
            dwi_dir.mkdir(parents=True)

            t1w = anat / "sub-0001_T1w.nii.gz"
            flair = anat / "sub-0001_FLAIR.nii.gz"
            dwi = dwi_dir / "sub-0001_dwi.nii.gz"
            lesion = anat / "sub-0001_lesion.nii.gz"

            self._write_nifti(t1w, shape=(10, 10, 10), voxel_size=(1.0, 1.0, 1.0))
            self._write_nifti(flair, shape=(9, 9, 9), voxel_size=(1.2, 1.2, 1.2))
            self._write_nifti(dwi, shape=(8, 8, 8), voxel_size=(2.0, 2.0, 2.0))
            self._write_nifti(lesion, shape=(7, 7, 7), voxel_size=(1.8, 1.8, 1.8))

            result = create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                lesion_space="FLAIR",
                lesion_resample=True,
            )

            t1w_mask = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-T1w_desc-sub-0001-t1w_label-lesion_mask.nii.gz"
            flair_mask = dst / "sub-0001" / "anat" / "sub-0001_space-FLAIR_desc-sub-0001-flair_lesion_roi.nii.gz"
            dwi_mask = dst / "sub-0001" / "anat" / "sub-0001_space-dwi_desc-sub-0001-dwi_lesion_roi.nii.gz"
            canonical_flair_mask = dst / "sub-0001" / "anat" / "sub-0001_space-FLAIR_lesion_roi.nii.gz"

            self.assertFalse(t1w_mask.exists())
            self.assertFalse(flair_mask.exists())
            self.assertFalse(dwi_mask.exists())
            self.assertTrue(canonical_flair_mask.exists())
            self.assertEqual(result["lesion_resample_outputs"], 1)

    def test_integer_lesion_mask_can_be_split_and_combined(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            lesion = src / "sub-0001" / "anat" / "sub-0001_lesion.nii.gz"
            lesion.parent.mkdir(parents=True)

            labels = np.zeros((8, 8, 8), dtype=np.int16)
            labels[1:3, 1:3, 1:3] = 1
            labels[4:6, 4:6, 4:6] = 2
            self._write_label_nifti(lesion, labels)

            result = create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                lesion_space="MNI152NLin6Asym",
                lesion_split=True,
                lesion_split_labels={1: "core", 2: "edema"},
                lesion_split_combined_desc="edemacore",
            )

            core = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-MNI152NLin6Asym_desc-core_label-lesion_mask.nii.gz"
            edema = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-MNI152NLin6Asym_desc-edema_label-lesion_mask.nii.gz"
            combined = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-MNI152NLin6Asym_desc-edemacore_label-lesion_mask.nii.gz"

            self.assertTrue(core.exists())
            self.assertTrue(edema.exists())
            self.assertTrue(combined.exists())
            self.assertEqual(result["lesion_split_outputs"], 3)

    def test_grouped_split_labels_can_exclude_other_labels(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            lesion = src / "sub-0001" / "anat" / "sub-0001_lesion.nii.gz"
            lesion.parent.mkdir(parents=True)

            labels = np.zeros((8, 8, 8), dtype=np.int16)
            labels[1:2, 1:2, 1:2] = 1
            labels[2:3, 2:3, 2:3] = 2
            labels[3:4, 3:4, 3:4] = 3
            labels[4:5, 4:5, 4:5] = 4
            self._write_label_nifti(lesion, labels)

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                lesion_space="MNI152NLin6Asym",
                lesion_split=True,
                lesion_split_labels={1: "core", 2: "core", 3: "core"},
            )

            core = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-MNI152NLin6Asym_desc-core_label-lesion_mask.nii.gz"
            label4 = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-MNI152NLin6Asym_desc-label4_label-lesion_mask.nii.gz"
            self.assertTrue(core.exists())
            self.assertFalse(label4.exists())

    def test_split_label_recipe_can_overlap_labels(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            lesion = src / "sub-0001" / "anat" / "sub-0001_lesion.nii.gz"
            lesion.parent.mkdir(parents=True)

            labels = np.zeros((8, 8, 8), dtype=np.int16)
            labels[1:2, 1:2, 1:2] = 1
            labels[2:3, 2:3, 2:3] = 2
            labels[3:4, 3:4, 3:4] = 3
            labels[4:5, 4:5, 4:5] = 4
            self._write_label_nifti(lesion, labels)

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                lesion_space="MNI152NLin6Asym",
                lesion_split=True,
                lesion_split_labels=[((1, 2, 3), "core"), ((4,), "edema"), ((3,), "necrosis")],
                lesion_split_combined_desc="edemacore",
            )

            core = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-MNI152NLin6Asym_desc-core_label-lesion_mask.nii.gz"
            edema = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-MNI152NLin6Asym_desc-edema_label-lesion_mask.nii.gz"
            necrosis = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-MNI152NLin6Asym_desc-necrosis_label-lesion_mask.nii.gz"
            combined = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-MNI152NLin6Asym_desc-edemacore_label-lesion_mask.nii.gz"

            self.assertTrue(core.exists())
            self.assertTrue(edema.exists())
            self.assertTrue(necrosis.exists())
            self.assertTrue(combined.exists())

    def test_t1w_split_keeps_all_masks_in_anat(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            anat = src / "sub-0001" / "anat"
            anat.mkdir(parents=True)

            t1w = anat / "sub-0001_T1w.nii.gz"
            lesion = anat / "sub-0001_lesion.nii.gz"
            t1w_affine = np.diag([-1.0, 1.0, 1.0, 1.0])
            self._write_nifti(t1w, shape=(10, 10, 10), voxel_size=(1.0, 1.0, 1.0), affine=t1w_affine)
            labels = np.zeros((10, 10, 10), dtype=np.int16)
            labels[1:3, 1:3, 1:3] = 1
            labels[4:6, 4:6, 4:6] = 2
            self._write_label_nifti(lesion, labels)

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                lesion_space="T1w",
                lesion_split=True,
                lesion_split_labels={1: "core", 2: "edema"},
            )

            anat_core = dst / "sub-0001" / "anat" / "sub-0001_space-T1w_desc-core_lesion_roi.nii.gz"
            anat_edema = dst / "sub-0001" / "anat" / "sub-0001_space-T1w_desc-edema_lesion_roi.nii.gz"
            deriv_core = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-T1w_desc-core_label-lesion_mask.nii.gz"
            deriv_edema = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-T1w_desc-edema_label-lesion_mask.nii.gz"

            self.assertTrue(anat_core.exists())
            self.assertTrue(anat_edema.exists())
            self.assertFalse(deriv_core.exists())
            self.assertFalse(deriv_edema.exists())

            t1w_img = nib.load(str(dst / "sub-0001" / "anat" / "sub-0001_T1w.nii.gz"))
            anat_core_img = nib.load(str(anat_core))
            self.assertEqual(anat_core_img.shape[:3], t1w_img.shape[:3])
            anat_edema_img = nib.load(str(anat_edema))
            self.assertEqual(anat_edema_img.shape[:3], t1w_img.shape[:3])
            self.assertTrue(np.allclose(anat_core_img.affine, t1w_img.affine))
            self.assertTrue(np.allclose(anat_edema_img.affine, t1w_img.affine))

    def test_per_lesion_config_supports_different_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            anat = src / "sub-0001" / "anat"
            anat.mkdir(parents=True)

            flair_lesion = anat / "sub-0001_space-FLAIR_les.nii.gz"
            mni_lesion = anat / "sub-0001_space-MNI152_lesion.nii.gz"
            flair_scan = anat / "sub-0001_FLAIR.nii.gz"
            self._write_label_nifti(flair_lesion, np.ones((5, 5, 5), dtype=np.int16))
            self._write_label_nifti(mni_lesion, np.ones((5, 5, 5), dtype=np.int16))
            self._write_nifti(flair_scan, shape=(5, 5, 5), voxel_size=(1.0, 1.0, 1.0))

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                lesion_configs=[
                    {"pattern": "*space-FLAIR_les*", "space": "FLAIR"},
                    {"pattern": "*space-MNI152*", "space": "MNI152NLin2009cAsym"},
                ],
            )

            flair_mask = dst / "sub-0001" / "anat" / "sub-0001_space-FLAIR_lesion_roi.nii.gz"
            mni_mask = dst / "derivatives" / "manual_masks" / "sub-0001" / "anat" / "sub-0001_space-MNI152NLin2009cAsym_label-lesion_mask.nii.gz"
            self.assertTrue(flair_mask.exists())
            self.assertTrue(mni_mask.exists())

    def test_existing_target_dir_is_removed_before_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            stale = dst / "stale.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("old", encoding="utf-8")

            img = src / "sub-0001" / "anat" / "sub-0001_T1w.nii.gz"
            img.parent.mkdir(parents=True)
            self._write_nifti(img, shape=(4, 4, 4), voxel_size=(1.0, 1.0, 1.0))

            create_bids_ready_tree(source_dir=src, target_dir=dst)

            self.assertFalse(stale.exists())
            self.assertTrue((dst / "sub-0001" / "anat" / "sub-0001_T1w.nii.gz").exists())


if __name__ == "__main__":
    unittest.main()

