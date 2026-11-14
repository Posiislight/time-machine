// Time Machine dashboard. One story: timeline -> pick a snapshot -> see what a rewind does -> rewind.
// All text from the server is inserted with textContent, never as HTML.
const $ = id => document.getElementById(id);
let token = '', current = null, selected = '', maritime = false;

function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el[k] = v;
    else if (v !== false && v != null) el.setAttribute(k, v === true ? '' : v);
  }
  el.append(...kids.flat().filter(x => x != null && x !== false));
  return el;
}

function notice(text, error = false) {
  const n = $('notice');
  n.textContent = text || '';
  n.hidden = !text;
  n.className = error ? 'error' : '';
  if (text) window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function api(path, data) {
  if (!token) token = (await (await fetch('/api/state')).json()).token;
  const init = data ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Local-Token': token }, body: JSON.stringify(data) } : {};
  let res = await fetch(path, init);
  if (res.status === 403 && data) {            // server restarted: new token
    token = (await (await fetch('/api/state')).json()).token;
    init.headers['X-Local-Token'] = token;
    res = await fetch(path, init);
  }
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || 'Request failed');
  return body;
}
const safe = fn => async (...a) => { try { await fn(...a); } catch (e) { notice(e.message, true); } };

// ---------- sidebar ----------
async function refreshSessions() {
  const { sessions } = await api('/api/sessions');
  $('sessions').replaceChildren(...(sessions.length ? sessions.map(s =>
    h('button', { 'aria-current': current === s.id, onclick: safe(() => openSession(s.id)) }, (s.parent ? '↳ ' : '') + s.title)
  ) : [h('p', { class: 'muted small' }, 'No sessions yet.')]));
  const st = await api('/api/state');
  maritime = st.maritimeConfigured;
  $('connection').textContent = maritime ? 'Maritime connected' : 'No Maritime key yet';
  $('startBtn').disabled = !maritime;
  $('startHint').textContent = maritime ? 'This starts a Maritime machine on your account. Machines you start here use your plan credit.' : 'Add your Maritime API key first (bottom left), then start a machine.';
}

// ---------- home ----------
function showHome() {
  current = null; selected = '';
  history.replaceState(null, '', '#');
  $('home').hidden = false; $('session').hidden = true; notice('');
  safe(refreshSessions)();
}

// ---------- session ----------
const KIND = { payment: 'Payment', message: 'Message sent', booking: 'Booking', external: 'External action', change: 'Change' };
const STATUS = { completed: 'Done', unknown: 'Unknown', pending: 'Unconfirmed', not_completed: 'Did not happen', undone: 'Undone' };
const parse = s => { try { return JSON.parse(s); } catch { return {}; } };

async function openSession(id, cp = '') {
  const s = await api('/api/session?id=' + encodeURIComponent(id));
  current = id; selected = '';
  history.replaceState(null, '', '#s=' + id);
  $('home').hidden = true; $('session').hidden = false;
  const m = s.document.resources.machine, box = m && m.state && m.state.sandbox;
  const ended = s.events.some(e => e.kind === 'machine_ended' && e.session === s.id);
  const live = !!box && !ended;
  $('title').textContent = s.document.title;
  $('kicker').textContent = s.parent ? 'Recovered branch' : 'Session';
  const pc = s.document.resources.agent && s.document.resources.agent.state && s.document.resources.agent.state.computer;
  $('badge').textContent = pc ? 'Maritime computer' : !box ? 'No machine' : ended ? 'Machine ended' : 'Machine ' + box;
  $('badge').className = 'badge' + (live ? ' live' : '');
  $('endMachine').hidden = !live;
  $('work').hidden = !live;
  $('output').hidden = true;
  renderGuide(s, box);
  renderTimeline(s);
  $('preview').replaceChildren(h('p', { class: 'empty' }, 'Pick a snapshot on the timeline.'));
  await refreshSessions();
  if (cp) await choose(s, cp);
}

function renderGuide(s, box) {
  const g = $('guide');
  if (s.parent) {
    g.hidden = false;
    g.replaceChildren(h('strong', {}, 'Recovered. '), 'This branch runs on a new machine started from the snapshot you chose. Actions already taken stay on record, and doing the same one again is refused. The machine you rewound from is still running until you end it.');
  } else g.hidden = true;
}

function renderTimeline(s) {
  const effects = Object.fromEntries(s.effects.map(e => [e.id, e]));
  const evidence = {};
  for (const e of s.events) if (e.kind === 'reconciled') { const d = parse(e.detail); evidence[d.id] = d.evidence; }
  const items = [];
  for (const e of s.events) {
    const d = parse(e.detail);
    if (e.kind === 'checkpoint') {
      const own = e.session === s.id;
      items.push(h('li', {}, h('span', { class: 'dot snap' }),
        own ? h('button', { class: 'snapbtn', 'aria-pressed': false, 'data-cp': d.id, onclick: safe(() => choose(s, d.id)) }, d.label, h('span', { class: 'tag' }, 'snapshot'))
            : h('div', { class: 'note' }, d.label + ' (earlier session)')));
    } else if (e.kind === 'external_action') {
      const now = effects[d.id] || d, ev = evidence[d.id];
      const mark = now.status === 'completed' ? ['ok', '✓'] : now.status === 'undone' ? ['snap', '↩'] : now.status === 'not_completed' ? ['none', '–'] : ['warn', '!'];
      items.push(h('li', {}, h('span', { class: 'dot ' + mark[0] }, mark[1]),
        h('div', { class: 'effect' },
          h('div', { class: 'kind' }, KIND[d.kind] || d.kind, h('span', { class: 'chip ' + now.status }, STATUS[now.status] || now.status)),
          h('div', {}, d.detail),
          ev ? h('div', { class: 'note' }, 'Checked: ' + ev) : null,
          now.status === 'completed' && !now.undo ? h('div', { class: 'note' }, 'A rewind cannot undo this.') : null,
          now.status === 'completed' && now.undo ? h('div', { class: 'note' }, 'A rewind will undo this.') : null,
          now.status === 'undone' ? h('div', { class: 'note' }, 'Undone by the rewind.') : null)));
    } else if (e.kind === 'command') {
      const out = [d.stdout, d.stderr, d.error].filter(Boolean).join(String.fromCharCode(10)).trim();
      items.push(h('li', {}, h('span', { class: 'dot cmd' }, '›'),
        h('div', { class: 'cmd' }, h('code', {}, d.cmd), out ? h('pre', {}, out.slice(0, 600)) : null,
          d.error || d.exitCode ? h('div', { class: 'note' }, d.error ? 'Did not finish' : 'Exit code ' + d.exitCode) : null)));
    } else if (e.kind === 'machine_ended') {
      items.push(h('li', {}, h('span', { class: 'dot none' }, '■'), h('div', { class: 'note' }, 'Machine ended')));
    } else if (e.kind === 'rewound') {
      items.push(h('li', {}, h('span', { class: 'dot snap' }, '↩'), h('div', { class: 'note' }, 'Rewound here from an earlier snapshot')));
    } else if (e.kind === 'restore_failed') {
      items.push(h('li', {}, h('span', { class: 'dot warn' }, '!'), h('div', { class: 'note' }, 'Machine restore failed: ' + (d.error || 'unknown error'))));
    }
  }
  const step = Object.values(s.document.resources).map(r => r.state && r.state.step).find(Boolean);
  items.push(h('li', {}, h('span', { class: 'dot now' }), h('div', { class: 'now' }, step ? 'Now: ' + step : 'Now')));
  $('timeline').replaceChildren(...items);
}

async function choose(s, cp) {
  selected = cp;
  history.replaceState(null, '', '#s=' + s.id + '&c=' + cp);
  document.querySelectorAll('.snapbtn').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.cp === cp)));
  const plan = await api('/api/rewind-preview?session=' + encodeURIComponent(s.id) + '&checkpoint=' + encodeURIComponent(cp));
  const label = (s.checkpoints.find(c => c.id === cp) || {}).label || 'this snapshot';
  renderPreview(s, plan, label);
}

function renderPreview(s, plan, label) {
  const back = plan.resources.filter(r => r.mode !== 'unavailable');
  const only = plan.resources.filter(r => r.mode === 'unavailable');
  const done = plan.effects.filter(e => e.status === 'completed' && !e.undo);
  const reversible = plan.effects.filter(e => e.status === 'completed' && e.undo);
  const open = plan.effects.filter(e => ['pending', 'unknown'].includes(e.status));
  const blocks = [h('h3', {}, 'Rewind to “' + label + '”')];

  blocks.push(h('div', { class: 'block comes' }, h('h3', {}, 'Comes back'),
    h('ul', {}, ...(back.length || reversible.length ? [...back.map(r => h('li', {}, h('strong', {}, r.name + ': '), r.description)), ...reversible.map(e => h('li', {}, h('strong', {}, 'Undone: '), e.detail))] : [h('li', {}, 'Nothing can be restored from this snapshot.')]))));

  const stays = [...done.map(e => h('li', {}, (KIND[e.kind] || e.kind) + ': ' + e.detail + '. Cannot be undone; it stays on record.')),
                 ...only.map(r => h('li', {}, r.name + ': recorded for reference only, not restored.'))];
  if (stays.length) blocks.push(h('div', { class: 'block stays' }, h('h3', {}, 'Stays as it is'), h('ul', {}, ...stays)));

  if (open.length) {
    blocks.push(h('div', { class: 'block check' }, h('h3', {}, 'Check this first'),
      h('p', { class: 'note' }, 'We cannot tell whether these happened. Rewinding is blocked until you confirm each one with the service itself.'),
      ...open.map(e => {
        const input = h('input', { 'aria-label': 'How you checked', placeholder: 'How did you check? e.g. order confirmation number' });
        const send = status => safe(async () => {
          await api('/api/session/reconcile', { session: s.id, effect: e.id, status, evidence: input.value });
          await openSession(s.id, selected);
        });
        return h('div', { class: 'verify' }, h('div', {}, (KIND[e.kind] || e.kind) + ': ' + e.detail), input,
          h('div', { class: 'row' }, h('button', { onclick: send('completed') }, 'It went through'), h('button', { onclick: send('not_completed') }, 'It did not happen')));
      })));
  }

  const ack = h('input', { type: 'checkbox', id: 'ack' });
  const go = h('button', { class: 'primary', disabled: true, onclick: safe(async () => {
    const r = await api('/api/session/rewind', { session: s.id, checkpoint: plan.checkpoint, receipt: plan.receipt, acknowledge: ack.checked });
    await openSession(r.id);
    notice('Rewound. The agent can continue from the recovered branch.');
  }) }, 'Rewind to here');
  ack.disabled = plan.blocked;
  ack.onchange = () => { go.disabled = plan.blocked || !ack.checked; };
  blocks.push(h('div', { class: 'block confirm' },
    h('label', {}, ack, 'I understand what comes back and what does not.'),
    h('div', { class: 'row' }, go),
    plan.blocked ? h('p', { class: 'note' }, 'Blocked until the checks above are done.') : null));
  $('preview').replaceChildren(...blocks);
}

// ---------- wiring ----------
$('newSession').onclick = () => { showHome(); $('sessionName').focus(); };
$('startForm').onsubmit = async e => {
  e.preventDefault();
  const btn = $('startBtn'); btn.disabled = true; btn.textContent = 'Starting the machine…';
  try {
    const { id } = await api('/api/session/start', { title: $('sessionName').value });
    $('sessionName').value = '';
    await openSession(id);
  } catch (err) { notice(err.message, true); }
  finally { btn.textContent = 'Start a machine'; btn.disabled = !maritime; }
};
$('external').onchange = () => { $('externalWhat').hidden = !$('external').checked; if ($('external').checked) $('externalWhat').focus(); };
$('runForm').onsubmit = async e => {
  e.preventDefault();
  const btn = $('runBtn'); btn.disabled = true; btn.textContent = 'Running…';
  const out = $('output'); out.hidden = true;
  try {
    const external = $('external').checked ? { kind: 'external', description: $('externalWhat').value } : undefined;
    const r = await api('/api/session/run', { session: current, cmd: $('cmd').value, external });
    $('cmd').value = ''; $('external').checked = false; $('externalWhat').hidden = true; $('externalWhat').value = '';
    await openSession(current);
    out.textContent = [r.stdout, r.stderr].filter(Boolean).join(String.fromCharCode(10)).trim() || '(no output)';
    out.hidden = false;
  } catch (err) { await openSession(current).catch(() => {}); notice(err.message, true); }
  finally { btn.textContent = 'Run'; btn.disabled = false; }
};
$('publishForm').onsubmit = async e => {
  e.preventDefault();
  const btn = $('publishBtn'); btn.disabled = true; btn.textContent = 'Publishing…';
  try {
    const { name } = await api('/api/session/publish', { session: current, name: $('releaseName').value });
    $('releaseName').value = '';
    await openSession(current);
    notice('Published ' + name + '. Maritime lists it, and a rewind will not remove it.');
  } catch (err) { await openSession(current).catch(() => {}); notice(err.message, true); }
  finally { btn.textContent = 'Publish'; btn.disabled = false; }
};
$('endMachine').onclick = safe(async () => {
  await api('/api/session/end', { session: current });
  await openSession(current);
  notice('Machine ended. Its snapshots are kept, so you can still rewind.');
});
$('brand').onclick = e => { e.preventDefault(); showHome(); };

$('openSettings').onclick = () => { $('settingsStatus').textContent = ''; $('settingsDialog').showModal(); };
$('cancelSettings').onclick = () => $('settingsDialog').close();
$('settingsForm').onsubmit = async e => {
  e.preventDefault();
  try {
    await api('/api/settings', { MARITIME_API_KEY: $('maritimeKey').value, OPENROUTER_API_KEY: $('routerKey').value, OPENROUTER_MODEL: '' });
    $('maritimeKey').value = ''; $('routerKey').value = '';
    $('settingsDialog').close(); notice('Saved locally.'); await refreshSessions();
  } catch (err) { $('settingsStatus').textContent = err.message; }
};

(async () => {
  const q = new URLSearchParams(location.hash.slice(1));
  if (q.get('s')) await safe(() => openSession(q.get('s'), q.get('c') || ''))();
  else showHome();
})();
