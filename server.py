import json, os, secrets, threading, webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from core import Store
from agent import execute
from recovery import compare, repair_catalogue
from maritime import Maritime
from sessions import Sessions
from live import Live
from workspace import Workspace
BASE=Path(__file__).resolve().parent
if (BASE/'.env').exists():
    for line in (BASE/'.env').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1);os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
store=Store(Path(os.environ.get('TIME_MACHINE_DATA') or BASE/'data')); token=secrets.token_urlsafe(32); active=set(); errors={}; guard=threading.Lock()
for old in store.list_runs():
    if old['status']=='running': store.status(old['id'],'interrupted')
def sample():
    r=store.create('Prepare spring catalogue','Read supplier.csv. Supplier prices are per carton. Calculate unit prices and a 30% markup. Save catalogue.csv.')
    store.write(r,'supplier.csv','product,pack_size,carton_price\nAll-purpose cleaner,12,24\nPaper towel,6,18\nDish soap,12,20.40\nCleaning sponge,24,28.80\n')
    store.checkpoint(r,'Supplier data imported')
    store.write(r,'catalogue.csv','product,selling_price\nAll-purpose cleaner,31.20\nPaper towel,23.40\nDish soap,26.52\nCleaning sponge,37.44\n')
    store.save_messages(r,store.messages(r)+[{'role':'assistant','content':'Sample fixture: this catalogue intentionally uses carton prices as unit prices. Select the imported-data checkpoint and branch to correct the assumption.'}])
    store.checkpoint(r,'Incorrect pricing · sample fixture');store.status(r,'review');return r

def background(r):
    try: execute(store,r)
    except Exception as e: errors[r]=str(e)
    finally:
        with guard: active.discard(r)
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,status,value,kind='application/json'):
        data=json.dumps(value).encode() if kind=='application/json' else value
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
    def allowed(self):
        return self.headers.get('Host') in ('127.0.0.1:8765','localhost:8765')
    def do_GET(self):
        if not self.allowed(): return self.send(403,{'error':'Local requests only'})
        u=urlparse(self.path);q=parse_qs(u.query)
        try:
            if u.path=='/api/state':
                r=q.get('run',[''])[0]
                return self.send(200,{'runs':store.list_runs(),'token':token,'configured':bool(os.environ.get('OPENROUTER_API_KEY')),'maritimeConfigured':bool(os.environ.get('MARITIME_API_KEY')),'model':os.environ.get('OPENROUTER_MODEL','z-ai/glm-5.3-flash'),'checkpoints':store.checkpoints(r) if r else [],'files':store.files(r) if r else [],'messages':store.messages(r) if r else [],'error':errors.get(r),'active':r in active})
            if u.path=='/api/diff': return self.send(200,{'changes':compare(store,q['run'][0],q['checkpoint'][0])})
            if u.path=='/api/sessions': return self.send(200,{'sessions':Sessions(store).list()})
            if u.path=='/api/session': return self.send(200,Sessions(store).state(q['id'][0]))
            if u.path=='/api/rewind-preview': return self.send(200,Sessions(store).preview(q['session'][0],q['checkpoint'][0]))
            if u.path=='/api/file':return self.send(200,{'content':store.read(q['run'][0],q['path'][0])})
            name={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/classic':'classic.html','/classic.js':'classic.js','/classic.css':'classic.css'}.get(u.path)
            if not name:return self.send(404,{'error':'Not found'})
            kind={'html':'text/html; charset=utf-8','js':'application/javascript','css':'text/css'}[name.split('.')[-1]]
            return self.send(200,(BASE/'static'/name).read_bytes(),kind)
        except (ValueError,OSError,KeyError) as e:self.send(400,{'error':str(e)})
    def do_POST(self):
        if not self.allowed() or self.headers.get('X-Local-Token')!=token:return self.send(403,{'error':'Reload this local dashboard'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<1 or size>2_100_000:raise ValueError('Invalid request size')
            b=json.loads(self.rfile.read(size)); path=urlparse(self.path).path
            if not isinstance(b,dict): raise ValueError('Expected a JSON object')
            if path=='/api/settings':
                allowed_keys=('MARITIME_API_KEY','OPENROUTER_API_KEY','OPENROUTER_MODEL')
                for key in allowed_keys:
                    value=b.get(key,'')
                    if not isinstance(value,str) or '\n' in value or '\r' in value:raise ValueError('Invalid setting')
                for key in allowed_keys:
                    if b.get(key,'').strip():os.environ[key]=b[key].strip()
                (BASE/'.env').write_text('\n'.join(key+'='+os.environ.get(key,'') for key in allowed_keys)+'\n',encoding='utf-8')
                return self.send(200,{'ok':True})
            if path=='/api/live/create': return self.send(200,Live().create(b['user'],b['os']))
            if path=='/api/live/capture': return self.send(200,Live().capture(b['computer']))
            if path=='/api/live/action':
                engine=Sessions(store)
                resource=engine.state(b['session'])['document']['resources'].get('computer',{})
                if resource.get('state',{}).get('id')!=b['computer']:raise ValueError('Computer does not match session')
                eid=engine.effect(b['session'],secrets.token_hex(16),'external','pending',b.get('description','Live computer input; external outcome requires review'))
                result=Live().action(b['computer'],b['action'])
                return self.send(200,{'result':result,'effect':eid})
            if path=='/api/live/suggest': return self.send(200,Live().suggest(b['computer'],b['task']))
            if path.startswith('/api/session/'):
                engine=Sessions(store); workspace=Workspace(engine)
                if path=='/api/session/create': return self.send(200,{'id':engine.create(b['title'],b['resources'])})
                if path=='/api/session/checkpoint': return self.send(200,{'id':engine.checkpoint(b['session'],b['label'])})
                if path=='/api/session/update': engine.update(b['session'],b['resources']); return self.send(200,{'ok':True})
                if path=='/api/session/effect': return self.send(200,{'id':engine.effect(b['session'],b['key'],b['kind'],b['status'],b['detail'])})
                if path=='/api/session/reconcile': engine.reconcile(b['session'],b['effect'],b['status'],b['evidence']); return self.send(200,{'ok':True})
                if path=='/api/session/rewind': return self.send(200,{'id':workspace.rewind(b['session'],b['checkpoint'],b['receipt'],b.get('acknowledge'))})
                if path=='/api/session/start': return self.send(200,{'id':workspace.start(b['title'])})
                if path=='/api/session/task': return self.send(200,{'id':workspace.start_task(b['title'],b['computer'])})
                if path=='/api/session/do': return self.send(200,{'id':workspace.do(b['session'],b['description'],b['actions'],b.get('undo'),b.get('kind','change'),b.get('key'))})
                if path=='/api/session/run': return self.send(200,workspace.run(b['session'],b['cmd'],b.get('external')))
                if path=='/api/session/publish': return self.send(200,{'name':workspace.publish(b['session'],b['name'])})
                if path=='/api/session/end': workspace.end(b['session']); return self.send(200,{'ok':True})
            if path=='/api/maritime/agents': return self.send(200,{'agents':Maritime().agents()})
            if path=='/api/maritime/files': return self.send(200,Maritime().files(b['agent']))
            if path=='/api/maritime/capture': return self.send(200,{'id':Maritime().capture(store,b['agent'],b['paths'])})
            with guard:
                if b.get('run') in active and path!='/api/branch':raise ValueError('Wait for this run to finish before changing its workspace')
                if path=='/api/sample':result={'id':sample()}
                elif path=='/api/create':result={'id':store.create(b['title'],b['instruction'])}
                elif path=='/api/branch':result={'id':store.branch(b['checkpoint'],b['instruction'])}
                elif path=='/api/checkpoint':result={'id':store.checkpoint(b['run'],b['label'])}
                elif path=='/api/demo':repair_catalogue(store,b['run']);result={'ok':True}
                elif path=='/api/file':store.write(b['run'],b['path'],b['content']);result={'ok':True}
                elif path=='/api/execute':
                    store.workspace(b['run'])
                    if not os.environ.get('OPENROUTER_API_KEY'):raise ValueError('Add OPENROUTER_API_KEY to .env and restart. The sample works without a key.')
                    active.add(b['run']);errors.pop(b['run'],None)
                    threading.Thread(target=background,args=(b['run'],),daemon=True).start();result={'ok':True}
                else:return self.send(404,{'error':'Not found'})
            self.send(200,result)
        except (ValueError,KeyError,OSError) as e:self.send(400,{'error':str(e)})
if __name__=='__main__':
    print('Time Machine: http://127.0.0.1:8765 — Ctrl+C to stop',flush=True)
    if os.environ.get('NO_BROWSER')!='1':threading.Timer(.8,lambda:webbrowser.open('http://127.0.0.1:8765')).start()
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
