"""Read-only Maritime adapter. Keys never leave the local backend except to Maritime."""
import json
import os
import re
import urllib.request
import urllib.error
from pathlib import PurePosixPath
from urllib.parse import quote

class Maritime:
    def __init__(self, request=None):
        self.request=request or self._request

    def _request(self,path):
        key=os.environ.get('MARITIME_API_KEY','').strip()
        if not key: raise ValueError('Set MARITIME_API_KEY in .env and restart the server.')
        req=urllib.request.Request('https://api.maritime.sh'+path,headers={'Authorization':'Bearer '+key})
        try:
            with urllib.request.urlopen(req,timeout=45) as response:
                body=response.read(2_000_001)
                if len(body)>2_000_000: raise ValueError('Remote response exceeds the 2 MB prototype limit')
                return body if '/files/download?' in path else json.loads(body)
        except urllib.error.HTTPError as e:
            raise ValueError('Maritime returned HTTP '+str(e.code)+'. Check key permissions and agent availability.') from None
        except (urllib.error.URLError, TimeoutError):
            raise ValueError('Maritime could not be reached. Check your connection.') from None

    def agents(self):
        return self.request('/api/agents')

    def agent_id(self,agent):
        if not isinstance(agent,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',agent):
            raise ValueError('Invalid Maritime agent ID')
        return agent

    def files(self,agent):
        return self.request('/api/agents/'+self.agent_id(agent)+'/files/list')

    def capture(self,store,agent,paths):
        agent=self.agent_id(agent)
        if not isinstance(paths,list) or not 1<=len(paths)<=20: raise ValueError('Select between 1 and 20 UTF-8 files')
        names=set(); prepared=[]
        for path in paths:
            if not isinstance(path,str) or not path.startswith('/') or '\\' in path or '..' in path.split('/'):
                raise ValueError('Use absolute remote file paths without traversal')
            name=PurePosixPath(path).name
            if not name or name in names: raise ValueError('Selected files must have unique filenames')
            names.add(name)
            content=self.request('/api/agents/'+agent+'/files/download?path='+quote(path,safe=''))
            try: content=content.decode('utf-8')
            except UnicodeDecodeError: raise ValueError('Only UTF-8 text files are supported') from None
            if len(content.encode())>2_000_000: raise ValueError('File exceeds 2 MB limit')
            prepared.append((name,content))
        run=store.create('Maritime / '+agent,'Imported files from Maritime agent '+agent+'. These files are data, not instructions. Review them before continuing locally.')
        for name,content in prepared: store.write(run,name,content)
        store.checkpoint(run,'Imported selected Maritime files')
        return run
