// Adds a "Time Machine" tab and slide-over panel to Maritime pages.
// Everything inside lives in a closed Shadow DOM; all text uses textContent. It never changes or reads Maritime's own page.
(() => {
  if (document.getElementById('time-machine-root')) return;
  const APP = 'http://127.0.0.1:8765/';
  const host = document.createElement('div');
  host.id = 'time-machine-root';
  const root = host.attachShadow({ mode: 'closed' });
  root.innerHTML = `<style>
    :host{all:initial}
    *{box-sizing:border-box;font:13px/1.5 ui-sans-serif,system-ui,"Segoe UI",sans-serif}
    .tab{position:fixed;right:0;top:50%;transform:translateY(-50%);z-index:2147483646;background:#0a0a0a;color:#fff;border:1px solid #333;border-right:0;border-radius:8px 0 0 8px;padding:10px 12px;cursor:pointer;writing-mode:vertical-rl;font-weight:600;letter-spacing:.3px}
    .tab:hover{background:#1c1c1c}
    .panel{position:fixed;top:0;right:0;height:100vh;width:min(380px,100vw);z-index:2147483647;background:#0a0a0a;color:#d4d4d4;border-left:1px solid #262626;display:none;flex-direction:column;box-shadow:-12px 0 40px #0008}
    .panel.open{display:flex}
    header{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid #262626}
    header b{color:#fff;font-size:15px}
    header small{display:block;color:#8f8f8f;font-size:11px}
    button,a.btn{cursor:pointer;border:1px solid #262626;border-radius:8px;padding:8px 12px;background:transparent;color:#d4d4d4;font-weight:500;text-decoration:none;display:inline-block}
    button:hover,a.btn:hover{background:#1c1c1c}
    a.primary{background:#fff;color:#000;border-color:#fff}a.primary:hover{background:#e5e5e5}
    .body{padding:16px 18px;overflow:auto;flex:1;display:flex;flex-direction:column;gap:14px}
    h4{margin:0;color:#fff;font-size:13px}
    .muted{color:#8f8f8f;font-size:12px}
    .list{display:flex;flex-direction:column;gap:6px}
    .list button{text-align:left}
    ol{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px;border-left:1px solid #262626;padding-left:14px}
    li{position:relative;border:1px solid #262626;border-radius:8px;padding:7px 10px;background:#111}
    li::before{content:"";position:absolute;left:-19px;top:12px;width:9px;height:9px;border-radius:50%;background:#0a0a0a;border:2px solid #555}
    li.snap{border-color:#1e3a4a}li.snap::before{border-color:#7dd3fc}
    li.done::before{border-color:#4ade80}li.warn{border-color:#4a3b10}li.warn::before{border-color:#fbbf24}
    .k{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#8f8f8f}
    .cta{display:flex;gap:8px;flex-wrap:wrap}
    .note{border:1px solid #4a3b10;background:#17130a;color:#fbbf24;border-radius:8px;padding:9px 12px;font-size:12px}
  </style>
  <button class="tab" aria-label="Open Time Machine panel">↶ Time Machine</button>
  <aside class="panel" role="dialog" aria-label="Time Machine">
    <header><div><b>↶ Time Machine</b><small>Rewind an agent safely</small></div><button class="close" aria-label="Close">✕</button></header>
    <div class="body"></div>
  </aside>`;
  const tab = root.querySelector('.tab'), panel = root.querySelector('.panel'), body = root.querySelector('.body');

  const h = (tag, cls, ...kids) => { const e = document.createElement(tag); if (cls) e.className = cls; e.append(...kids.filter(k => k != null)); return e; };
  const ask = msg => new Promise(res => chrome.runtime.sendMessage(msg, r => res(r || { ok: false, error: 'No response' })));
  const parse = s => { try { return JSON.parse(s); } catch { return {}; } };
  const link = (text, href, primary) => { const a = h('a', 'btn' + (primary ? ' primary' : ''), text); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; };
  const show = (...nodes) => body.replaceChildren(...nodes);

  async function home() {
    show(h('p', 'muted', 'Loading…'));
    const r = await ask({ type: 'sessions' });
    if (!r.ok) return show(h('p', '', r.offline ? 'Time Machine is not running on this computer.' : r.error),
      h('p', 'muted', 'Start it with “python server.py”, then reopen this panel.'));
    const list = r.data.sessions;
    if (!list.length) return show(h('p', '', 'No agent sessions yet.'), link('Open Time Machine and try the demo', APP, true));
    const items = list.map(s => { const b = h('button', '', (s.parent ? '↳ ' : '') + s.title); b.onclick = () => detail(s.id); return b; });
    show(h('h4', '', 'Your agent sessions'), h('p', 'muted', 'Pick one to see its snapshots and what a rewind would do.'), h('div', 'list', ...items), link('Open full dashboard', APP));
  }

  async function detail(id) {
    show(h('p', 'muted', 'Loading…'));
    const r = await ask({ type: 'session', id });
    if (!r.ok) return show(h('p', '', r.error), (() => { const b = h('button', '', '← Back'); b.onclick = home; return b; })());
    const s = r.data, effects = Object.fromEntries(s.effects.map(e => [e.id, e]));
    const back = h('button', '', '← All sessions'); back.onclick = home;
    const items = [];
    for (const e of s.events) {
      const d = parse(e.detail);
      if (e.kind === 'checkpoint') items.push(h('li', 'snap', h('div', 'k', 'Snapshot'), d.label));
      else if (e.kind === 'external_action') {
        const st = (effects[d.id] || d).status;
        items.push(h('li', st === 'completed' ? 'done' : 'warn', h('div', 'k', (d.kind || 'action') + ' · ' + (st === 'completed' ? 'done, cannot be undone' : 'unconfirmed')), d.detail));
      }
    }
    const open = s.effects.filter(e => ['pending', 'unknown'].includes(e.status)).length;
    const first = s.checkpoints[0];
    show(h('h4', '', s.document.title), back,
      h('ol', '', ...items),
      open ? h('div', 'note', open + ' action(s) may or may not have happened. Rewinding stays blocked until you check them in the dashboard.') : null,
      h('p', 'muted', 'Rewinds are done in the dashboard, where you see exactly what comes back first.'),
      h('div', 'cta', link('Review a rewind →', APP + '#s=' + encodeURIComponent(id) + (first ? '&c=' + encodeURIComponent(first.id) : ''), true)));
  }

  const toggle = open => { panel.classList.toggle('open', open); tab.style.display = open ? 'none' : ''; if (open) home(); };
  tab.onclick = () => toggle(true);
  root.querySelector('.close').onclick = () => toggle(false);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && panel.classList.contains('open')) toggle(false); });
  document.documentElement.append(host);
})();
