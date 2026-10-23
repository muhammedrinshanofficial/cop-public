/* Step 14: the Assistant panel and the daily briefing card. Loaded after panels.js. */
(() => {
const {$, esc, ago, pill, S} = UI;

const style = document.createElement('style');
style.textContent = `
.btn.pri{background:var(--ac);border-color:var(--ac);color:#fff}.btn.pri:hover{background:#4a7ce0;border-color:#4a7ce0}
.btn:disabled{opacity:.55;cursor:default}
.chat{overflow:hidden}.chat .msgs{height:calc(100vh - 340px);min-height:340px;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:14px;scroll-behavior:smooth}
.msg{display:flex;flex-direction:column;max-width:80%;animation:in .25s both}.msg.user{align-self:flex-end;align-items:flex-end}
.bub{padding:10px 14px;border-radius:12px;background:var(--panel2);border:1px solid var(--line);line-height:1.6;word-break:break-word}
.msg.user .bub{background:var(--acs);border-color:rgba(91,141,239,.35)}.msg.error .bub{border-color:rgba(229,96,79,.45);color:#f3b6ad}
.bub p{margin:0 0 6px}.bub p:last-child{margin:0}.bub ul{margin:4px 0 4px 18px}.bub code{font:12px var(--mono);background:rgba(255,255,255,.07);padding:1px 5px;border-radius:4px}
.used{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--fa)}
.dots i{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--mu);margin:0 2px;animation:blink 1.2s infinite}.dots i:nth-child(2){animation-delay:.2s}.dots i:nth-child(3){animation-delay:.4s}
.welcome{margin:auto;text-align:center;max-width:580px}.welcome h2{font-size:18px;font-weight:600;margin-bottom:6px}.welcome p{color:var(--mu)}
.sugg{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:18px}
.composer{display:flex;gap:10px;padding:14px 18px;border-top:1px solid var(--line);align-items:flex-end}
.composer textarea{flex:1;resize:none;background:var(--bg);border:1px solid var(--line2);border-radius:8px;padding:8px 12px;color:var(--tx);font:inherit;max-height:120px;transition:border-color .15s,box-shadow .15s}
.composer textarea:focus{outline:0;border-color:var(--ac);box-shadow:0 0 0 3px var(--acs)}
.brief .head{font-size:15px;font-weight:500;margin-bottom:6px}.brief .sect{margin:14px 0 4px;color:var(--mu);font-size:12px;font-weight:600}
.hl{padding:9px 0;border-top:1px solid var(--line)}.hl b{display:block;font-weight:600}.hl span{color:var(--mu)}
.brief .act{margin:4px 0 0 18px}.brief .act li{margin:3px 0}
.bfoot{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-top:16px;padding-top:12px;border-top:1px solid var(--line);color:var(--fa);font-size:12px}
.facts{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
@keyframes blink{0%,80%,100%{opacity:.25}40%{opacity:1}}`;
document.head.appendChild(style);

// ---------------------------------------------------------------- daily briefing card on the Overview
const STATUS = {ok: ['All clear', 'ok'], attention: ['Needs attention', 'warn'], critical: ['Critical', 'err']};
const briefCard = b => {
  if (!b || b.available === false) {
    return `<div class="card brief"><div class="ch"><h3>Daily briefing</h3><span><button class="btn" id="brGen">Generate now</button></span></div>
      <div class="empty">${esc((b && b.message) || 'The briefing is not available right now.')}</div></div>`;
  }
  const [label, tone] = STATUS[b.status] || STATUS.ok, f = b.facts || {};
  const chip = (k, v) => v == null ? '' : `<span class="tag">${k}: ${esc(v)}</span>`;
  return `<div class="card brief"><div class="ch"><h3>Daily briefing</h3><span>${pill(label, tone)}</span></div><div class="cb">
    <p class="head">${esc(b.headline)}</p>
    ${(b.highlights || []).map(h => `<div class="hl"><b>${esc(h.title)}</b><span>${esc(h.detail)}</span></div>`).join('')}
    ${(b.actions || []).length ? `<div class="sect">Suggested next steps</div><ul class="act">${b.actions.map(a => `<li>${esc(a)}</li>`).join('')}</ul>` : ''}
    <div class="facts">${chip('Alerts fired, 24 h', f.alertsFiredLast24h)}${chip('Changes, 24 h', f.changesLast24h)}${chip('Failed deployments, 24 h', f.failedDeploymentsLast24h)}${chip('Critical security', f.securityCritical)}</div>
    <div class="bfoot"><span>Written by AI from your collected data ${ago(b.generatedAt)}. Check important facts in the panels.</span><button class="btn" id="brGen">Regenerate</button></div></div></div>`;
};
UI.briefing = b => { $('#view').insertAdjacentHTML('afterbegin', briefCard(b)); };

document.addEventListener('click', async e => {
  const btn = e.target.closest('#brGen'); if (!btn) return;
  btn.disabled = true; btn.textContent = 'Generating…';
  try { await UI.api('briefing/generate', {}); }
  catch (err) { $('#err').textContent = 'Could not generate the briefing: ' + err.message; $('#err').style.display = 'block'; }
  if (S.page === 'overview') UI.show('overview', true);
});

// ---------------------------------------------------------------- assistant panel
const SUGGEST = ['What changed in the last 24 hours?', 'Which VM is over-provisioned and how much could I save?', 'Is anything exposed to the internet?', 'Why did my last deployment fail?', 'How is the cost against the budget?'];
const TOOL = {get_inventory: 'Inventory', get_cost_summary: 'Cost', get_resource_metrics: 'VM metrics', get_recent_changes: 'Changes', get_alerts: 'Alerts',
  get_deployments: 'Deployments', get_security_findings: 'Security', get_vm_utilization_vs_cost: 'Right-sizing'};
let msgs = [], convId = '', pending = false;
try { msgs = JSON.parse(sessionStorage.getItem('copChat') || '[]'); convId = sessionStorage.getItem('copConv') || ''; } catch (e) { msgs = []; }
const persist = () => { try { sessionStorage.setItem('copChat', JSON.stringify(msgs.slice(-40))); sessionStorage.setItem('copConv', convId); } catch (e) {} };

const inline = s => s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`(.+?)`/g, '<code>$1</code>');
const format = text => {   // escape first, then allow only bold, code, paragraphs and lists
  let html = '', list = false;
  for (const line of esc(text).split('\n')) {
    const m = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (m) { if (!list) { html += '<ul>'; list = true; } html += `<li>${inline(m[1])}</li>`; }
    else { if (list) { html += '</ul>'; list = false; } if (line.trim()) html += `<p>${inline(line)}</p>`; }
  }
  return html + (list ? '</ul>' : '');
};
const bubble = m => `<div class="msg ${m.role}${m.error ? ' error' : ''}"><div class="bub">${m.role === 'user' ? esc(m.text) : format(m.text)}</div>${
  m.tools && m.tools.length ? `<div class="used">Data used: ${m.tools.map(t => `<span class="tag">${TOOL[t] || esc(t)}</span>`).join('')}</div>` : ''}</div>`;
const WELCOME = `<div class="welcome"><h2>Ask about your Azure environment</h2><p>I can look at cost, changes, alerts, deployments, security, VM performance and right-sizing. I only read data and never change anything.</p>
  <div class="sugg">${SUGGEST.map(q => `<button class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join('')}</div></div>`;

function draw() {
  const box = $('#msgs'); if (!box) return;
  box.innerHTML = msgs.length ? msgs.map(bubble).join('') + (pending ? '<div class="msg"><div class="bub dots"><i></i><i></i><i></i></div></div>' : '') : WELCOME;
  box.scrollTop = box.scrollHeight;
  $('#send').disabled = pending; $('#chIn').disabled = pending;
}
async function send(question) {
  question = (question || '').trim(); if (!question || pending) return;
  msgs.push({role: 'user', text: question}); pending = true; $('#chIn').value = ''; draw();
  try {
    const r = await UI.api('assistant/chat', {question, conversationId: convId});
    convId = r.conversationId; msgs.push({role: 'assistant', text: r.answer, tools: r.toolsUsed});
  } catch (e) { msgs.push({role: 'assistant', text: 'Sorry, I could not answer: ' + e.message, error: true}); }
  pending = false; persist(); draw(); const input = $('#chIn'); if (input) input.focus();
}

UI.register({assistant: {title: 'Assistant', sub: 'Ask questions about your Azure environment in plain language. Read-only.', async load() {
  if (!$('#msgs')) {
    $('#view').innerHTML = `<div class="card chat"><div class="ch"><h3>Chat</h3><span><button class="btn" id="chNew">New chat</button></span></div>
      <div class="msgs" id="msgs"></div>
      <div class="composer"><textarea id="chIn" rows="1" maxlength="600" placeholder="Ask about cost, changes, alerts, security, VMs…"></textarea><button class="btn pri" id="send">Send</button></div></div>
      <p class="note">Answers are written by AI from the data your collectors saved. They can be wrong, so check important facts in the other panels.</p>`;
    draw();
  }
  UI.stamp(null);
}}});

document.addEventListener('click', e => {
  const q = e.target.closest('[data-q]'); if (q) { send(q.dataset.q); return; }
  if (e.target.closest('#send')) { send($('#chIn').value); return; }
  if (e.target.closest('#chNew')) { msgs = []; convId = ''; pending = false; persist(); draw(); }
});
document.addEventListener('keydown', e => {
  if (e.target.id === 'chIn' && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(e.target.value); }
});
document.addEventListener('input', e => { if (e.target.id === 'chIn') { e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'; } });
})();