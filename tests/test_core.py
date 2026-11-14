import tempfile, unittest
from pathlib import Path
from core import Store

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(Path(self.tmp.name))
    def tearDown(self): self.tmp.cleanup()
    def test_branch_restores_files_and_context_without_changing_original(self):
        r = self.s.create('Catalogue', 'Extract products')
        self.s.write(r, 'products.csv', 'price\n24\n')
        history = [{'role':'user','content':'Prices are per carton'}]
        self.s.save_messages(r, history)
        cp = self.s.checkpoint(r, 'Extracted')
        self.s.write(r, 'products.csv', 'price\n999\n')
        b = self.s.branch(cp, 'Divide by pack size')
        self.assertEqual(self.s.read(b,'products.csv'), 'price\n24\n')
        self.assertEqual(self.s.read(r,'products.csv'), 'price\n999\n')
        self.assertEqual(self.s.messages(b)[:-1], history)
        self.assertEqual(self.s.messages(b)[-1]['content'], 'Divide by pack size')
    def test_rejects_paths_outside_workspace(self):
        r = self.s.create('Test','Test')
        for path in ['../secret', '/etc/passwd', 'C:\\secret', '..\\secret']:
            with self.assertRaises(ValueError): self.s.write(r,path,'bad')
    def test_corrupt_checkpoint_cannot_be_restored(self):
        r = self.s.create('Test','Test')
        self.s.write(r,'a.txt','original')
        cp = self.s.checkpoint(r,'Saved')
        (self.s.root/'checkpoints'/cp/'files'/'a.txt').write_text('tampered')
        with self.assertRaises(ValueError): self.s.branch(cp,'Continue')
    def test_data_survives_reopen(self):
        r=self.s.create('Persistent','hello')
        self.s.write(r,'hello.txt','saved')
        other=Store(self.s.root)
        self.assertEqual(other.read(r,'hello.txt'),'saved')
        self.assertEqual(other.list_runs()[0]['title'],'Persistent')

if __name__=='__main__': unittest.main()
