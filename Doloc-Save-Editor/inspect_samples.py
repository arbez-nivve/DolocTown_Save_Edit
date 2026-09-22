"""Print a bounded schema summary without changing sample saves."""
import collections
import json
import sys
from pathlib import Path

for source in Path(sys.argv[1]).glob('*.json'):
    data = json.loads(source.read_text(encoding='utf-8-sig'))
    if 'farmData' not in data:
        continue
    types, genes, properties = {}, set(), collections.Counter()
    def walk(value, path=''):
        if isinstance(value, dict):
            if isinstance(value.get('itemName'), str) and 'itemCount' in value:
                types.setdefault(value.get('$type', '(base item)'), (path, value))
                properties.update(value.keys())
            for key, child in value.items():
                if key in ('geneIds', 'geneNames', 'unlockedGeneNames') and isinstance(child, list):
                    genes.update(g for g in child if isinstance(g, str))
                if key == 'geneId' and isinstance(child, str):
                    genes.add(child)
                walk(child, path + '/' + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, path + '/' + str(index))
    walk(data)
    print('\nSAMPLE', source.name, 'version', data['baseData'].get('version'))
    print('ITEM FIELDS', dict(properties))
    print('GENES', sorted(genes))
    for kind, (path, value) in types.items():
        print(kind, path, json.dumps(value, ensure_ascii=False)[:900])
