import tempfile, unittest
from pathlib import Path
from core import Store
from recovery import compare, repair_catalogue
from maritime import Maritime

class FeatureTests(unittest.TestCase):
    def test_compare_added_removed_changed_and_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d); r=s.create('Test','Test')
            s.write(r,'a.txt','old'); s.write(r,'removed.txt','gone')
            cp=s.checkpoint(r,'Before')
            s.write(r,'a.txt','new'); s.path(r,'removed.txt').unlink(); s.write(r,'added.txt','new')
            result=compare(s,r,cp)
            self.assertEqual({x['path']:x['status'] for x in result}, {'a.txt':'changed','removed.txt':'removed','added.txt':'added'})
            self.assertIn('-old',result[0]['diff'])
    def test_demo_repairs_only_branch_with_decimal_prices(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d); r=s.create('Catalogue','Make catalogue')
            s.write(r,'supplier.csv','product,pack_size,carton_price\nSoap,12,20.40\n')
            cp=s.checkpoint(r,'Imported'); b=s.branch(cp,'Correct prices')
            repair_catalogue(s,b)
            self.assertIn('2.21',s.read(b,'catalogue.csv'))
            self.assertFalse(s.path(r,'catalogue.csv').exists())
            self.assertEqual(s.list_runs()[0]['status'],'completed')
    def test_maritime_import_uses_documented_endpoints(self):
        calls=[]
        def request(path):
            calls.append(path)
            return b'hello' if 'download?' in path else {'entries':[]}
        m=Maritime(request=request)
        with tempfile.TemporaryDirectory() as d:
            s=Store(d); r=m.capture(s,'agent-123',['/data/report.txt'])
            self.assertEqual(s.read(r,'report.txt'),'hello')
            self.assertEqual(len(s.checkpoints(r)),1)
            self.assertIn('/api/agents/agent-123/files/download?path=%2Fdata%2Freport.txt',calls)
    def test_maritime_rejects_unsafe_or_duplicate_paths(self):
        m=Maritime(request=lambda _: b'hello')
        with tempfile.TemporaryDirectory() as d:
            for paths in [['/data/../secret'],['/a/report.txt','/b/report.txt']]:
                with self.assertRaises(ValueError): m.capture(Store(d),'agent-123',paths)

if __name__=='__main__': unittest.main()
