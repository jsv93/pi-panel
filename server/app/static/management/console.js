'use strict';
const el = id => document.getElementById(id);
let session = '', panel = '', absoluteEnd = 0, idleEnd = 0, busy = false;
const message = text => { el('status').textContent = text; };
const render = value => { el('output').textContent = JSON.stringify(value, null, 2); };
function clearSession(text) {
  session = ''; panel = ''; el('key').value = '';
  el('session').hidden = true; el('login').hidden = false;
  el('output').textContent = 'Choose a check to begin.';
  message(text);
}
async function api(path, body, authenticated = true) {
  const response = await fetch(new URL('api/' + path, location.href), {
    method: 'POST', credentials: 'omit', cache: 'no-store', redirect: 'error',
    headers: {'Content-Type': 'application/json', ...(authenticated ? {Authorization: 'Bearer ' + session} : {})},
    body: JSON.stringify(body), signal: AbortSignal.timeout(15000)
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && authenticated) clearSession('Your session ended. Sign in again.');
    throw new Error(typeof data.detail === 'string' ? data.detail : 'The request could not be completed.');
  }
  return data;
}
async function action(task) {
  if (busy) return;
  busy = true; document.querySelectorAll('button').forEach(b => b.disabled = true);
  try { await task(); } catch (e) { message(e.message); }
  finally { busy = false; document.querySelectorAll('button').forEach(b => b.disabled = false); }
}
el('panel').value = new URL(location.href).searchParams.get('panel') || '';
if (location.protocol !== 'https:') {
  message('Open Panel Server using its configured HTTPS address to use secure diagnostics.');
  el('open').disabled = true;
}
el('login').addEventListener('submit', event => {
  event.preventDefault();
  if (location.protocol !== 'https:') return;
  action(async () => {
    message('Checking access…');
    let key = el('key').value; el('key').value = '';
    let data;
    try { data = await api('session', {user: el('user').value, key, panel: el('panel').value}, false); }
    finally { key = ''; }
    session = data.session; panel = data.panel;
    absoluteEnd = Date.now() + data.expires_in * 1000;
    idleEnd = Date.now() + data.idle_timeout * 1000;
    el('device').textContent = panel; el('login').hidden = true; el('session').hidden = false;
    message('Session open. Choose a diagnostic check.');
  }).then(() => { if (session) el('connection').focus(); });
});
for (const operation of ['connection', 'health']) {
  el(operation).addEventListener('click', () => action(async () => {
    message(operation === 'health' ? 'Waiting for the panel…' : 'Checking the connection…');
    idleEnd = Date.now() + 120000;
    const result = await api('panels/' + encodeURIComponent(panel) + '/diagnostic', {operation});
    if (!session) return;
    render(result); message('Check complete. No panel settings changed.');
  }));
}
el('close').addEventListener('click', () => action(async () => {
  await api('logout', {}); clearSession('Session ended.'); el('user').focus();
}));
setInterval(() => {
  if (!session) return;
  const remaining = Math.min(absoluteEnd, idleEnd) - Date.now();
  if (remaining <= 0) { clearSession('Session expired. Sign in to continue.'); return; }
  el('expiry').textContent = 'Session expires in ' + Math.ceil(remaining / 1000) + ' seconds unless extended by a check (10-minute maximum).';
}, 1000);
