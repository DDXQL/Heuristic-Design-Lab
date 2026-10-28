"""Query saved file locations offline; never reads the old project or runs experiments."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query', help='part of the original path or filename')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--verify', action='store_true', help='read matched saved files and verify SHA256')
    args = parser.parse_args()
    if not args.query.strip() or args.limit < 1:
        parser.error('nonempty query and positive limit required')
    index = json.loads(gzip.decompress(Path(__file__).with_name('逐文件保存索引.json.gz').read_bytes()))
    query = args.query.removeprefix('/Users/DDXQL/Documents/大学/硕士/代码/')
    matches = [(key, value) for key, value in index.items() if query in key]
    rows = []
    for original, value in matches[:args.limit]:
        row = {'原路径': original, '保存位置': value['destination'],
               '字节数': value['bytes'], 'SHA256': value['sha256']}
        if args.verify:
            saved = Path(value['destination'])
            digest = hashlib.sha256()
            with saved.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(block)
            row['校验通过'] = digest.hexdigest() == value['sha256']
        rows.append(row)
    print(json.dumps({'匹配总数': len(matches), '显示数': len(rows), '文件': rows,
                      'API调用': 0, '求解': 0}, ensure_ascii=False, indent=2))
    if any(row.get('校验通过') is False for row in rows):
        raise SystemExit(2)

if __name__ == '__main__':
    main()
