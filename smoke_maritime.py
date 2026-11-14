"""Live smoke test against real Maritime. Uses a little trial credit; always cleans up.
Run: python smoke_maritime.py"""
import os, secrets, sys
from pathlib import Path
env = Path(__file__).with_name('.env')
if env.exists():
    for line in env.read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
from sandboxes import Sandboxes, SandboxError

m, tag = Sandboxes(), 'tm-smoke-' + secrets.token_hex(3)
boxes, snaps = [], []
def step(name, fn):
    try: r = fn(); print('OK  ', name, str(r)[:160]); return r
    except (SandboxError, ValueError) as e: print('FAIL', name, '->', e, getattr(e, 'code', ''), getattr(e, 'status', '')); raise
try:
    a = step('create sandbox', lambda: m.create(tag + '-a')); boxes.append(a['id'])
    step('write file', lambda: m.run(a['id'], 'echo marker-' + tag + ' > /tmp/m.txt'))
    snaps.append(tag + '-snap'); step('save snapshot', lambda: m.save(a['id'], snaps[0]))
    step('change file after snapshot', lambda: m.run(a['id'], 'echo changed > /tmp/m.txt'))
    b = step('restore into new sandbox', lambda: m.create(tag + '-b', source=snaps[0])); boxes.append(b['id'])
    out = step('read file on restored', lambda: m.run(b['id'], 'cat /tmp/m.txt'))
    print('RESTORED OK' if tag in str(out) else 'RESTORE MISMATCH', out)
except Exception as e:
    print('stopped:', type(e).__name__, e); sys.exitcode = 1
finally:
    for i in boxes:
        try: m.kill(i); print('cleaned sandbox', i)
        except Exception as e: print('cleanup failed sandbox', i, e)
    for s in snaps:
        try: m.delete_snapshot(s); print('cleaned snapshot', s)
        except Exception as e: print('cleanup failed snapshot', s, e)
