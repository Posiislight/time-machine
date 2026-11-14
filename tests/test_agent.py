import tempfile, unittest
from pathlib import Path
from core import Store
from agent import execute
class AgentTests(unittest.TestCase):
    def test_tool_write_and_complete_recoverable(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)); r=s.create('Report','Create a report')
            replies=iter([{'role':'assistant','content':None,'tool_calls':[{'id':'t1','type':'function','function':{'name':'write_file','arguments':'{"path":"report.md","content":"Report ready"}'}}]},{'role':'assistant','content':'Done'}])
            execute(s,r,call=lambda _:next(replies))
            self.assertEqual(s.read(r,'report.md'),'Report ready')
            self.assertEqual(s.list_runs()[0]['status'],'completed')
            b=s.branch(s.checkpoints(r)[1]['id'],'Revise report')
            self.assertEqual(s.read(b,'report.md'),'Report ready')
            self.assertEqual(s.messages(b)[-2]['role'],'tool')
    def test_failure_sets_error_and_keeps_initial_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d));r=s.create('Test','Test')
            def fail(_): raise ValueError('Unavailable')
            with self.assertRaises(ValueError): execute(s,r,call=fail)
            self.assertEqual(s.list_runs()[0]['status'],'error')
            self.assertEqual(len(s.checkpoints(r)),1)
