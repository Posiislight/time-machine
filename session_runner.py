"""Embed this runner around an agent's tool dispatch to record actual actions.

Adapters own device-specific capture/execute implementations. They must declare
whether their snapshots can be reconstructed; screenshots alone cannot qualify.
"""


class SessionRunner:
    def __init__(self, sessions, session, adapters):
        self.sessions, self.session, self.adapters = sessions, session, adapters

    def checkpoint(self, label):
        # Call only at a quiescent tool-dispatch boundary. This is not a global VM barrier.
        captured = {name: adapter.capture() for name, adapter in self.adapters.items()}
        self.sessions.update(self.session, captured)
        return self.sessions.checkpoint(self.session, label)

    def act(self, resource, action, *, operation_key=None, effect_kind=None, description=None):
        adapter = self.adapters.get(resource)
        if adapter is None:
            raise ValueError('No adapter for resource')
        effect = None
        if effect_kind:
            if not operation_key or not description:
                raise ValueError('External actions require a stable operation key and description')
            # Persist before dispatch. A process crash leaves a pending action that blocks rewind.
            effect = self.sessions.effect(self.session, operation_key, effect_kind, 'pending', description)
        try:
            try:
                result = adapter.execute(action, operation_key=operation_key)
            except Exception as error:
                # Only an explicit provider statement that nothing started makes a retry safe.
                # Timeouts and lost responses stay pending: the action may have happened.
                if effect and getattr(error, 'definitely_not_started', False):
                    self.sessions.reconcile(self.session, effect, 'not_completed',
                                            'Provider reported the action did not start: ' + str(error))
                raise
            if effect:
                # The adapter must verify the remote result, not merely an HTTP acknowledgment.
                outcome = adapter.verify(result)
                if outcome.get('status') in ('completed', 'not_completed'):
                    self.sessions.reconcile(self.session, effect, outcome['status'], outcome['evidence'])
            return result
        finally:
            # Unknown or pending effects deliberately survive exceptions; never auto-retry them.
            self.checkpoint('After action / ' + resource)


def rewind_and_restore(sessions, session, checkpoint, receipt, acknowledge, adapters):
    """Commit the rewind first, then start machines for snapshot resources.

    Committing first means a stale receipt or an unreconciled effect creates no machine.
    If a restore fails, the branch and an audit event remain; machines already started
    are listed in that event so they can be ended.
    """
    branch = sessions.rewind(session, checkpoint, receipt, acknowledge)
    resources = sessions.state(branch)['document']['resources']
    created = []
    try:
        for name, resource in list(resources.items()):
            if resource['recovery'] != 'snapshot':
                continue
            adapter = adapters.get(name)
            if adapter is None:
                raise ValueError('No adapter to restore ' + name)
            state = adapter.restore(resource['state'])
            created.append(state['sandbox'])
            resources[name] = {'recovery': 'snapshot', 'state': state}
        sessions.update(branch, resources)
    except Exception as error:
        sessions.record(branch, 'restore_failed', {'error': str(error), 'machines_started': created})
        raise
    return branch
