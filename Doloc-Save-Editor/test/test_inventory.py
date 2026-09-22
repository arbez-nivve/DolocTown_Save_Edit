import copy
import unittest

from inventory import (add_item, backpack, delete_item, discover_catalog,
                       item_at, replace_item, validate_item, validate_backpack_layout)
from save_codec import SaveFormatError


SEED = {'$type': 'DolocTown.ItemSeed, Assembly-CSharp', 'itemName': 'seed_succulent',
        'itemCount': 2, 'isClonedSeed': False, 'incubationProgress': 269,
        'geneGroup': {'geneIds': ['hope'], 'unknown': 42}}
BOX = {'$type': 'DolocTown.ItemBox, Assembly-CSharp', 'itemName': 'plastic_box',
       'itemCount': 1, 'currentDurability': 91, 'skinIndex': 4,
       'inventory': {'items': [SEED, None], 'slotLockStates': [False, False]}}


def sample():
    return copy.deepcopy({'farmData': {'inventory': {'backpack': {
        'items': [BOX, None, None], 'slotLockStates': [False, True, False]}}},
        'baseData': {}, 'research': {'unlockedGeneNames': ['charge', 'hope']},
        'reward': {'$type': 'DolocTown.RewardItem, Assembly-CSharp',
                   'itemName': 'fake_reward', 'itemCount': 3}})


class InventoryTests(unittest.TestCase):
    def test_capacity_10_20_30_40(self):
        for size in (10, 20, 30, 40):
            with self.subTest(size=size):
                data = sample()
                container = backpack(data)
                container['items'] = [None] * size
                container['slotLockStates'] = [False] * size
                baseline = copy.deepcopy(data)
                for slot in range(size):
                    self.assertEqual(add_item(data, (), SEED), (slot,))
                full = copy.deepcopy(data)
                with self.assertRaises(SaveFormatError):
                    add_item(data, (), SEED)
                self.assertEqual(data, full)
                delete_item(data, (size // 2,))
                self.assertEqual(add_item(data, (), BOX), (size // 2,))
                replace_item(data, (size - 1,), SEED)
                validate_backpack_layout(data, baseline)
                self.assertEqual(len(backpack(data)['items']), size)

    def test_rejects_capacity_changes_even_when_lock_array_matches(self):
        for size in (10, 20, 30, 40):
            original = sample()
            container = backpack(original)
            container['items'], container['slotLockStates'] = [None] * size, [False] * size
            for new_size in (size - 1, size + 1):
                with self.subTest(size=size, new_size=new_size):
                    changed = copy.deepcopy(original)
                    container = backpack(changed)
                    container['items'] = [None] * new_size
                    container['slotLockStates'] = [False] * new_size
                    with self.assertRaises(SaveFormatError):
                        validate_backpack_layout(changed, original)

    def test_capacity_metadata_cannot_be_changed_or_removed(self):
        original = sample()
        original['farmData']['inventory']['backpackColum'] = 10
        original['farmData']['agentData'] = {'backpackLevel': 2}
        for path, key, replacement in [
                (('farmData', 'inventory', 'backpack'), 'slotLockStates', [False] * 3),
                (('farmData', 'inventory'), 'backpackColum', 5),
                (('farmData', 'agentData'), 'backpackLevel', 3)]:
            for remove in (False, True):
                changed = copy.deepcopy(original)
                parent = changed
                for part in path:
                    parent = parent[part]
                if remove:
                    del parent[key]
                else:
                    parent[key] = replacement
                with self.subTest(key=key, remove=remove), self.assertRaises(SaveFormatError):
                    validate_backpack_layout(changed, original)

    def test_delete_preserves_slots_and_metadata(self):
        data = sample()
        before = copy.deepcopy(data)
        delete_item(data, (0, 0))
        before['farmData']['inventory']['backpack']['items'][0]['inventory']['items'][0] = None
        self.assertEqual(data, before)
        delete_item(data, (0,))
        self.assertEqual(len(backpack(data)['items']), 3)
        self.assertEqual(backpack(data)['slotLockStates'], [False, True, False])

    def test_add_skips_locks_and_deepcopies(self):
        data = sample()
        self.assertEqual(add_item(data, (), SEED), (2,))
        item_at(data, (2,))['geneGroup']['geneIds'].append('charge')
        self.assertEqual(SEED['geneGroup']['geneIds'], ['hope'])
        with self.assertRaises(SaveFormatError):
            add_item(data, (), SEED)
        with self.assertRaises(SaveFormatError):
            add_item(data, (), SEED, slot=1)

    def test_nested_add_and_edit_preserve_unknown_fields(self):
        data = sample()
        self.assertEqual(add_item(data, (0,), SEED), (0, 1))
        candidate = copy.deepcopy(item_at(data, (0, 1)))
        candidate['geneGroup']['geneIds'] = ['charge', 'aerial_root']
        candidate['itemCount'] = 100
        replace_item(data, (0, 1), candidate)
        candidate['geneGroup']['geneIds'].clear()
        self.assertEqual(item_at(data, (0, 1))['geneGroup'],
                         {'geneIds': ['charge', 'aerial_root'], 'unknown': 42})
        self.assertEqual(item_at(data, (0, 0)), SEED)

    def test_invalid_edit_is_atomic(self):
        for key, value in [('itemCount', 0), ('itemCount', True),
                           ('itemCount', 2**31), ('currentDurability', -1),
                           ('currentDurability', float('nan')),
                           ('geneGroup', {'geneIds': [1]})]:
            with self.subTest(key=key, value=value):
                data = sample()
                before = copy.deepcopy(data)
                candidate = copy.deepcopy(BOX)
                candidate[key] = value
                with self.assertRaises(SaveFormatError):
                    replace_item(data, (0,), candidate)
                self.assertEqual(data, before)

    def test_nested_container_validation(self):
        bad = copy.deepcopy(BOX)
        bad['inventory']['slotLockStates'].pop()
        with self.assertRaises(SaveFormatError):
            validate_item(bad)

    def test_catalog_scans_other_modules_and_excludes_rewards(self):
        data = sample()
        data['equipment'] = copy.deepcopy(SEED)
        data['equipment']['itemCount'] = 50
        data['equipment']['geneGroup']['geneIds'] = ['firefly']
        templates, genes = discover_catalog(data)
        self.assertEqual(len(templates), 3)
        self.assertEqual(genes, ['charge', 'firefly', 'hope'])
        self.assertTrue(all(t.item['itemCount'] == 1 for t in templates))
        self.assertNotIn('fake_reward', [t.item['itemName'] for t in templates])
        self.assertTrue(any(t.source == 'equipment' for t in templates))

    def test_catalog_skips_malformed_templates(self):
        data = sample()
        data['malformed'] = dict(SEED, geneGroup=None)
        templates, _ = discover_catalog(data)
        self.assertEqual(len(templates), 2)


if __name__ == '__main__':
    unittest.main()
