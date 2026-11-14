"""Live sessions: a Maritime machine plus the session history that makes it recoverable.

Every step runs through SessionRunner, so each one leaves a snapshot to rewind to and any
real-world action is written to the ledger before it is attempted.
"""
import json
import os
import re
import threading
import uuid

from live import Live
from sandboxes import SandboxAdapter, Sandboxes
from session_runner import SessionRunner, rewind_and_restore

KINDS = ('payment', 'message', 'booking', 'external', 'change')
COMPUTER = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')


def short(text, n=60):
    text = ' '.join(text.split())
    return text if len(text) <= n else text[:n - 1] + '…'


def clip(text, n=6000):
    text = text if isinstance(text, str) else ''
    return text if len(text) <= n else text[:n] + '\n… output cut'


def segments(actions, most=40):
    """Split a recipe before each page load (ctrl+l) so every call stays short."""
    parts = []
    for a in actions:
        if not parts or (a.get('action') == 'key' and a.get('text') == 'ctrl+l') or len(parts[-1]) >= most:
            parts.append([])
        parts[-1].append(a)
    return parts


class Workspace:
    # One lock and one client per process, so a handler can build a Workspace per request.
    lock = threading.Lock()
    shared = None

    def __init__(self, sessions, client=None):
        self.sessions, self.injected = sessions, client

    def client(self):
        if self.injected is not None:
            return self.injected
        if Workspace.shared is None:
            Workspace.shared = Sandboxes()
        Workspace.shared.key = os.environ.get('MARITIME_API_KEY', '').strip()  # picks up keys saved after startup
        return Workspace.shared

    def _sandbox(self, sid):
        state = self.sessions.state(sid)
        machine = state['document']['resources'].get('machine')
        box = machine and machine['state'].get('sandbox')
        if not box:
            raise ValueError('This session has no running machine')
        if any(e['kind'] == 'machine_ended' and e['session'] == sid for e in state['events']):
            raise ValueError('This machine has been ended. Rewind to an earlier snapshot to continue.')
        return box

    def _runner(self, sid, sandbox):
        return SessionRunner(self.sessions, sid, {'machine': SandboxAdapter(self.client(), sandbox)})

    def start(self, title):
        if not isinstance(title, str) or not title.strip():
            raise ValueError('Give the session a name')
        with self.lock:
            client = self.client()
            box = client.create('tm-' + uuid.uuid4().hex[:10])
            sid = self.sessions.create(title.strip()[:120],
                                       {'machine': {'recovery': 'snapshot', 'state': {'sandbox': box['id'], 'snapshot': None}}})
            try:
                self._runner(sid, box['id']).checkpoint('Session started')
            except Exception:
                try:
                    client.kill(box['id'])
                except Exception:
                    pass
                raise
            return sid

    def run(self, sid, cmd, external=None):
        if not isinstance(cmd, str) or not cmd.strip() or len(cmd) > 4000:
            raise ValueError('Enter a command to run')
        kind = description = None
        if external:
            kind, description = external.get('kind', 'external'), (external.get('description') or '').strip()
            if kind not in KINDS or not description:
                raise ValueError('Describe the real-world action this command performs')
        with self.lock:
            runner = self._runner(sid, self._sandbox(sid))
            detail = {'cmd': cmd}
            try:
                result = runner.act('machine', {'cmd': cmd}, operation_key=uuid.uuid4().hex, effect_kind=kind,
                                    description=description, label='After: ' + short(cmd))
                detail.update(exitCode=result.get('exitCode'), stdout=clip(result.get('stdout')), stderr=clip(result.get('stderr')))
                return detail
            except Exception as error:
                detail['error'] = str(error)
                raise
            finally:
                self.sessions.record(sid, 'command', detail)

    def publish(self, sid, name):
        name = Sandboxes.name(name)
        with self.lock:
            runner = self._runner(sid, self._sandbox(sid))
            # The key is the release name: publishing it twice in one lineage is refused, even after a rewind.
            runner.act('machine', {'publish': name}, operation_key='publish-' + name, effect_kind='external',
                       description='Published release "' + name + '" as a Maritime snapshot', label='After publishing ' + name)
            return name

    # -- tasks done on a Maritime computer (a desktop an agent clicks through) --------------
    def start_task(self, title, computer):
        if not isinstance(computer, str) or not COMPUTER.match(computer):
            raise ValueError('Invalid computer ID')
        if not isinstance(title, str) or not title.strip():
            raise ValueError('Give the task a name')
        sid = self.sessions.create(title.strip()[:120], {'agent': {'recovery': 'logical', 'state': {'computer': computer, 'step': 'Ready'}}})
        self.sessions.checkpoint(sid, 'Before the task')
        return sid

    def _computer(self, sid):
        agent = self.sessions.state(sid)['document']['resources'].get('agent') or {}
        computer = agent.get('state', {}).get('computer')
        if not computer or not COMPUTER.match(computer):
            raise ValueError('This session has no computer')
        return computer

    def do(self, sid, description, actions, undo=None, kind='change', key=None):
        """Record an outside action (with its undo recipe) BEFORE running it on the computer."""
        computer = self._computer(sid)
        if not isinstance(description, str) or not description.strip() or kind not in KINDS:
            raise ValueError('Describe the action')
        recipe = {'computer': computer, 'actions': undo} if undo else None
        with self.lock:
            eid = self.sessions.effect(sid, key or uuid.uuid4().hex, kind, 'pending', description.strip(), recipe)
            if actions:   # no actions: the caller performs it elsewhere, then reconciles
                Live().batch(computer, actions)   # a failure here leaves the action pending: it may have happened
            return eid

    def undo_recorded(self, sid):
        """Run the undo recipe of every completed action that has one. Returns what was undone."""
        undone = []
        for e in self.sessions.state(sid)['effects']:
            if e['status'] != 'completed' or not e.get('undo'):
                continue
            recipe = json.loads(e['undo'])
            try:
                for part in segments(recipe['actions']):   # short calls: one long batch can time out mid-way
                    Live().batch(recipe['computer'], part)
            except Exception as error:
                self.sessions.record(sid, 'undo_failed', {'id': e['id'], 'error': str(error)})
                raise
            self.sessions.mark_undone(sid, e['id'], 'Ran the recorded undo steps on the computer.')
            undone.append(e['detail'])
        return undone

    def end(self, sid):
        with self.lock:
            sandbox = self._sandbox(sid)
            self.client().kill(sandbox)
            self.sessions.record(sid, 'machine_ended', {'sandbox': sandbox})

    def rewind(self, sid, checkpoint, receipt, acknowledge):
        with self.lock:
            machine = self.sessions.state(sid)['document']['resources'].get('machine')
            current = (machine or {}).get('state', {}).get('sandbox') or 'sbx-restore'
            adapters = {'machine': SandboxAdapter(self.client(), current)}
            branch = rewind_and_restore(self.sessions, sid, checkpoint, receipt, acknowledge, adapters)
            self.undo_recorded(branch)
            if machine:
                label = next((c['label'] for c in self.sessions.state(sid)['checkpoints'] if c['id'] == checkpoint), 'snapshot')
                self._runner(branch, self.sessions.state(branch)['document']['resources']['machine']['state']['sandbox']) \
                    .checkpoint('Restored from "' + label + '"')
            return branch
