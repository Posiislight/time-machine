"""Call the local Time Machine API: python scripts/tm.py GET /api/sessions | POST /api/session/x '{json}'"""
import json, sys, urllib.request
BASE = 'http://127.0.0.1:8765'
def call(method, path, body=None):
    token = json.load(urllib.request.urlopen(BASE + '/api/state'))['token']
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), method=method,
                                 headers={'Content-Type': 'application/json', 'X-Local-Token': token})
    try:
        with urllib.request.urlopen(req, timeout=300) as r: return json.load(r)
    except urllib.error.HTTPError as e: return {'error': e.read().decode(), 'status': e.code}
if __name__ == '__main__':
    print(json.dumps(call(sys.argv[1], sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else None), indent=1)[:3000])
