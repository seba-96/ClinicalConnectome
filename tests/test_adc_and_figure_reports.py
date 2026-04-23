from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

from bids_converter.converter import create_bids_ready_tree


def _write_nifti(path: Path, shape: tuple[int, int, int]) -> None:
    image = nib.Nifti1Image(np.ones(shape, dtype=np.float32), affine=np.eye(4))
    nib.save(image, str(path))


def _read_png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG signature")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


class AdcAndFigureReportTests(unittest.TestCase):
    def test_adc_in_dwi_is_relocated_under_derivatives_clinical_dwi(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            adc = src / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_ADC.nii.gz"
            adc.parent.mkdir(parents=True)
            _write_nifti(adc, shape=(5, 5, 5))

            create_result = create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            relocated = dst / "derivatives" / "clinical_dwi" / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_ADC.nii.gz"
            self.assertTrue(relocated.exists())
            self.assertFalse((dst / "sub-0001" / "ses-01" / "dwi" / "sub-0001_ses-01_ADC.nii.gz").exists())
            self.assertEqual(create_result["adc_files_relocated"], 1)

    def test_figure_dir_writes_six_slice_montage_and_subject_html(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"
            figures = Path(dst_tmp) / "figures"

            t1w = src / "sub-0001" / "anat" / "sub-0001_T1w.nii.gz"
            t1w.parent.mkdir(parents=True)
            _write_nifti(t1w, shape=(10, 8, 12))

            result = create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                figure_dir=figures,
            )

            montage_png = figures / "sub-0001" / "anat" / "sub-0001_T1w_axial.png"
            subject_html = figures / "sub-0001.html"
            self.assertTrue(montage_png.exists())
            self.assertTrue(subject_html.exists())

            width, height = _read_png_size(montage_png)
            self.assertEqual(width, 1800)
            self.assertEqual(height, 300)

            html = subject_html.read_text(encoding="utf-8")
            self.assertIn("sub-0001/anat/sub-0001_T1w_axial.png", html)
            self.assertEqual(result["subject_html_pages"], 1)


if __name__ == "__main__":
    unittest.main()

