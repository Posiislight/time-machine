"""Local, immutable checkpoints. No shell execution or external side effects."""
import hashlib, json, shutil, sqlite3, threading, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,title TEXT,status TEXT,parent TEXT,created TEXT,messages TEXT);
CREATE TABLE IF NOT EXISTS checkpoints(id TEXT PRIMARY KEY,run_id TEXT,label TEXT,created TEXT);''')
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.root/'state.sqlite3'); c.row_factory=sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()
    def now(self): return datetime.now(timezone.utc).isoformat()
    def workspace(self,r):
        if not isinstance(r,str) or len(r)!=32 or any(x not in '0123456789abcdef' for x in r): raise ValueError('Invalid run ID')
        p=self.root/'runs'/r
        if not p.is_dir(): raise ValueError('Run not found')
        return p
    def create(self,title,prompt,parent=None):
        if not title.strip() or not prompt.strip(): raise ValueError('Title and instruction are required')
        r=uuid.uuid4().hex
        (self.root/'runs'/r).mkdir(parents=True)
        with self.db() as c: c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?)',(r,title,'ready',parent,self.now(),json.dumps([{'role':'user','content':prompt}])))
        return r
    def list_runs(self):
        with self.db() as c: return [dict(x) for x in c.execute('SELECT id,title,status,parent,created FROM runs ORDER BY created DESC')]
    def status(self,r,status):
        with self.db() as c: c.execute('UPDATE runs SET status=? WHERE id=?',(status,r))
    def messages(self,r):
        self.workspace(r)
        with self.db() as c: return json.loads(c.execute('SELECT messages FROM runs WHERE id=?',(r,)).fetchone()[0])
    def save_messages(self,r,m):
        with self.db() as c: c.execute('UPDATE runs SET messages=? WHERE id=?',(json.dumps(m),r))
    def path(self,r,name):
        if not isinstance(name,str) or not name or '\\' in name or ':' in name: raise ValueError('Use a relative workspace path')
        base=self.workspace(r); p=(base/name).resolve()
        if p==base or not p.is_relative_to(base): raise ValueError('Path escapes workspace')
        return p
    def write(self,r,name,text):
        if len(text.encode())>2_000_000: raise ValueError('File exceeds 2 MB limit')
        with self.lock:
            p=self.path(r,name); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding='utf-8')
    def read(self,r,name): return self.path(r,name).read_text(encoding='utf-8')[:2_000_000]
    def files(self,r):
        base=self.workspace(r)
        return [{'name':p.relative_to(base).as_posix(),'size':p.stat().st_size} for p in sorted(base.rglob('*')) if p.is_file() and not p.is_symlink()]
    def checkpoint(self,r,label):
        with self.lock:
            cp=uuid.uuid4().hex; dest=self.root/'checkpoints'/cp; dest.mkdir(parents=True)
            try:
                base=self.workspace(r)
                if any(p.is_symlink() for p in base.rglob('*')): raise ValueError('Symlinks are not supported')
                shutil.copytree(base,dest/'files')
                hashes={p.relative_to(dest/'files').as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (dest/'files').rglob('*') if p.is_file()}
                manifest={'messages':self.messages(r),'hashes':hashes}
                (dest/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
                with self.db() as c: c.execute('INSERT INTO checkpoints VALUES(?,?,?,?)',(cp,r,label,self.now()))
                return cp
            except Exception:
                shutil.rmtree(dest,ignore_errors=True); raise
    def checkpoints(self,r):
        with self.db() as c: return [dict(x) for x in c.execute('SELECT * FROM checkpoints WHERE run_id=? ORDER BY created',(r,))]
    def branch(self,cp,instruction):
        if not instruction.strip(): raise ValueError('Enter a new instruction')
        with self.lock:
            with self.db() as c:
                row=c.execute('SELECT c.*,r.title FROM checkpoints c JOIN runs r ON r.id=c.run_id WHERE c.id=?',(cp,)).fetchone()
            if not row: raise ValueError('Checkpoint not found')
            source=self.root/'checkpoints'/cp
            m=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
            for name,digest in m['hashes'].items():
                p=(source/'files'/name).resolve()
                if not p.is_relative_to((source/'files').resolve()) or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest: raise ValueError('Checkpoint integrity check failed')
            actual={p.relative_to(source/'files').as_posix() for p in (source/'files').rglob('*') if p.is_file()}
            if actual!=set(m['hashes']): raise ValueError('Checkpoint contains unexpected files')
            r=self.create(row['title']+' · branch',instruction,cp)
            shutil.copytree(source/'files',self.workspace(r),dirs_exist_ok=True)
            self.save_messages(r,m['messages']+[{'role':'user','content':instruction}])
            self.checkpoint(r,'Restored from '+row['label'])
            return r
