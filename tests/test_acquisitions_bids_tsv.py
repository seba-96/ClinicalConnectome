from __future__ import annotations

import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

from bids_converter.converter import create_bids_ready_tree


def _write_nifti(path: Path, shape: tuple[int, ...], zooms: tuple[float, ...]) -> None:
    data = np.zeros(shape, dtype=np.float32)
    image = nib.Nifti1Image(data, affine=np.eye(4))
    image.header.set_zooms(zooms)
    nib.save(image, str(path))


class AcquisitionsBidsTsvTests(unittest.TestCase):
    def test_writes_func_metrics_and_scanner_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            func_nii = src / "sub-0001" / "ses-01" / "func" / "sub-0001_ses-01_task-rest_bold.nii.gz"
            func_nii.parent.mkdir(parents=True)
            _write_nifti(func_nii, shape=(4, 4, 4, 120), zooms=(2.0, 2.0, 2.5, 2.0))
            func_nii.with_name("sub-0001_ses-01_task-rest_bold.json").write_text(
                json.dumps(
                    {
                        "RepetitionTime": 2.0,
                        "Manufacturer": "Siemens",
                        "ManufacturersModelName": "Prisma",
                        "MagneticFieldStrength": 3.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            self.assertEqual(result["acquisitions_bids_rows"], 1)

            with (dst / "acquisitions_bids.tsv").open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertTrue(row["participant_id"].startswith("sub-"))
            self.assertEqual(row["modality"], "func")
            self.assertEqual(row["voxel_size_mm"], "2.0,2.0,2.5")
            self.assertEqual(row["repetition_time_s"], "2.0")
            self.assertEqual(row["total_length_minutes"], "4.0")
            self.assertEqual(row["machine"], "Siemens")
            self.assertEqual(row["model"], "Prisma")
            self.assertEqual(row["tesla"], "3.0")

    def test_writes_dwi_metrics_including_bvals_and_directions(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            for run in ("01", "02"):
                dwi_nii = src / "sub-0001" / "ses-01" / "dwi" / f"sub-0001_ses-01_run-{run}_dwi.nii.gz"
                dwi_nii.parent.mkdir(parents=True, exist_ok=True)
                _write_nifti(dwi_nii, shape=(3, 3, 3, 5), zooms=(2.2, 2.2, 2.2, 1.0))
                stem = dwi_nii.name[: -len(".nii.gz")]
                dwi_nii.with_name(f"{stem}.json").write_text(
                    json.dumps(
                        {
                            "Manufacturer": "GE",
                            "ManufacturersModelName": "SIGNA",
                            "MagneticFieldStrength": 1.5,
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                dwi_nii.with_name(f"{stem}.bval").write_text("0 1000 1000 2000 0\n", encoding="utf-8")
                dwi_nii.with_name(f"{stem}.bvec").write_text(
                    "0 1 0 0 0\n"
                    "0 0 1 0 0\n"
                    "0 0 0 1 0\n",
                    encoding="utf-8",
                )

            result = create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            self.assertEqual(result["acquisitions_bids_rows"], 2)

            with (dst / "acquisitions_bids.tsv").open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))

            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row["modality"], "dwi")
                self.assertNotIn("dwi_number_of_runs", row)
                self.assertEqual(row["dwi_unique_nonzero_bvals"], "2.0")
                self.assertEqual(row["dwi_unique_nonzero_bvals_values"], "1000.0,2000.0")
                self.assertEqual(row["dwi_diffusion_directions"], "3.0")
                self.assertEqual(row["machine"], "GE")
                self.assertEqual(row["model"], "SIGNA")
                self.assertEqual(row["tesla"], "1.5")

    def test_accepts_gzipped_bval_and_bvec_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            dwi_nii = src / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_dwi.nii.gz"
            dwi_nii.parent.mkdir(parents=True, exist_ok=True)
            _write_nifti(dwi_nii, shape=(3, 3, 3, 5), zooms=(2.2, 2.2, 2.2, 1.0))
            stem = dwi_nii.name[: -len(".nii.gz")]

            dwi_nii.with_name(f"{stem}.json").write_text(
                json.dumps({"Manufacturer": "GE", "ManufacturersModelName": "SIGNA", "MagneticFieldStrength": 1.5})
                + "\n",
                encoding="utf-8",
            )
            dwi_nii.with_name(f"{stem}.bval").write_bytes(gzip.compress(b"0 1000 1000 2000 0\n"))
            dwi_nii.with_name(f"{stem}.bvec").write_bytes(
                gzip.compress(b"0 1 0 0 0\n0 0 1 0 0\n0 0 0 1 0\n")
            )

            create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            with (dst / "acquisitions_bids.tsv").open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["dwi_unique_nonzero_bvals"], "2.0")
            self.assertEqual(row["dwi_unique_nonzero_bvals_values"], "1000.0,2000.0")
            self.assertEqual(row["dwi_diffusion_directions"], "3.0")

    def test_invalid_binary_bval_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            dwi_nii = src / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_dwi.nii.gz"
            dwi_nii.parent.mkdir(parents=True, exist_ok=True)
            _write_nifti(dwi_nii, shape=(3, 3, 3, 5), zooms=(2.2, 2.2, 2.2, 1.0))
            stem = dwi_nii.name[: -len(".nii.gz")]

            dwi_nii.with_name(f"{stem}.bval").write_bytes(b"\x00\x8b\xff\x10")
            dwi_nii.with_name(f"{stem}.bvec").write_text("0 1 0 0 0\n0 0 1 0 0\n0 0 0 1 0\n", encoding="utf-8")

            create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            with (dst / "acquisitions_bids.tsv").open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["dwi_unique_nonzero_bvals"], "")
            self.assertEqual(row["dwi_unique_nonzero_bvals_values"], "")
            self.assertEqual(row["dwi_diffusion_directions"], "3.0")


if __name__ == "__main__":
    unittest.main()

