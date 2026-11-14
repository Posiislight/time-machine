const el = document.getElementById('status');
chrome.runtime.sendMessage({ type: 'sessions' }, r => {
  el.textContent = r && r.ok ? 'Running. ' + r.data.sessions.length + ' session(s).' : 'Not running. Start it with “python server.py”.';
});
