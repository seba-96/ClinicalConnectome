from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from bids_converter.converter import create_bids_ready_tree


class ParticipantIdMappingTests(unittest.TestCase):
    def test_original_ids_are_saved_in_participant_id_dmp_column(self) -> None:
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
            acquisitions = src / "acquisitions.tsv"
            acquisitions.write_text(
                "participant_id\tsite\n"
                "ST_UNIPD_0001\tA\n",
                encoding="utf-8",
            )

            create_bids_ready_tree(source_dir=src, target_dir=dst, overwrite=True)

            with (dst / "participants.tsv").open("r", encoding="utf-8", newline="") as f:
                participant_rows = list(csv.DictReader(f, delimiter="\t"))
            with (dst / "acquisitions.tsv").open("r", encoding="utf-8", newline="") as f:
                acquisition_rows = list(csv.DictReader(f, delimiter="\t"))

            self.assertEqual(participant_rows[0]["participant_id"], "sub-STUNIPD0001")
            self.assertEqual(participant_rows[0]["participant_id_dmp"], "ST_UNIPD_0001")
            self.assertEqual(participant_rows[1]["participant_id"], "sub-STUNIPD0002")
            self.assertEqual(participant_rows[1]["participant_id_dmp"], "sub-ST_UNIPD_0002")

            self.assertEqual(acquisition_rows[0]["participant_id"], "sub-STUNIPD0001")
            self.assertEqual(acquisition_rows[0]["participant_id_dmp"], "ST_UNIPD_0001")


if __name__ == "__main__":
    unittest.main()

