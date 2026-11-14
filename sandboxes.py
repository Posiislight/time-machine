"""Maritime sandbox client and a SessionRunner adapter backed by real snapshots.

Capture saves a snapshot of the running sandbox. Restore starts a NEW sandbox from
that snapshot and leaves the original untouched. Sandbox secrets stay in memory in
the client; nothing returned by `capture()` or `restore()` contains them, because the
session database is not encrypted.
"""
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse

BASE = 'https://api.maritime.sh'
SANDBOX_ID = re.compile(r'sbx-[A-Za-z0-9]{1,64}\Z')
NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,62}\Z')
DATA_PLANE_SUFFIX = '.mtm.sh'


class SandboxError(ValueError):
    """A refusal or transport failure. `definitely_not_started` is True only when the
    provider states the command did not begin, which is the only case safe to retry."""

    def __init__(self, message, code='error', status=None, hint=None, definitely_not_started=False):
        super().__init__(message)
        self.code, self.status, self.hint = code, status, hint
        self.definitely_not_started = definitely_not_started


def default_request(method, url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read(2_000_001)
            status = response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(2_000_001), error.code
    if len(raw) > 2_000_000:
        raise SandboxError('Provider response exceeds the 2 MB limit', code='response_too_large')
    try:
        return status, (json.loads(raw) if raw else {})
    except ValueError:
        return status, {'message': 'Provider returned a non-JSON response'}


class Sandboxes:
    def __init__(self, request=None):
        self.request = request or default_request
        self.key = os.environ.get('MARITIME_API_KEY', '').strip()
        self.boxes = {}  # sandbox id -> {'url', 'secret'}; memory only

    # -- plumbing ---------------------------------------------------------
    def _send(self, method, url, body=None, headers=None):
        try:
            status, payload = self.request(method, url, body, headers or {})
        except SandboxError:
            raise
        except (TimeoutError, OSError):
            # The request may have reached Maritime. Outcome unknown, so never "not started".
            raise SandboxError('Maritime could not be reached; the outcome is unknown', code='unreachable') from None
        if status >= 400:
            detail = payload.get('detail') if isinstance(payload.get('detail'), dict) else payload
            raise SandboxError(str(detail.get('message') or detail.get('code') or 'Maritime returned HTTP ' + str(status)),
                               code=str(detail.get('code') or 'http_' + str(status)), status=status,
                               hint=detail.get('hint'), definitely_not_started=detail.get('execution_started') is False)
        return payload

    def _api(self, method, path, body=None):
        if not self.key:
            raise ValueError('Set MARITIME_API_KEY in .env and restart the server.')
        return self._send(method, BASE + path, body, {'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})

    @staticmethod
    def sandbox_id(value):
        if not isinstance(value, str) or not SANDBOX_ID.match(value):
            raise ValueError('Invalid sandbox ID')
        return value

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not NAME.match(value):
            raise ValueError('Names use lowercase letters, digits and hyphens only')
        return value

    def _remember(self, box):
        url = box.get('dataPlaneUrl')
        parsed = urlparse(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != 'https' or not (parsed.hostname or '').endswith(DATA_PLANE_SUFFIX):
            raise SandboxError('Refusing a data-plane address outside Maritime', code='bad_data_plane')
        self.boxes[self.sandbox_id(box['id'])] = {'url': url.rstrip('/'), 'secret': box.get('secret', '')}

    # -- sandboxes --------------------------------------------------------
    def create(self, name, source='base', size='small', idle_seconds=900):
        body = {'name': self.name(name), 'from': self.name(source), 'size': size,
                'onIdle': 'pause', 'idleTimeoutSeconds': idle_seconds}
        box = self._api('POST', '/v1/sandboxes', body)
        self._remember(box)
        return box

    def connect(self, sandbox):
        box = self._api('GET', '/v1/sandboxes/' + self.sandbox_id(sandbox))
        self._remember(box)
        return box

    def save(self, sandbox, snapshot):
        return self._api('POST', '/v1/sandboxes/' + self.sandbox_id(sandbox) + '/save', {'name': self.name(snapshot)})

    def kill(self, sandbox):
        return self._api('DELETE', '/v1/sandboxes/' + self.sandbox_id(sandbox))

    def snapshots(self):
        return self._api('GET', '/v1/snapshots').get('data', [])

    def delete_snapshot(self, snapshot):
        return self._api('DELETE', '/v1/snapshots/' + self.name(snapshot))

    def run(self, sandbox, cmd):
        if not isinstance(cmd, str) or not cmd.strip() or len(cmd) > 100_000:
            raise ValueError('A command is required')
        if self.sandbox_id(sandbox) not in self.boxes:
            self.connect(sandbox)
        box = self.boxes[sandbox]
        return self._send('POST', box['url'] + '/commands', {'cmd': cmd},
                          {'X-Maritime-Token': box['secret'], 'Content-Type': 'application/json'})


class SandboxAdapter:
    """Resource adapter for SessionRunner. `verifier(result)` must check the REAL outcome
    (merchant, mail provider, database) and return {'status', 'evidence'}. Without one,
    effects stay pending and block rewind; that is deliberate."""

    def __init__(self, client, sandbox, verifier=None):
        self.client, self.sandbox, self.verifier = client, client.sandbox_id(sandbox), verifier

    def capture(self):
        snapshot = 'tm-' + uuid.uuid4().hex[:16]
        self.client.save(self.sandbox, snapshot)
        return {'recovery': 'snapshot', 'state': {'sandbox': self.sandbox, 'snapshot': snapshot}}

    def execute(self, action, operation_key=None):
        # operation_key is ledger-only here: Maritime documents no idempotency key for commands.
        if action.get('publish'):
            # A named snapshot others can start machines from. Rewinding never deletes it.
            return self.client.save(self.sandbox, action['publish'])
        return self.client.run(self.sandbox, action.get('cmd'))

    def verify(self, result):
        if self.verifier:
            return self.verifier(result)
        if isinstance(result, dict) and result.get('sourceSandboxId') == self.sandbox and result.get('name'):
            # A publish: ask Maritime whether the snapshot really exists rather than trusting the reply.
            for snap in self.client.snapshots():
                if snap.get('name') == result['name'] and snap.get('sourceSandboxId') == self.sandbox:
                    return {'status': 'completed', 'evidence': 'Maritime lists snapshot "' + result['name'] + '" from this machine.'}
            return {'status': 'unknown', 'evidence': 'Maritime did not list the snapshot after saving it.'}
        return {'status': 'unknown', 'evidence': 'No verifier configured; the command result is not proof of the outcome.'}

    def restore(self, state):
        box = self.client.create('tm-restore-' + uuid.uuid4().hex[:10], source=state['snapshot'])
        return {'sandbox': box['id'], 'snapshot': state['snapshot']}
