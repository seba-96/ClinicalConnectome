from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bids_converter.converter import create_bids_ready_tree


class IntendedForPopulationTests(unittest.TestCase):
    def test_populates_intendedfor_for_matching_subject_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            fmap_json = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_dir-AP_epi.json"
            fmap_nii = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_dir-AP_epi.nii.gz"
            fmap_json.parent.mkdir(parents=True)
            fmap_json.write_text("{}\n", encoding="utf-8")
            fmap_nii.write_bytes(b"x")

            sub1_func = src / "sub-0001" / "ses-01" / "func" / "sub-0001_ses-01_task-rest_bold.nii.gz"
            sub1_dwi = src / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_dwi.nii.gz"
            sub2_func = src / "sub-0002" / "ses-01" / "func" / "sub-0002_ses-01_task-rest_bold.nii.gz"
            sub1_func.parent.mkdir(parents=True)
            sub1_dwi.parent.mkdir(parents=True)
            sub2_func.parent.mkdir(parents=True)
            sub1_func.write_bytes(b"x")
            sub1_dwi.write_bytes(b"x")
            sub2_func.write_bytes(b"x")

            result = create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            payload = json.loads(
                (dst / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_dir-AP_epi.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload["IntendedFor"],
                [
                    "ses-01/dwi/sub-0001_ses-01_dwi.nii.gz",
                    "ses-01/func/sub-0001_ses-01_task-rest_bold.nii.gz",
                ],
            )
            self.assertEqual(result["intendedfor_updated"], 1)

    def test_merges_existing_intendedfor_with_discovered_entries(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            fmap_json = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_dir-PA_epi.json"
            fmap_nii = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_dir-PA_epi.nii.gz"
            fmap_json.parent.mkdir(parents=True)
            fmap_json.write_text(
                json.dumps(
                    {
                        "IntendedFor": "sub-0001/ses-01/func/sub-0001_ses-01_task-localizer_bold.nii.gz",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            fmap_nii.write_bytes(b"x")

            (src / "sub-0001" / "ses-01" / "func" / "sub-0001_ses-01_task-rest_bold.nii.gz").parent.mkdir(parents=True)
            (src / "sub-0001" / "ses-01" / "func" / "sub-0001_ses-01_task-rest_bold.nii.gz").write_bytes(b"x")

            create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            payload = json.loads(
                (dst / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_dir-PA_epi.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload["IntendedFor"],
                [
                    "ses-01/func/sub-0001_ses-01_task-localizer_bold.nii.gz",
                    "ses-01/func/sub-0001_ses-01_task-rest_bold.nii.gz",
                ],
            )

    def test_acq_fmri_fmap_searches_only_bold_files(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            fmap_json = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-fmri_dir-AP_epi.json"
            fmap_nii = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-fmri_dir-AP_epi.nii.gz"
            fmap_json.parent.mkdir(parents=True)
            fmap_json.write_text("{}\n", encoding="utf-8")
            fmap_nii.write_bytes(b"x")

            bold_file = src / "sub-0001" / "ses-01" / "func" / "sub-0001_ses-01_task-rest_bold.nii.gz"
            dwi_file = src / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_dwi.nii.gz"
            bold_file.parent.mkdir(parents=True)
            dwi_file.parent.mkdir(parents=True)
            bold_file.write_bytes(b"x")
            dwi_file.write_bytes(b"x")

            create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            payload = json.loads(
                (dst / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-fmri_dir-AP_epi.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["IntendedFor"], ["ses-01/func/sub-0001_ses-01_task-rest_bold.nii.gz"])

    def test_acq_dwi_fmap_searches_only_dwi_files(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            fmap_json = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-dwi_dir-PA_epi.json"
            fmap_nii = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-dwi_dir-PA_epi.nii.gz"
            fmap_json.parent.mkdir(parents=True)
            fmap_json.write_text("{}\n", encoding="utf-8")
            fmap_nii.write_bytes(b"x")

            bold_file = src / "sub-0001" / "ses-01" / "func" / "sub-0001_ses-01_task-rest_bold.nii.gz"
            dwi_file = src / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_dwi.nii.gz"
            bold_file.parent.mkdir(parents=True)
            dwi_file.parent.mkdir(parents=True)
            bold_file.write_bytes(b"x")
            dwi_file.write_bytes(b"x")

            create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            payload = json.loads(
                (dst / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-dwi_dir-PA_epi.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["IntendedFor"], ["ses-01/dwi/sub-0001_ses-01_dwi.nii.gz"])

    def test_override_fmri_only_ignores_acq_dwi_heuristic(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            fmap_json = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-dwi_dir-PA_epi.json"
            fmap_nii = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-dwi_dir-PA_epi.nii.gz"
            fmap_json.parent.mkdir(parents=True)
            fmap_json.write_text("{}\n", encoding="utf-8")
            fmap_nii.write_bytes(b"x")

            bold_file = src / "sub-0001" / "ses-01" / "func" / "sub-0001_ses-01_task-rest_bold.nii.gz"
            dwi_file = src / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_dwi.nii.gz"
            bold_file.parent.mkdir(parents=True)
            dwi_file.parent.mkdir(parents=True)
            bold_file.write_bytes(b"x")
            dwi_file.write_bytes(b"x")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                intendedfor_modality_override="bold",
            )

            payload = json.loads(
                (dst / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-dwi_dir-PA_epi.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["IntendedFor"], ["ses-01/func/sub-0001_ses-01_task-rest_bold.nii.gz"])

    def test_override_dwi_only_ignores_acq_fmri_heuristic(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            fmap_json = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-fmri_dir-AP_epi.json"
            fmap_nii = src / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-fmri_dir-AP_epi.nii.gz"
            fmap_json.parent.mkdir(parents=True)
            fmap_json.write_text("{}\n", encoding="utf-8")
            fmap_nii.write_bytes(b"x")

            bold_file = src / "sub-0001" / "ses-01" / "func" / "sub-0001_ses-01_task-rest_bold.nii.gz"
            dwi_file = src / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_dwi.nii.gz"
            bold_file.parent.mkdir(parents=True)
            dwi_file.parent.mkdir(parents=True)
            bold_file.write_bytes(b"x")
            dwi_file.write_bytes(b"x")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                intendedfor_modality_override="dwi",
            )

            payload = json.loads(
                (dst / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-fmri_dir-AP_epi.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["IntendedFor"], ["ses-01/dwi/sub-0001_ses-01_dwi.nii.gz"])

    def test_reclassifies_func_fmap_files_and_forces_acq_fmri(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            misplaced_fmap_nii = src / "sub-0001" / "ses-01" / "func" / "sub-0001_ses-01_fMRI_rest_pa_epi.nii.gz"
            misplaced_fmap_json = src / "sub-0001" / "ses-01" / "func" / "sub-0001_ses-01_fMRI_rest_pa_epi.json"
            misplaced_fmap_nii.parent.mkdir(parents=True)
            misplaced_fmap_nii.write_bytes(b"x")
            misplaced_fmap_json.write_text("{}\n", encoding="utf-8")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                fmap_fmri_patterns=["fMRI_rest_pa"],
            )

            moved_nii = dst / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-fmri_fMRI_rest_pa_epi.nii.gz"
            moved_json = dst / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-fmri_fMRI_rest_pa_epi.json"
            self.assertTrue(moved_nii.exists())
            self.assertTrue(moved_json.exists())
            self.assertFalse(
                (dst / "sub-0001" / "ses-01" / "func" / "sub-0001_ses-01_fMRI_rest_pa_epi.nii.gz").exists()
            )

    def test_reclassifies_dwi_fmap_files_and_forces_acq_dwi(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            misplaced_fmap_nii = src / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_acq-old_dMRI_pa_epi.nii.gz"
            misplaced_fmap_json = src / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_acq-old_dMRI_pa_epi.json"
            misplaced_fmap_nii.parent.mkdir(parents=True)
            misplaced_fmap_nii.write_bytes(b"x")
            misplaced_fmap_json.write_text("{}\n", encoding="utf-8")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                fmap_dwi_patterns=["dMRI_pa"],
            )

            moved_nii = dst / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-dwi_dMRI_pa_epi.nii.gz"
            moved_json = dst / "sub-0001" / "ses-01" / "fmap" / "sub-0001_ses-01_acq-dwi_dMRI_pa_epi.json"
            self.assertTrue(moved_nii.exists())
            self.assertTrue(moved_json.exists())
            self.assertFalse(
                (dst / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_acq-old_dMRI_pa_epi.nii.gz").exists()
            )


if __name__ == "__main__":
    unittest.main()


