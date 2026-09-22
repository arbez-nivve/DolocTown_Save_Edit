"""Opt-in real-save regression: DOLOC_SAMPLE_DIR points to read-only inputs."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from inventory import (add_item, backpack, delete_item, discover_catalog,
                       item_at, replace_item, validate_item)
from save_codec import load_save, write_save


@unittest.skipUnless(os.environ.get('DOLOC_SAMPLE_DIR'), 'Set DOLOC_SAMPLE_DIR to test real saves')
class SampleTests(unittest.TestCase):
    def test_real_samples_edit_encrypt_readback(self):
        root = Path(os.environ['DOLOC_SAMPLE_DIR'])
        paths = sorted(root.glob('doloc-save-*.json')) + sorted(root.glob('doloc-save-*.data'))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(file=path.name):
                digest = hashlib.sha256(path.read_bytes()).digest()
                data = (load_save(path)[0] if path.suffix == '.data'
                        else json.loads(path.read_text(encoding='utf-8-sig')))
                before = copy.deepcopy(data)
                templates, genes = discover_catalog(data)
                self.assertGreater(len(genes), 10)
                for template in templates:
                    validate_item(template.item)
                box_index = next(i for i, item in enumerate(backpack(data)['items'])
                                 if isinstance(item, dict) and 'currentDurability' in item)
                box = copy.deepcopy(item_at(data, (box_index,)))
                box['currentDurability'] = 77
                replace_item(data, (box_index,), box)
                child_index = next(i for i, item in enumerate(box['inventory']['items']) if item)
                child = copy.deepcopy(item_at(data, (box_index, child_index)))
                child['itemCount'] = 23
                replace_item(data, (box_index, child_index), child)
                seed = copy.deepcopy(next(t.item for t in templates
                                          if t.item.get('$type', '').startswith('DolocTown.ItemSeed,')))
                seed['geneGroup']['geneIds'] = genes[:3]
                delete_item(data, (0,))
                self.assertEqual(add_item(data, (), seed, slot=0), (0,))
                self.assertEqual(len(backpack(data)['items']), len(backpack(before)['items']))
                self.assertEqual(backpack(data)['slotLockStates'], backpack(before)['slotLockStates'])
                with tempfile.TemporaryDirectory(prefix='doloc-roundtrip-') as folder:
                    target = Path(folder, 'edited.data')
                    write_save(target, data)
                    loaded, _ = load_save(target)
                    self.assertEqual(loaded, data)
                expected = copy.deepcopy(data)
                expected['farmData']['inventory']['backpack'] = backpack(before)
                self.assertEqual(expected, before)
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), digest)
                print(f'{path.name}: {len(templates)} templates / {len(genes)} genes; roundtrip OK')


if __name__ == '__main__':
    unittest.main()
