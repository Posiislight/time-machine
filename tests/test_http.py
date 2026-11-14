import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import server
from core import Store

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch.object(server,'store',Store(self.temp.name));self.patch.start()
    def tearDown(self):
        self.patch.stop();self.temp.cleanup()
    def request(self,path,data=None,token=True):
        import io
        body=b'' if data is None else json.dumps(data).encode()
        headers='Host: 127.0.0.1:8765\r\nContent-Length: '+str(len(body))+'\r\n'
        if token:headers+='X-Local-Token: '+server.token+'\r\n'
        raw=(('GET' if data is None else 'POST')+' '+path+' HTTP/1.0\r\n'+headers+'\r\n').encode()+body
        class Connection:
            def __init__(self): self.output=bytearray()
            def makefile(self,*args): return io.BytesIO(raw)
            def sendall(self,value): self.output.extend(value)
        connection=Connection()
        server.Handler(connection,('127.0.0.1',12345),None)
        head,body=bytes(connection.output).split(b'\r\n\r\n',1)
        return int(head.split()[1]),json.loads(body)
    def test_full_sample_branch_repair_diff_and_persistence(self):
        status,result=self.request('/api/sample',{});self.assertEqual(status,200)
        original=result['id'];_,state=self.request('/api/state?run='+original)
        checkpoint=state['checkpoints'][0]['id']
        _,branch=self.request('/api/branch',{'checkpoint':checkpoint,'instruction':'Correct unit prices'})
        run=branch['id'];self.assertEqual(self.request('/api/demo',{'run':run})[0],200)
        _,file=self.request('/api/file?run='+run+'&path=catalogue.csv')
        self.assertIn('2.21',file['content'])
        _,diff=self.request('/api/diff?run='+run+'&checkpoint='+checkpoint)
        self.assertEqual(next(x['status'] for x in diff['changes'] if x['path']=='catalogue.csv'),'added')
        self.assertIn('31.20',server.store.read(original,'catalogue.csv'))
        self.assertEqual(Store(self.temp.name).read(run,'catalogue.csv'),file['content'])
    def test_session_preview_acknowledgment_and_rewind_http(self):
        status,result=self.request('/api/session/demo',{})
        self.assertEqual(status,200)
        sid=result['id']
        _,state=self.request('/api/session?id='+sid)
        cp=state['checkpoints'][0]['id']
        _,plan=self.request('/api/rewind-preview?session='+sid+'&checkpoint='+cp)
        body={'session':sid,'checkpoint':cp,'receipt':plan['receipt']}
        self.assertEqual(self.request('/api/session/rewind',body)[0],400)
        body['acknowledge']=True
        status,branch=self.request('/api/session/rewind',body)
        self.assertEqual(status,200)
        _,recovered=self.request('/api/session?id='+branch['id'])
        self.assertEqual(len(recovered['effects']),2)

    def test_unauthorized_and_invalid_mutations_are_rejected(self):
        self.assertEqual(self.request('/api/sample',{},token=False)[0],403)
        self.assertEqual(self.request('/api/create',[])[0],400)
        self.assertEqual(self.request('/api/demo',{'run':'../outside'})[0],400)

if __name__=='__main__':unittest.main()
