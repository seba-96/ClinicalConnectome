from __future__ import annotations

import io
import json
import subprocess
import unittest
from unittest.mock import patch

from bids_converter.cli import main


class BidsValidationCliTests(unittest.TestCase):
    def test_validation_runs_by_default_and_emits_compact_result(self) -> None:
        with (
            patch("bids_converter.cli.create_bids_ready_tree", return_value={"dirs": 0}),
            patch(
                "bids_converter.cli.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["bids-validator", "/tmp/out"],
                    returncode=0,
                ),
            ) as run_mock,
            patch("sys.argv", ["bids-converter", "/tmp/in", "/tmp/out"]),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            main()

        payload = json.loads(stdout.getvalue())
        self.assertIn("bids_validation", payload)
        self.assertEqual(payload["bids_validation"]["returncode"], 0)
        self.assertEqual(payload["bids_validation"]["command"], ["bids-validator", "/tmp/out"])
        self.assertEqual(sorted(payload["bids_validation"].keys()), ["command", "returncode"])
        run_mock.assert_called_once_with(
            ["bids-validator", "/tmp/out"],
            check=False,
        )

    def test_validation_nonzero_exit_code_is_propagated(self) -> None:
        with (
            patch("bids_converter.cli.create_bids_ready_tree", return_value={"dirs": 0}),
            patch(
                "bids_converter.cli.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["bids-validator", "/tmp/out"],
                    returncode=2,
                ),
            ),
            patch("sys.argv", ["bids-converter", "/tmp/in", "/tmp/out"]),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            with self.assertRaises(SystemExit) as exc:
                main()

        self.assertEqual(exc.exception.code, 2)

    def test_no_validate_bids_skips_validator(self) -> None:
        with (
            patch("bids_converter.cli.create_bids_ready_tree", return_value={"dirs": 0}) as create_mock,
            patch("bids_converter.cli.subprocess.run") as run_mock,
            patch("sys.argv", ["bids-converter", "/tmp/in", "/tmp/out", "--no-validate-bids"]),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            main()

        payload = json.loads(stdout.getvalue())
        self.assertNotIn("bids_validation", payload)
        create_mock.assert_called_once()
        run_mock.assert_not_called()

    def test_validation_reports_missing_executable(self) -> None:
        with (
            patch("bids_converter.cli.create_bids_ready_tree", return_value={"dirs": 0}),
            patch(
                "bids_converter.cli.subprocess.run",
                side_effect=[FileNotFoundError(), FileNotFoundError()],
            ),
            patch("sys.argv", ["bids-converter", "/tmp/in", "/tmp/out"]),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            with self.assertRaises(RuntimeError) as exc:
                main()

        self.assertIn("bids-validator", str(exc.exception))


if __name__ == "__main__":
    unittest.main()

