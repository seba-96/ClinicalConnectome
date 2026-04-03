from __future__ import annotations

import unittest
from bids_converter.converter import (
    get_bundled_missing_json_fields_file,
    get_bundled_reference_bids_root,
)


class ResourceAndValidationTests(unittest.TestCase):
    def test_bundled_resources_exist(self) -> None:
        self.assertTrue(get_bundled_reference_bids_root().is_dir())
        self.assertTrue(get_bundled_missing_json_fields_file().is_file())



if __name__ == "__main__":
    unittest.main()

