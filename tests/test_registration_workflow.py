from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clinical_connectome.registration import (
    RegistrationConfig,
    find_lesion_mask_for_t1w,
    find_subject_t1w_images,
    register_dataset,
)


class RegistrationWorkflowTests(unittest.TestCase):
    def test_t1w_discovery_and_lesion_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anat = root / "sub-01" / "anat"
            anat.mkdir(parents=True)

            t1w = anat / "sub-01_T1w.nii.gz"
            lesion = anat / "sub-01_label-lesion_mask.nii.gz"
            t1w.write_bytes(b"fake")
            lesion.write_bytes(b"fake")

            found_t1w = find_subject_t1w_images(root)
            self.assertEqual([path.resolve() for path in found_t1w], [t1w.resolve()])
            self.assertEqual(find_lesion_mask_for_t1w(t1w).resolve(), lesion.resolve())

    def test_dataset_registration_orchestration(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as out_tmp:
            src = Path(src_tmp)
            out = Path(out_tmp)

            anat = src / "sub-01" / "anat"
            anat.mkdir(parents=True)
            t1w = anat / "sub-01_T1w.nii.gz"
            lesion = anat / "sub-01_label-lesion_mask.nii.gz"
            t1w.write_bytes(b"fake")
            lesion.write_bytes(b"fake")

            config = RegistrationConfig(
                bids_root=src,
                output_root=out,
                template_space="MNI152NLin2009cAsym",
            )

            with (
                patch("clinical_connectome.registration.resolve_mni_template", return_value=Path("/tmp/template.nii.gz")),
                patch(
                    "clinical_connectome.registration._run_ants_registration",
                    return_value={
                        "status": "ok",
                        "warped_t1w": str(out / "sub-01" / "anat" / "registered.nii.gz"),
                        "transforms": [],
                        "warped_lesion_mask": str(out / "sub-01" / "anat" / "registered_mask.nii.gz"),
                    },
                ) as run_mock,
            ):
                result = register_dataset(config)

            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["registered"], 1)
            self.assertEqual(result["failed"], 0)
            self.assertEqual(result["lesion_masks_found"], 1)
            self.assertEqual(result["lesion_masks_warped"], 1)
            self.assertEqual(run_mock.call_count, 1)
            self.assertFalse(run_mock.call_args.kwargs["fast"])
            self.assertTrue(run_mock.call_args.kwargs["run_n4_bias_correction"])
            self.assertTrue(run_mock.call_args.kwargs["run_brain_extraction"])
            self.assertIsNone(run_mock.call_args.kwargs["bet_frac"])
            self.assertFalse(run_mock.call_args.kwargs["keep_temp"])

    def test_dataset_registration_forwards_fast_flag(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as out_tmp:
            src = Path(src_tmp)
            out = Path(out_tmp)

            anat = src / "sub-01" / "anat"
            anat.mkdir(parents=True)
            t1w = anat / "sub-01_T1w.nii.gz"
            t1w.write_bytes(b"fake")

            config = RegistrationConfig(
                bids_root=src,
                output_root=out,
                template_space="MNI152NLin2009cAsym",
                fast=True,
                run_n4_bias_correction=False,
                run_brain_extraction=False,
                bet_frac=0.35,
                keep_temp=True,
            )

            with (
                patch("clinical_connectome.registration.resolve_mni_template", return_value=Path("/tmp/template.nii.gz")),
                patch(
                    "clinical_connectome.registration._run_ants_registration",
                    return_value={
                        "status": "ok",
                        "warped_t1w": str(out / "sub-01" / "anat" / "registered.nii.gz"),
                        "transforms": [],
                        "warped_lesion_mask": None,
                    },
                ) as run_mock,
            ):
                register_dataset(config)

            self.assertTrue(run_mock.call_args.kwargs["fast"])
            self.assertFalse(run_mock.call_args.kwargs["run_n4_bias_correction"])
            self.assertFalse(run_mock.call_args.kwargs["run_brain_extraction"])
            self.assertAlmostEqual(run_mock.call_args.kwargs["bet_frac"], 0.35)
            self.assertTrue(run_mock.call_args.kwargs["keep_temp"])

    def test_dataset_registration_forwards_synquick_transform_type(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as out_tmp:
            src = Path(src_tmp)
            out = Path(out_tmp)

            anat = src / "sub-01" / "anat"
            anat.mkdir(parents=True)
            t1w = anat / "sub-01_T1w.nii.gz"
            t1w.write_bytes(b"fake")

            config = RegistrationConfig(
                bids_root=src,
                output_root=out,
                transform_type="RegistrationSynQuick",
            )

            with (
                patch("clinical_connectome.registration.resolve_mni_template", return_value=Path("/tmp/template.nii.gz")),
                patch(
                    "clinical_connectome.registration._run_ants_registration",
                    return_value={
                        "status": "ok",
                        "warped_t1w": str(out / "sub-01" / "anat" / "registered.nii.gz"),
                        "transforms": [],
                        "warped_lesion_mask": None,
                    },
                ) as run_mock,
            ):
                register_dataset(config)

            self.assertEqual(run_mock.call_args.kwargs["transform_type"], "RegistrationSynQuick")


if __name__ == "__main__":
    unittest.main()
