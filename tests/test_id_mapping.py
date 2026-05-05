from __future__ import annotations

import csv
import tempfile
import unittest
import warnings
from pathlib import Path

from bids_converter.converter import DEFAULT_FILENAME_SUBSTITUTIONS, create_bids_ready_tree


class ParticipantIdMappingTests(unittest.TestCase):
    def test_original_ids_are_saved_in_participant_id_dmp_column(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            participants = src / "participants.tsv"
            participants.write_text(
                "participant_id\tage\n"
                "ST_UNIPD_0001\t34\n"
                "sub-ST_UNIPD_0002\t41\n"
                "ST-UNIPD-0003\t28\n"
                "sub-ST-UNIPD-0004\t37\n",
                encoding="utf-8",
            )
            acquisitions = src / "acquisitions.tsv"
            acquisitions.write_text(
                "participant_id\tsite\n"
                "ST_UNIPD_0001\tA\n"
                "sub-ST-UNIPD-0004\tB\n",
                encoding="utf-8",
            )

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                substitutions=DEFAULT_FILENAME_SUBSTITUTIONS,
            )

            with (dst / "participants.tsv").open("r", encoding="utf-8", newline="") as f:
                participant_rows = list(csv.DictReader(f, delimiter="\t"))
            with (dst / "acquisitions_dmp.tsv").open("r", encoding="utf-8", newline="") as f:
                acquisition_rows = list(csv.DictReader(f, delimiter="\t"))

            self.assertEqual(participant_rows[0]["participant_id"], "sub-STUNIPD0001")
            self.assertEqual(participant_rows[0]["participant_id_dmp"], "ST_UNIPD_0001")
            self.assertEqual(participant_rows[1]["participant_id"], "sub-STUNIPD0002")
            self.assertEqual(participant_rows[1]["participant_id_dmp"], "sub-ST_UNIPD_0002")
            self.assertEqual(participant_rows[2]["participant_id"], "sub-STUNIPD0003")
            self.assertEqual(participant_rows[2]["participant_id_dmp"], "ST-UNIPD-0003")
            self.assertEqual(participant_rows[3]["participant_id"], "sub-STUNIPD0004")
            self.assertEqual(participant_rows[3]["participant_id_dmp"], "sub-ST-UNIPD-0004")

            self.assertEqual(acquisition_rows[0]["participant_id"], "sub-STUNIPD0001")
            self.assertEqual(acquisition_rows[0]["participant_id_dmp"], "ST_UNIPD_0001")
            self.assertEqual(acquisition_rows[1]["participant_id"], "sub-STUNIPD0004")
            self.assertEqual(acquisition_rows[1]["participant_id_dmp"], "sub-ST-UNIPD-0004")

    def test_filename_subject_normalization_preserves_task_run_entities(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            src_file = src / "sub-ST_UNIPD_0002" / "func" / "sub-ST_UNIPD_0002_fMRI_rest_run-02.nii.gz"
            src_file.parent.mkdir(parents=True)
            src_file.write_bytes(b"fake")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                substitutions=DEFAULT_FILENAME_SUBSTITUTIONS,
            )

            expected = dst / "sub-STUNIPD0002" / "func" / "sub-STUNIPD0002_task-rest_run-02_bold.nii.gz"
            self.assertTrue(expected.exists())

    def test_subject_ends_at_first_four_digits_and_preserves_remaining_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            src_file = src / "sub-ST_UNIPD_0002_extra_2020" / "func" / "sub-ST_UNIPD_0002_extra_2020_fMRI_rest.nii.gz"
            src_file.parent.mkdir(parents=True)
            src_file.write_bytes(b"fake")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                substitutions=DEFAULT_FILENAME_SUBSTITUTIONS,
            )

            expected_dir = dst / "sub-STUNIPD0002_extra_2020" / "func"
            expected_file = expected_dir / "sub-STUNIPD0002_extra_2020_task-rest_bold.nii.gz"
            self.assertTrue(expected_file.exists())

    def test_files_directly_under_subject_directory_are_not_copied(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            subject_file = src / "ST_UKE_0001" / "file.tsv"
            subject_file.parent.mkdir(parents=True)
            subject_file.write_text("k\tv\n", encoding="utf-8")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                substitutions=DEFAULT_FILENAME_SUBSTITUTIONS,
            )

            skipped_target = dst / "sub-STUKE0001" / "file.tsv"
            self.assertFalse(skipped_target.exists())

    def test_tsv_files_anywhere_inside_subject_tree_are_not_copied(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            nested_tsv = src / "sub-0001" / "ses-01" / "anat" / "notes.tsv"
            nested_tsv.parent.mkdir(parents=True)
            nested_tsv.write_text("k\tv\n", encoding="utf-8")

            create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            self.assertFalse((dst / "sub-0001" / "ses-01" / "anat" / "notes.tsv").exists())

    def test_json_without_matching_nifti_in_subject_tree_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            orphan_json = src / "sub-0001" / "anat" / "sub-0001_T1w.json"
            orphan_json.parent.mkdir(parents=True)
            orphan_json.write_text("{}\n", encoding="utf-8")

            paired_json = src / "sub-0001" / "anat" / "sub-0001_FLAIR.json"
            paired_nii = src / "sub-0001" / "anat" / "sub-0001_FLAIR.nii.gz"
            paired_json.write_text("{}\n", encoding="utf-8")
            paired_nii.write_bytes(b"fake")

            create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            self.assertFalse((dst / "sub-0001" / "anat" / "sub-0001_T1w.json").exists())
            self.assertTrue((dst / "sub-0001" / "anat" / "sub-0001_FLAIR.json").exists())

    def test_participants_numeric_columns_use_dot_decimal_separator(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            participants = src / "participants.tsv"
            participants.write_text(
                "participant_id\tage\tweight\tnotes\n"
                "sub-0001\t34,5\t70,25\tn/a\n"
                "sub-0002\t41\t81,0\tkept\n",
                encoding="utf-8",
            )

            create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            with (dst / "participants.tsv").open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))

            self.assertEqual(rows[0]["age"], "34.5")
            self.assertEqual(rows[0]["weight"], "70.25")
            self.assertEqual(rows[1]["age"], "41")
            self.assertEqual(rows[1]["weight"], "81.0")

    def test_illegal_subject_features_folder_is_removed_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            anat = src / "sub-0001" / "anat"
            features = src / "sub-0001" / "features"
            anat.mkdir(parents=True)
            features.mkdir(parents=True)
            (anat / "sub-0001_T1w.nii.gz").write_bytes(b"fake")
            (features / "table.txt").write_text("payload\n", encoding="utf-8")

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            self.assertFalse((dst / "sub-0001" / "features").exists())
            self.assertEqual(result["illegal_subject_subfolders_removed"], 1)
            self.assertTrue(
                any("Removing illegal subject sub-folder with files: sub-0001/features" in str(w.message) for w in caught)
            )


if __name__ == "__main__":
    unittest.main()

