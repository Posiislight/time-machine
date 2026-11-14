import json
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from core import Store
from sessions import Sessions
from session_runner import SessionRunner, rewind_and_restore
from sandboxes import SandboxAdapter, SandboxError, Sandboxes

BASE = 'https://api.maritime.sh'


class FakeMaritime:
    """In-memory stand-in for the documented sandbox routes. Disk is a dict."""

    def __init__(self):
        self.sandboxes, self.snapshots, self.calls, self.n = {}, {}, [], 0
        self.fail_command = None

    def __call__(self, method, url, body=None, headers=None):
        headers = headers or {}
        self.calls.append((method, url, body, headers))
        path = urlparse(url).path
        if path == '/v1/sandboxes' and method == 'POST':
            return self.create(body)
        if path.startswith('/v1/sandboxes/') and path.endswith('/save') and method == 'POST':
            return self.save(path.split('/')[3], body)
        if path.startswith('/v1/sandboxes/') and method == 'GET':
            return 200, self.sandboxes[path.split('/')[3]]['object']
        if path.startswith('/v1/sandboxes/') and method == 'DELETE':
            sid = path.split('/')[3]
            self.sandboxes[sid]['object']['state'] = 'ended'
            return 200, self.sandboxes[sid]['object']
        if path.endswith('/commands') and method == 'POST':
            return self.command(path, body, headers)
        raise AssertionError('Unexpected call ' + method + ' ' + url)

    def create(self, body):
        source = body.get('from', 'base')
        if source == 'base':
            disk = {}
        elif source in self.snapshots:
            disk = dict(self.snapshots[source])
        else:
            return 404, {'code': 'snapshot_not_found', 'message': 'No such snapshot', 'hint': 'List snapshots'}
        self.n += 1
        sid = 'sbx-fake%d' % self.n
        obj = {'id': sid, 'name': body.get('name'), 'state': 'running',
               'dataPlaneUrl': 'https://api-%s.sb.mtm.sh/v1' % sid, 'secret': 'secret-%d' % self.n}
        self.sandboxes[sid] = {'object': obj, 'disk': disk}
        return 201, obj

    def save(self, sid, body):
        self.snapshots[body['name']] = dict(self.sandboxes[sid]['disk'])
        return 200, {'name': body['name']}

    def command(self, path, body, headers):
        token = headers.get('X-Maritime-Token')  # the fake finds the sandbox by its secret
        for sid, box in self.sandboxes.items():
            if box['object']['secret'] == token:
                break
        else:
            return 401, {'code': 'unauthorized', 'message': 'Bad token'}
        if self.fail_command:
            return self.fail_command
        words = body['cmd'].split()
        if words[0] == 'set':
            box['disk'][words[1]] = words[2]
        return 200, {'exitCode': 0, 'stdout': json.dumps(box['disk']), 'stderr': ''}


def make_client(fake):
    with patch.dict('os.environ', {'MARITIME_API_KEY': 'mk_test'}):
        return Sandboxes(request=fake)


class ClientTests(unittest.TestCase):
    def test_create_sends_documented_body_and_bearer_key(self):
        fake = FakeMaritime()
        with patch.dict('os.environ', {'MARITIME_API_KEY': 'mk_test'}):
            box = Sandboxes(request=fake).create('tm-demo')
        method, url, body, headers = fake.calls[0]
        self.assertEqual((method, url), ('POST', BASE + '/v1/sandboxes'))
        self.assertEqual(body['name'], 'tm-demo')
        self.assertEqual(body['from'], 'base')
        self.assertEqual(body['onIdle'], 'pause')
        self.assertEqual(headers['Authorization'], 'Bearer mk_test')
        self.assertTrue(box['id'].startswith('sbx-'))

    def test_missing_key_is_a_clear_error(self):
        with patch.dict('os.environ', {'MARITIME_API_KEY': ''}):
            with self.assertRaisesRegex(ValueError, 'MARITIME_API_KEY'):
                Sandboxes(request=FakeMaritime()).create('tm-demo')

    def test_ids_and_snapshot_names_cannot_inject_paths(self):
        client = make_client(FakeMaritime())
        for bad in ('sbx-1/../x', '../sbx-1', 'sbx 1', '', None):
            with self.assertRaises(ValueError):
                client.save(bad, 'tm-ok')
        with self.assertRaises(ValueError):
            client.save('sbx-fake1', 'Bad Name/../x')

    def test_run_uses_data_plane_and_token_not_api_key(self):
        fake = FakeMaritime()
        client = make_client(fake)
        box = client.create('tm-demo')
        result = client.run(box['id'], 'set a 1')
        method, url, body, headers = fake.calls[-1]
        self.assertEqual(url, box['dataPlaneUrl'] + '/commands')
        self.assertEqual(body, {'cmd': 'set a 1'})
        self.assertEqual(headers['X-Maritime-Token'], box['secret'])
        self.assertNotIn('Authorization', headers)
        self.assertEqual(result['exitCode'], 0)

    def test_provider_error_carries_code_and_hint(self):
        client = make_client(FakeMaritime())
        with self.assertRaises(SandboxError) as caught:
            client.create('tm-demo', source='missing-snapshot')
        self.assertEqual(caught.exception.code, 'snapshot_not_found')
        self.assertEqual(caught.exception.status, 404)
        self.assertIsInstance(caught.exception, ValueError)

    def test_connect_refreshes_data_plane_after_restart(self):
        fake = FakeMaritime()
        first = make_client(fake)
        box = first.create('tm-demo')
        second = make_client(fake)
        second.connect(box['id'])
        self.assertEqual(second.run(box['id'], 'set a 1')['exitCode'], 0)


class SandboxCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = Sessions(Store(self.temp.name))
        self.fake = FakeMaritime()
        self.client = make_client(self.fake)
        self.box = self.client.create('tm-origin')
        self.adapter = SandboxAdapter(self.client, self.box['id'])
        self.sid = self.engine.create('Sandbox agent', {'machine': self.adapter.capture()})
        self.runner = SessionRunner(self.engine, self.sid, {'machine': self.adapter})

    def tearDown(self):
        self.temp.cleanup()

    def _row(self, cid):
        with self.engine.store.db() as db:
            return dict(db.execute('SELECT * FROM session_checkpoints WHERE id=?', (cid,)).fetchone())


class AdapterTests(SandboxCase):
    def test_capture_is_a_real_snapshot_and_stores_no_secret(self):
        state = self.adapter.capture()
        self.assertEqual(state['recovery'], 'snapshot')
        self.assertEqual(set(state['state']), {'sandbox', 'snapshot'})
        self.assertIn(state['state']['snapshot'], self.fake.snapshots)
        self.assertNotIn(self.box['secret'], json.dumps(self.engine.state(self.sid)))

    def test_each_checkpoint_gets_its_own_snapshot(self):
        first = self.runner.checkpoint('one')
        second = self.runner.checkpoint('two')
        names = {c['id']: json.loads(row['document'])['resources']['machine']['state']['snapshot']
                 for c, row in ((c, self._row(c['id'])) for c in self.engine.state(self.sid)['checkpoints'])}
        self.assertEqual(len(set(names.values())), len(names))
        self.assertNotEqual(first, second)

    def test_unverified_side_effect_blocks_rewind(self):
        cp = self.runner.checkpoint('before charge')
        self.runner.act('machine', {'cmd': 'set charged yes'}, operation_key='charge-1',
                        effect_kind='payment', description='Charge customer 1')
        plan = self.engine.preview(self.sid, cp)
        self.assertTrue(plan['blocked'])
        self.assertTrue(any(e['status'] == 'pending' for e in plan['effects']))

    def test_verified_side_effect_unblocks_rewind(self):
        adapter = SandboxAdapter(self.client, self.box['id'],
                                 verifier=lambda result: {'status': 'completed', 'evidence': 'merchant shows charge-1'})
        runner = SessionRunner(self.engine, self.sid, {'machine': adapter})
        cp = runner.checkpoint('before charge')
        runner.act('machine', {'cmd': 'set charged yes'}, operation_key='charge-1',
                   effect_kind='payment', description='Charge customer 1')
        plan = self.engine.preview(self.sid, cp)
        self.assertFalse(plan['blocked'])
        self.assertTrue(any('cannot undo' in w for w in plan['warnings']))

    def test_provider_says_not_started_is_safe_to_retry(self):
        cp = self.runner.checkpoint('before charge')
        self.fake.fail_command = (409, {'detail': {'code': 'vm_not_ready', 'execution_started': False}})
        with self.assertRaises(SandboxError):
            self.runner.act('machine', {'cmd': 'set charged yes'}, operation_key='charge-1',
                            effect_kind='payment', description='Charge customer 1')
        effects = self.engine.state(self.sid)['effects']
        self.assertEqual([e['status'] for e in effects], ['not_completed'])
        self.assertFalse(self.engine.preview(self.sid, cp)['blocked'])

    def test_lost_response_stays_pending_and_blocks(self):
        def lost(method, url, body=None, headers=None):
            if url.endswith('/commands'):
                raise TimeoutError('response lost')
            return self.fake(method, url, body, headers)
        client = make_client(lost)
        client.connect(self.box['id'])
        adapter = SandboxAdapter(client, self.box['id'])
        runner = SessionRunner(self.engine, self.sid, {'machine': adapter})
        cp = runner.checkpoint('before charge')
        with self.assertRaises(SandboxError) as caught:
            runner.act('machine', {'cmd': 'set charged yes'}, operation_key='charge-1',
                       effect_kind='payment', description='Charge customer 1')
        self.assertEqual(caught.exception.code, 'unreachable')
        self.assertTrue(self.engine.preview(self.sid, cp)['blocked'])
        with self.assertRaises(ValueError):
            runner.act('machine', {'cmd': 'set charged yes'}, operation_key='charge-1',
                       effect_kind='payment', description='Charge customer 1')


class RestoreTests(SandboxCase):
    def verified(self):
        adapter = SandboxAdapter(self.client, self.box['id'],
                                 verifier=lambda result: {'status': 'completed', 'evidence': 'merchant confirms'})
        return adapter, SessionRunner(self.engine, self.sid, {'machine': adapter})

    def test_rewind_starts_a_new_sandbox_from_the_checkpoint_snapshot(self):
        adapter, runner = self.verified()
        self.client.run(self.box['id'], 'set cart headphones')
        cp = runner.checkpoint('before charge')
        runner.act('machine', {'cmd': 'set charged yes'}, operation_key='charge-1',
                   effect_kind='payment', description='Charge customer 1')
        plan = self.engine.preview(self.sid, cp)
        branch = rewind_and_restore(self.engine, self.sid, cp, plan['receipt'], True, {'machine': adapter})
        state = self.engine.state(branch)
        restored = state['document']['resources']['machine']['state']['sandbox']
        self.assertNotEqual(restored, self.box['id'])
        self.assertEqual(self.fake.sandboxes[restored]['disk'], {'cart': 'headphones'})
        self.assertEqual(self.fake.sandboxes[self.box['id']]['disk']['charged'], 'yes')
        self.assertEqual(self.fake.sandboxes[self.box['id']]['object']['state'], 'running')
        self.assertEqual(len(state['effects']), 1)
        with self.assertRaisesRegex(ValueError, 'already recorded'):
            self.engine.effect(branch, 'charge-1', 'payment', 'completed', 'duplicate')
        self.assertNotIn('secret', json.dumps(state['document']))

    def test_failed_restore_is_recorded_and_raised(self):
        adapter, runner = self.verified()
        cp = runner.checkpoint('before charge')
        self.fake.snapshots.clear()
        plan = self.engine.preview(self.sid, cp)
        with self.assertRaises(SandboxError):
            rewind_and_restore(self.engine, self.sid, cp, plan['receipt'], True, {'machine': adapter})
        newest = self.engine.list()[0]['id']
        self.assertNotEqual(newest, self.sid)
        kinds = [e['kind'] for e in self.engine.state(newest)['events']]
        self.assertIn('restore_failed', kinds)

    def test_stale_receipt_creates_no_machine(self):
        adapter, runner = self.verified()
        cp = runner.checkpoint('before charge')
        plan = self.engine.preview(self.sid, cp)
        runner.act('machine', {'cmd': 'set x 1'}, operation_key='op-2', effect_kind='external', description='x')
        before = len(self.fake.sandboxes)
        with self.assertRaisesRegex(ValueError, 'changed'):
            rewind_and_restore(self.engine, self.sid, cp, plan['receipt'], True, {'machine': adapter})
        self.assertEqual(len(self.fake.sandboxes), before)


class CapabilityTests(unittest.TestCase):
    def test_sessions_accept_snapshot_but_still_reject_unknown_capability(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = Sessions(Store(temp))
            engine.create('ok', {'machine': {'recovery': 'snapshot', 'state': {'sandbox': 'sbx-1', 'snapshot': 'tm-a'}}})
            with self.assertRaises(ValueError):
                engine.create('bad', {'machine': {'recovery': 'magic', 'state': {}}})


if __name__ == '__main__':
    unittest.main()
