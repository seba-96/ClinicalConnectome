from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bids_converter.converter import create_bids_ready_tree


class MissingJsonFieldRangesTests(unittest.TestCase):
    def test_in_range_subject_gets_missing_json_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            flair_json = src / "sub-0005" / "anat" / "sub-0005_Flair.json"
            flair_json.parent.mkdir(parents=True)
            flair_json.write_text("{}\n", encoding="utf-8")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                missing_json_fields={
                    "0001-0100": {
                        "Flair": {
                            "TaskName": "hello",
                        }
                    }
                },
            )

            out_payload = json.loads((dst / "sub-0005" / "anat" / "sub-0005_Flair.json").read_text(encoding="utf-8"))
            self.assertEqual(out_payload.get("TaskName"), "hello")

    def test_out_of_range_subject_does_not_get_missing_json_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            flair_json = src / "sub-0105" / "anat" / "sub-0105_Flair.json"
            flair_json.parent.mkdir(parents=True)
            flair_json.write_text("{}\n", encoding="utf-8")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                missing_json_fields={
                    "0001-0100": {
                        "Flair": {
                            "TaskName": "hello",
                        }
                    }
                },
            )

            out_payload = json.loads((dst / "sub-0105" / "anat" / "sub-0105_Flair.json").read_text(encoding="utf-8"))
            self.assertNotIn("TaskName", out_payload)

    def test_legacy_glob_missing_json_defaults_still_work(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            flair_json = src / "sub-0001" / "anat" / "sub-0001_FLAIR.json"
            flair_json.parent.mkdir(parents=True)
            flair_json.write_text("{}\n", encoding="utf-8")

            create_bids_ready_tree(
                source_dir=src,
                target_dir=dst,
                overwrite=True,
                missing_json_fields={
                    "sub-*/anat/*_FLAIR.json": {
                        "TaskName": "rest",
                    }
                },
            )

            out_payload = json.loads((dst / "sub-0001" / "anat" / "sub-0001_FLAIR.json").read_text(encoding="utf-8"))
            self.assertEqual(out_payload.get("TaskName"), "rest")


if __name__ == "__main__":
    unittest.main()

