from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from save_codec import (
    SaveFormatError,
    decrypt_save_text,
    encrypt_json_text,
    load_save,
    write_save,
)


SAMPLE_DATA = {
    "archiveIndex": 0,
    "farmData": {
        "agentData": {
            "customPlayerName": "测试玩家",
            "money": 25,
            "health": 100,
            "maxHealth": 100,
        }
    },
    "baseData": {
        "version": "1.00.05",
        "customPlayerName": "测试玩家",
        "money": 25,
    },
}


class SaveCodecTests(unittest.TestCase):
    def test_encrypt_decrypt_round_trip(self) -> None:
        import json

        source = json.dumps(SAMPLE_DATA, ensure_ascii=False, separators=(",", ":"))
        encrypted = encrypt_json_text(source)
        self.assertEqual(decrypt_save_text(encrypted), source)

    def test_rejects_invalid_prefix(self) -> None:
        with self.assertRaises(SaveFormatError):
            decrypt_save_text("NOT-A-SAVE")

    def test_write_save_and_create_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "doloc-save-0.data")
            first = write_save(target, SAMPLE_DATA)
            self.assertIsNone(first.backup_path)

            changed = copy.deepcopy(SAMPLE_DATA)
            changed["baseData"]["money"] = 500
            changed["farmData"]["agentData"]["money"] = 500
            second = write_save(target, changed)

            self.assertIsNotNone(second.backup_path)
            self.assertTrue(second.backup_path.exists())
            loaded, _ = load_save(target)
            self.assertEqual(loaded, changed)


if __name__ == "__main__":
    unittest.main()
