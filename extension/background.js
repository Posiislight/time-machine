// Read-only bridge to the local Time Machine app. GET requests only, to one fixed origin.
const BASE = 'http://127.0.0.1:8765';
const ROUTES = {
  sessions: () => '/api/sessions',
  session: m => '/api/session?id=' + encodeURIComponent(m.id),
};
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (sender.id !== chrome.runtime.id || !msg || !ROUTES[msg.type]) return;
  fetch(BASE + ROUTES[msg.type](msg), { cache: 'no-store' })
    .then(r => r.json().then(body => ({ ok: r.ok, body })))
    .then(({ ok, body }) => reply(ok ? { ok: true, data: body } : { ok: false, error: body.error || 'Request failed' }))
    .catch(() => reply({ ok: false, offline: true, error: 'Time Machine is not running.' }));
  return true;
});
