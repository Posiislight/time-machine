"""Transactional session history and conservative recovery planning.

Resource documents are logical snapshots, never claims of VM restoration.
External effects belong to a lineage and survive every branch.
"""
import hashlib
import json
import uuid


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


class Sessions:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, lineage TEXT, parent TEXT, document TEXT);
                CREATE TABLE IF NOT EXISTS session_checkpoints(id TEXT PRIMARY KEY, session TEXT, label TEXT, document TEXT);
                CREATE TABLE IF NOT EXISTS session_effects(id TEXT PRIMARY KEY, lineage TEXT, operation_key TEXT, kind TEXT, status TEXT, detail TEXT, UNIQUE(lineage, operation_key));
                CREATE TABLE IF NOT EXISTS session_events(seq INTEGER PRIMARY KEY AUTOINCREMENT, lineage TEXT, session TEXT, kind TEXT, detail TEXT, created TEXT);
            ''')
            try:  # databases made before undo recipes existed
                db.execute('ALTER TABLE session_effects ADD COLUMN undo TEXT')
            except Exception:
                pass

    def _row(self, db, session):
        row = db.execute('SELECT * FROM sessions WHERE id=?', (session,)).fetchone()
        if not row:
            raise ValueError('Session not found')
        return dict(row)

    def _event(self, db, row, kind, detail):
        db.execute('INSERT INTO session_events(lineage,session,kind,detail,created) VALUES(?,?,?,?,?)',
                   (row['lineage'], row['id'], kind, encoded(detail), self.store.now()))

    def create(self, title, resources):
        if not isinstance(title, str) or not title.strip() or not isinstance(resources, dict):
            raise ValueError('Title and resource object required')
        for name, resource in resources.items():
            if not isinstance(resource, dict) or resource.get('recovery') not in ('logical', 'snapshot', 'unavailable'):
                raise ValueError('Each resource needs logical, snapshot or unavailable recovery capability')
        sid = uuid.uuid4().hex
        document = {'title': title, 'resources': resources}
        with self.store.db() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (sid, sid, None, encoded(document)))
            self._event(db, {'id': sid, 'lineage': sid}, 'created', {'title': title})
        return sid

    def list(self):
        with self.store.db() as db:
            return [{'id': r['id'], 'parent': r['parent'], 'title': json.loads(r['document'])['title']}
                    for r in db.execute('SELECT * FROM sessions ORDER BY rowid DESC')]

    def state(self, sid):
        with self.store.db() as db:
            row = self._row(db, sid)
            return {**row, 'document': json.loads(row['document']),
                    'checkpoints': [dict(r) for r in db.execute('SELECT id,label FROM session_checkpoints WHERE session=?', (sid,))],
                    'effects': [dict(r) for r in db.execute('SELECT * FROM session_effects WHERE lineage=?', (row['lineage'],))],
                    'events': [dict(r) for r in db.execute('SELECT * FROM session_events WHERE lineage=? ORDER BY seq', (row['lineage'],))]}

    def checkpoint(self, sid, label):
        cid = uuid.uuid4().hex
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, sid)
            db.execute('INSERT INTO session_checkpoints VALUES(?,?,?,?)', (cid, sid, label, row['document']))
            self._event(db, row, 'checkpoint', {'id': cid, 'label': label})
        return cid

    def update(self, sid, resources):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, sid)
            doc = json.loads(row['document'])
            if set(resources) != set(doc['resources']):
                raise ValueError('Update must contain all session resources')
            for name, resource in resources.items():
                if resource.get('recovery') != doc['resources'][name]['recovery']:
                    raise ValueError('Recovery capabilities cannot be changed during update')
            doc['resources'] = resources
            db.execute('UPDATE sessions SET document=? WHERE id=?', (encoded(doc), sid))
            self._event(db, row, 'resources_updated', {'resources': list(resources)})

    def record(self, sid, kind, detail):
        """Append an audit event, for outcomes that happen outside this database."""
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._event(db, self._row(db, sid), kind, detail)

    def effect(self, sid, key, kind, status, detail, undo=None):
        if not key or kind not in ('payment', 'message', 'booking', 'external', 'change') or status not in ('pending', 'unknown', 'completed', 'not_completed'):
            raise ValueError('Invalid external action')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, sid)
            existing = db.execute('SELECT * FROM session_effects WHERE lineage=? AND operation_key=?', (row['lineage'], key)).fetchone()
            if existing:
                raise ValueError('Operation already recorded; reconcile its outcome before retrying')
            eid = uuid.uuid4().hex
            db.execute('INSERT INTO session_effects(id,lineage,operation_key,kind,status,detail,undo) VALUES(?,?,?,?,?,?,?)',
                       (eid, row['lineage'], key, kind, status, detail, None if undo is None else encoded(undo)))
            self._event(db, row, 'external_action', {'id': eid, 'kind': kind, 'status': status, 'detail': detail})
        return eid

    def reconcile(self, sid, eid, status, evidence):
        if status not in ('completed', 'not_completed') or not isinstance(evidence, str) or not evidence.strip():
            raise ValueError('A definite outcome and verification evidence are required')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, sid)
            effect = db.execute('SELECT * FROM session_effects WHERE id=? AND lineage=?', (eid, row['lineage'])).fetchone()
            if not effect or effect['status'] not in ('unknown', 'pending'):
                raise ValueError('Only unresolved actions can be reconciled')
            db.execute('UPDATE session_effects SET status=? WHERE id=?', (status, eid))
            self._event(db, row, 'reconciled', {'id': eid, 'status': status, 'evidence': evidence})

    def mark_undone(self, sid, eid, evidence):
        """Record that a rewind really reversed a completed action that carried an undo recipe."""
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError('Evidence is required')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, sid)
            effect = db.execute('SELECT * FROM session_effects WHERE id=? AND lineage=?', (eid, row['lineage'])).fetchone()
            if not effect or effect['status'] != 'completed' or not effect['undo']:
                raise ValueError('Only completed actions with an undo recipe can be marked undone')
            db.execute('UPDATE session_effects SET status=? WHERE id=?', ('undone', eid))
            self._event(db, row, 'undone', {'id': eid, 'evidence': evidence})

    def _plan(self, db, sid, cid):
        row = self._row(db, sid)
        cp = db.execute('SELECT * FROM session_checkpoints WHERE id=? AND session=?', (cid, sid)).fetchone()
        if not cp:
            raise ValueError('Checkpoint does not belong to session')
        document = json.loads(cp['document'])
        effects = [dict(r) for r in db.execute('SELECT * FROM session_effects WHERE lineage=? ORDER BY id', (row['lineage'],))]
        revision = db.execute('SELECT MAX(seq) FROM session_events WHERE lineage=?', (row['lineage'],)).fetchone()[0]
        warnings = []
        for e in effects:
            if e['status'] in ('pending', 'unknown'):
                warnings.append(f"{e['kind']}: {e['detail']}. Outcome uncertain; verify with the service before resuming.")
            elif e['status'] == 'completed' and e.get('undo'):
                warnings.append(f"{e['kind']}: {e['detail']}. Rewind will undo this action.")
            elif e['status'] == 'completed':
                warnings.append(f"{e['kind']}: {e['detail']}. Rewind cannot undo this action. It remains in the shared action ledger.")
        resources = []
        for name, value in document['resources'].items():
            mode = value['recovery']
            description = {'logical': 'The agent picks up from this point',
                           'snapshot': 'Start a new machine from the saved snapshot; the current machine is left untouched'}.get(
                               mode, 'Observation only; live machine or network restoration is unavailable')
            resources.append({'name': name, 'mode': mode, 'description': description})
            if mode == 'snapshot':
                warnings.append(name + ': a new machine will be started from the snapshot. The current machine keeps running and billing until you end it.')
            elif mode != 'logical':
                warnings.append(name + ': historical observation only; live state cannot be restored by this adapter.')
        plan = {'session': sid, 'checkpoint': cid, 'revision': revision, 'resources': resources,
                'effects': effects, 'warnings': warnings,
                'blocked': any(e['status'] in ('pending', 'unknown') for e in effects)}
        plan['receipt'] = hashlib.sha256(encoded(plan).encode()).hexdigest()
        return plan

    def preview(self, sid, cid):
        with self.store.db() as db:
            db.execute('BEGIN')
            return self._plan(db, sid, cid)

    def rewind(self, sid, cid, receipt, acknowledge=False):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            plan = self._plan(db, sid, cid)
            if receipt != plan['receipt']:
                raise ValueError('Session changed. Review a fresh rewind preview.')
            if plan['blocked']:
                raise ValueError('Rewind blocked until uncertain external actions are reconciled')
            if acknowledge is not True:
                raise ValueError('Review and acknowledge rewind consequences first')
            row = self._row(db, sid)
            original = json.loads(db.execute('SELECT document FROM session_checkpoints WHERE id=?', (cid,)).fetchone()[0])
            # Only supported state enters the restored branch; observations are not live state.
            observations = {k: v for k, v in original['resources'].items() if v['recovery'] == 'unavailable'}
            kept = {k: v for k, v in original['resources'].items() if v['recovery'] in ('logical', 'snapshot')}
            for value in kept.values():
                if value['recovery'] == 'snapshot':
                    # Not live until a machine is started from the snapshot; never point at the old machine.
                    value['state'] = {'snapshot': value['state']['snapshot'], 'sandbox': None, 'restore': 'pending'}
            original['resources'] = kept
            original['historical_observations'] = observations
            original['title'] += ' / recovered'
            branch = uuid.uuid4().hex
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (branch, row['lineage'], cid, encoded(original)))
            self._event(db, {'id': branch, 'lineage': row['lineage']}, 'rewound', {'checkpoint': cid, 'receipt': receipt})
            return branch
