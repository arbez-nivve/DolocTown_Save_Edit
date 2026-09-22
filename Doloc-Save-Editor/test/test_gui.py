"""Real Tk widget tests; use a Windows desktop session, no game required."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import customtkinter as ctk

from app import DolocSaveEditor, FIELDS, FORM_TAB, INVENTORY_TAB, JSON_TAB
from inventory import item_at, backpack
from save_codec import SaveFormatError, load_save
from json_search import JsonSearch
from test_inventory import sample


def close_root(root):
    # CustomTkinter schedules global polling callbacks; cancel between test roots.
    for timer in root.tk.splitlist(root.tk.call('after', 'info')):
        root.tk.call('after', 'cancel', timer)
    root.destroy()


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()
        cls.editor = ctk.CTkTextbox(cls.root)
        cls.search = JsonSearch(cls.root, cls.editor)

    @classmethod
    def tearDownClass(cls):
        cls.search.query.set('')
        cls.search.refresh()
        close_root(cls.root)

    def test_literal_case_unicode_and_navigation(self):
        self.editor.delete('1.0', 'end')
        self.editor.insert('1.0', 'Seed seed SEED\n基因😀 基因😀\n[a.*] -seed\nline\nnext')
        for query, sensitive, expected in [('seed', False, 4), ('Seed', True, 1),
                                          ('基因😀', False, 2), ('[a.*]', False, 1),
                                          ('-seed', False, 1), ('line\nnext', False, 1),
                                          ('absent', False, 0), ('', False, 0)]:
            with self.subTest(query=query):
                self.search.case_sensitive.set(sensitive)
                self.search.query.set(query)
                self.search.refresh()
                self.assertEqual(len(self.search.matches), expected)
                if expected:
                    ranges = self.editor._textbox.tag_ranges('search_current')
                    actual = self.editor.get(str(ranges[0]), str(ranges[1]))
                    self.assertEqual(actual.casefold(), query.casefold())
                    self.search.move(-1)
                    self.assertEqual(self.search.current, expected - 1)


class EditorTests(unittest.TestCase):
    def setUp(self):
        with patch('sys.argv', ['app.py']):
            self.app = DolocSaveEditor()
        self.app.withdraw()
        data = sample()
        data['farmData']['agentData'] = {}
        for spec in FIELDS:
            value = '测试' if spec.kind == 'text' else 10
            for dotted in spec.paths:
                parts = dotted.split('.')
                obj = data
                for part in parts[:-1]:
                    obj = obj.setdefault(part, {})
                obj[parts[-1]] = value
        self.app.data = data
        self.app.original_data = copy.deepcopy(data)
        self.app._populate_form()
        self.app._render_json()
        self.app.inventory_editor.refresh()
        self.app.update()
        self.app.dirty = False

    def tearDown(self):
        self.app.search.query.set('')
        self.app.search.refresh()
        close_root(self.app)

    def switch(self, tab):
        self.app.tabs.set(tab)
        self.app._on_tab_changed()

    def select_item(self, path):
        editor = self.app.inventory_editor
        editor.tree.selection_set('/'.join(map(str, path)))
        editor.select()
        return editor

    def test_inventory_json_form_sync(self):
        self.switch(INVENTORY_TAB)
        editor = self.select_item((0, 0))
        editor.editors['itemCount'][0].set('27')
        editor.gene_var.set('charge，hope')
        self.assertTrue(self.app.dirty)
        self.switch(JSON_TAB)
        parsed = json.loads(self.app.json_editor.get('1.0', 'end-1c'))
        self.assertEqual(item_at(parsed, (0, 0))['itemCount'], 27)
        self.assertEqual(item_at(parsed, (0, 0))['geneGroup']['geneIds'], ['charge', 'hope'])
        item_at(parsed, (0,))['currentDurability'] = 88
        self.app.json_editor.delete('1.0', 'end')
        self.app.json_editor.insert('1.0', json.dumps(parsed))
        self.switch(INVENTORY_TAB)
        editor = self.select_item((0,))
        self.assertEqual(editor.editors['currentDurability'][0].get(), '88')
        self.switch(FORM_TAB)
        self.app.field_vars['money'].set('200')
        self.switch(INVENTORY_TAB)
        self.assertEqual(self.app._collect_active_data()['baseData']['money'], 200)
        self.assertEqual(item_at(self.app.data, (0,))['currentDurability'], 88)

    def test_invalid_draft_prevents_tab_switch(self):
        self.switch(INVENTORY_TAB)
        editor = self.select_item((0,))
        before = copy.deepcopy(self.app.data)
        editor.editors['currentDurability'][0].set('-2')
        with patch('app.messagebox.showerror') as error:
            self.switch(JSON_TAB)
            error.assert_called_once()
        self.assertEqual(self.app.tabs.get(), INVENTORY_TAB)
        self.assertEqual(self.app.data, before)

    def test_json_change_marks_dirty_programmatic_render_does_not(self):
        self.assertFalse(self.app.dirty)
        self.app._render_json()
        self.app.update()
        self.assertFalse(self.app.dirty)
        self.app.json_editor.insert('end', ' ')
        self.app.update()
        self.assertTrue(self.app.dirty)

    def test_duplicate_and_delete_keep_slots(self):
        self.switch(INVENTORY_TAB)
        editor = self.select_item((0,))
        editor.duplicate()
        self.assertEqual(editor.selected, (2,))
        self.assertEqual(item_at(self.app.data, (2,)), item_at(self.app.data, (0,)))
        with patch('inventory_ui.messagebox.askyesno', return_value=True):
            editor.delete()
        self.assertIsNone(item_at(self.app.data, (2,)))

    def test_advanced_json_rejects_capacity_change_without_applying(self):
        self.switch(JSON_TAB)
        before = copy.deepcopy(self.app.data)
        changed = copy.deepcopy(before)
        backpack(changed)['items'].append(None)
        # Even a consistent pair of longer arrays must be rejected.
        changed['farmData']['inventory']['backpack']['slotLockStates'].append(False)
        self.app.json_editor.delete('1.0', 'end')
        self.app.json_editor.insert('1.0', json.dumps(changed))
        with self.assertRaises(SaveFormatError):
            self.app._apply_json()
        self.assertEqual(self.app.data, before)
        with patch('app.messagebox.showerror') as error:
            self.app.validate_json()
            error.assert_called_once()
        with patch('app.messagebox.showerror'):
            self.switch(INVENTORY_TAB)
        self.assertEqual(self.app.tabs.get(), JSON_TAB)
        self.assertEqual(self.app.data, before)

    def test_save_and_export_block_capacity_changes(self):
        self.switch(INVENTORY_TAB)
        self.app.source_path = Path('test.data')
        container = backpack(self.app.data)
        container['items'].append(None)
        container['slotLockStates'].append(False)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder, 'output.data')
            target.write_bytes(b'unchanged')
            with patch('app.messagebox.showerror') as error:
                self.app._save_to(target)
                error.assert_called_once()
            self.assertEqual(target.read_bytes(), b'unchanged')
            export = Path(folder, 'output.json')
            with patch('app.filedialog.asksaveasfilename', return_value=str(export)), \
                    patch('app.messagebox.showerror') as error:
                self.app.export_json()
                error.assert_called_once()
            self.assertFalse(export.exists())

    def test_open_different_capacities_and_save_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            for size in (10, 20, 30, 40):
                with self.subTest(size=size):
                    data = copy.deepcopy(self.app.original_data)
                    container = backpack(data)
                    container['items'] = [None] * size
                    container['slotLockStates'] = [False] * size
                    source = Path(folder, f'{size}.json')
                    source.write_text(json.dumps(data), encoding='utf-8')
                    self.app.load_path(source)
                    self.switch(INVENTORY_TAB)
                    self.assertEqual(len(self.app.inventory_editor.tree.get_children()), size)
                    from test_inventory import SEED
                    from inventory import add_item
                    add_item(self.app.data, (), SEED)
                    target = Path(folder, f'{size}.data')
                    with patch('app.messagebox.showinfo'), patch('app.messagebox.showerror') as error:
                        self.app._save_to(target)
                        error.assert_not_called()
                    saved = load_save(target)[0]
                    self.assertEqual(len(backpack(saved)['items']), size)
                    self.assertEqual(item_at(saved, (0,)), SEED)

    def test_backpack_level_is_preserved(self):
        self.app.field_vars['backpack_level'].set('99')
        self.app._apply_form()
        self.assertEqual(self.app.data['farmData']['agentData']['backpackLevel'], 10)
        changed = copy.deepcopy(self.app.data)
        changed['farmData']['agentData']['backpackLevel'] = 99
        with self.assertRaises(SaveFormatError):
            self.app._validate_backpack_layout(changed)

    @unittest.skipUnless(os.environ.get('DOLOC_SAMPLE_DIR'), 'Real GUI sample is opt-in')
    def test_real_sample_load_and_search(self):
        path = Path(os.environ['DOLOC_SAMPLE_DIR'], 'doloc-save-0.data')
        with patch('app.messagebox.showerror') as error:
            self.app.load_path(path)
            error.assert_not_called()
        self.assertEqual(self.app.source_path, path)
        self.app.update()
        self.assertFalse(self.app.dirty)
        self.switch(INVENTORY_TAB)
        self.assertGreater(len(self.app.inventory_editor.templates), 400)
        self.app._focus_search()
        self.app.search.query.set('geneIds')
        self.app.search.refresh()
        self.assertGreater(len(self.app.search.matches), 100)


if __name__ == '__main__':
    unittest.main()
