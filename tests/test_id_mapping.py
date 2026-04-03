from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from bids_converter.converter import create_bids_ready_tree


class ParticipantIdMappingTests(unittest.TestCase):
    def test_mapping_tsv_is_written_when_ids_collapse(self) -> None:
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src = Path(src_tmp)
            dst = Path(dst_tmp) / "out"

            participants = src / "participants.tsv"
            participants.write_text(
                "participant_id\tage\n"
                "ST_UNIPD_0001\t34\n"
                "sub-ST_UNIPD_0002\t41\n",
                encoding="utf-8",
            )

            create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            map_path = dst / "participant_id_map.tsv"
            self.assertTrue(map_path.exists())

            with map_path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))

            self.assertEqual(rows[0]["original_participant_id"], "ST_UNIPD_0001")
            self.assertEqual(rows[0]["bids_participant_id"], "sub-STUNIPD0001")


if __name__ == "__main__":
    unittest.main()

