"""Tiny helper for the Maritime computer: python scripts/computer.py shot OUT.jpg | act '{json}'"""
import base64, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for l in (Path(__file__).resolve().parents[1] / '.env').read_text(encoding='utf-8-sig').splitlines():
    if '=' in l and not l.lstrip().startswith('#'): k, v = l.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
from live import Live
CID = os.environ['TM_COMPUTER']
L = Live()
if sys.argv[1] == 'shot':
    img = L.request('/api/v1/computers/' + CID + '/screenshot?format=jpeg&quality=80', binary=True)
    Path(sys.argv[2]).write_bytes(base64.b64decode(img['image'])); print('saved')
else:
    print(json.dumps(L.request('/api/v1/computers/' + CID + '/actions', json.loads(sys.argv[2])))[:1500])
