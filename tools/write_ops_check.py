#!/usr/bin/env python3
"""Write a single key to .ops_checks.json. Usage: write_ops_check.py KEY RC OUTPUT [CMD]"""
import json, sys, time
from datetime import datetime
from pathlib import Path

key = sys.argv[1]
rc = int(sys.argv[2])
output = sys.argv[3] if len(sys.argv) > 3 else ''
cmd = sys.argv[4] if len(sys.argv) > 4 else ''

ops_path = Path(__file__).resolve().parent.parent / '.ops_checks.json'
ops = {}
if ops_path.exists():
    try:
        ops = json.loads(ops_path.read_text(encoding='utf-8'))
    except Exception:
        pass
now_ts = time.time()
ops[key] = {
    'title': key,
    'rc': rc,
    'ok': rc == 0,
    'updated_ts': now_ts,
    'updated_at': datetime.fromtimestamp(now_ts).strftime('%Y-%m-%d %H:%M:%S'),
    'cmd': cmd,
    'output': output[:300],
}
tmp = ops_path.with_suffix('.json.tmp')
tmp.write_text(json.dumps(ops, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
tmp.replace(ops_path)
print(f'[ops_check] {key}: ok={rc==0}')
