"""Reconstruct two patched adapter files in a separate directory; never edit the source."""
import argparse
import hashlib
import json
from pathlib import Path

def digest(data):
    return hashlib.sha256(data).hexdigest()

def prepare(source, recipe):
    files = {}
    for name in ('generate.mjs', 'lib/kuaizi_cdp.mjs'):
        row = recipe[name]
        data = (source / name).read_bytes()
        if digest(data) == row['to']:
            files[name] = data
            continue
        if digest(data) != row['from']:
            raise ValueError(f'{name}: unknown version; review changes manually')
        lines = data.decode('utf-8').splitlines(keepends=True)
        for first, last, replacement in reversed(row['edits']):
            lines[first:last] = [replacement]
        result = ''.join(lines).encode('utf-8')
        if digest(result) != row['to']:
            raise ValueError(f'{name}: reconstructed file failed checksum')
        files[name] = result
    return files

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='existing Windows adapter directory')
    parser.add_argument('--output', type=Path, help='new directory outside the adapter (default: verify only)')
    args = parser.parse_args()
    source = args.source.resolve()
    files = prepare(source, json.loads(Path(__file__).with_name('edits.json').read_text(encoding='utf-8')))
    if args.output:
        output = args.output.resolve()
        if output == source or source in output.parents:
            parser.error('output must be outside the adapter')
        output.mkdir(exist_ok=False)
        for name, data in files.items():
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    print('Verified both adapter files')

if __name__ == '__main__':
    main()
