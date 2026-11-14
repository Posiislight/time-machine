import tempfile
import unittest
from unittest.mock import patch

from core import Store
from sessions import Sessions
from workspace import Workspace
from test_sandboxes import FakeMaritime, make_client


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fake = FakeMaritime()
        self.sessions = Sessions(Store(self.temp.name))
        self.ws = Workspace(self.sessions, make_client(self.fake))

    def tearDown(self):
        self.temp.cleanup()

    def labels(self, sid):
        return [c['label'] for c in self.sessions.state(sid)['checkpoints']]

    def test_every_step_leaves_a_snapshot_and_output(self):
        sid = self.ws.start('Build page')
        out = self.ws.run(sid, 'set page hello')
        self.assertEqual(out['exitCode'], 0)
        self.assertEqual(self.labels(sid), ['Session started', 'After: set page hello'])
        self.assertIn('command', [e['kind'] for e in self.sessions.state(sid)['events']])

    def test_publish_is_verified_and_cannot_be_repeated(self):
        sid = self.ws.start('Build page')
        self.ws.publish(sid, 'release-one')
        effect = self.sessions.state(sid)['effects'][0]
        self.assertEqual(effect['status'], 'completed')
        with self.assertRaises(ValueError):
            self.ws.publish(sid, 'release-one')

    def test_rewind_restores_machine_but_keeps_published_release(self):
        sid = self.ws.start('Build page')
        self.ws.run(sid, 'set page good')
        self.ws.publish(sid, 'release-one')
        self.ws.run(sid, 'set page broken')
        cp = next(c['id'] for c in self.sessions.state(sid)['checkpoints'] if c['label'] == 'After: set page good')
        plan = self.sessions.preview(sid, cp)
        branch = self.ws.rewind(sid, cp, plan['receipt'], True)
        box = self.sessions.state(branch)['document']['resources']['machine']['state']['sandbox']
        self.assertIn('"page": "good"', self.ws.run(branch, 'set other 1')['stdout'])
        self.assertNotEqual(box, self.sessions.state(sid)['document']['resources']['machine']['state']['sandbox'])
        with self.assertRaises(ValueError):
            self.ws.publish(branch, 'release-one')
        self.assertTrue(self.labels(branch)[0].startswith('Restored from'))

    def test_ended_machine_refuses_commands(self):
        sid = self.ws.start('Build page')
        self.ws.end(sid)
        with self.assertRaises(ValueError):
            self.ws.run(sid, 'set a b')

    def test_external_command_stays_unconfirmed_and_blocks_rewind(self):
        sid = self.ws.start('Build page')
        cp = self.sessions.state(sid)['checkpoints'][0]['id']
        self.ws.run(sid, 'set sent yes', external={'kind': 'message', 'description': 'Sent invoice email'})
        self.assertTrue(self.sessions.preview(sid, cp)['blocked'])

    def test_rewind_runs_undo_recipes_and_keeps_the_rest(self):
        computer = '11111111-2222-3333-4444-555555555555'
        sid = self.ws.start_task('Tidy inbox', computer)
        cp = self.sessions.state(sid)['checkpoints'][0]['id']
        with patch('workspace.Live') as live:
            archived = self.ws.do(sid, 'Archived 10 emails', [{'action': 'key', 'text': 'e'}], undo=[{'action': 'key', 'text': 'z'}])
            sent = self.ws.do(sid, 'Sent 2 replies', [{'action': 'key', 'text': 's'}])
            self.sessions.reconcile(sid, archived, 'completed', 'Checked Gmail')
            self.sessions.reconcile(sid, sent, 'completed', 'Checked Sent folder')
            plan = self.sessions.preview(sid, cp)
            self.assertTrue(any('will undo' in w for w in plan['warnings']))
            self.assertTrue(any('cannot undo' in w for w in plan['warnings']))
            branch = self.ws.rewind(sid, cp, plan['receipt'], True)
            self.assertEqual(live.return_value.batch.call_args_list[-1].args[1], [{'action': 'key', 'text': 'z'}])
        status = {e['id']: e['status'] for e in self.sessions.state(branch)['effects']}
        self.assertEqual(status, {archived: 'undone', sent: 'completed'})


if __name__ == '__main__':
    unittest.main()
