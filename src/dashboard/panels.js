/* Operations, Performance, Right-sizing and Security panels. Registers itself with the main page through UI.register. */
(() => {
const {$, esc, tidy, S, money, ago, when, tone, pill, icon, kpi, meter, card, empty, table, ring, events, api, show} = UI;
const PROJECT_TAG = 'azure-cloud-operations-center';
// "This project" = anything tagged for the project, or whose name or resource group contains the word cop
const isMine = o => (o.tags || {}).project === PROJECT_TAG ||
  /(^|[\s\-_\/])cop([\s\-_]|$)/i.test([o.resourceGroup, o.name, o.resourceName, o.alertRule, o.title].filter(Boolean).join(' '));
const inScope = o => S.scope === 'all' || isMine(o);
const sevOf = s => ({Sev0: 'critical', Sev1: 'critical', Sev2: 'warning'})[s] || 'info';
const sevLabel = s => ({critical: 'Critical', warning: 'Warning', info: 'Info'})[sevOf(s)];
const shortType = t => String(t || '').split('/').pop();
const scopeSeg = () => `<div class="seg">${[['project', 'This project'], ['all', 'Whole subscription']].map(([v, l]) =>
  `<button class="${S.scope === v ? 'on' : ''}" data-set="scope=${v}">${l}</button>`).join('')}</div>`;
const busyTyping = () => /INPUT|SELECT/.test(document.activeElement.tagName);
const SCAN = {alerts: 'alerts', deployments: 'activity', inventory: 'inventory'};
const scanBtn = name => `<button class="btn" data-scan="${name}">Scan now</button>`;
const kvs = rows => `<div class="kvs">${rows.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('')}</div>`;

// ---------------------------------------------------------------- Operations
const operations = {
  title: 'Operations', sub: 'Alerts, deployments and the resource inventory', q: {tab: 'alerts', rg: '', search: ''}, data: null, dataTab: '',
  async load() {
    const q = this.q;
    if (this.data && this.dataTab === q.tab && busyTyping()) return;   // the auto-refresh must not disturb typing
    const d = q.tab === 'alerts' ? await api('alerts?days=30')
      : q.tab === 'deployments' ? await api('timeline?days=30&type=deployment&limit=300') : await api('inventory');
    this.data = d; this.dataTab = q.tab; this.draw(); UI.stamp(d.timestamp || (d.events && d.events[0] && d.events[0].timestamp));
  },
  draw() { this.shell(); this.results(); },
  shell() {
    const q = this.q, d = this.data || {}, groups = q.tab === 'inventory' ? Object.keys(d.byResourceGroup || {}).sort() : [];
    $('#view').innerHTML = `<div class="tabs">${[['alerts', 'Alerts'], ['deployments', 'Deployments'], ['inventory', 'Inventory']].map(([v, l]) =>
        `<button class="tab ${q.tab === v ? 'on' : ''}" data-set="tab=${v}">${l}</button>`).join('')}</div>
      <div class="row2"><div class="fl">${q.tab !== 'alerts' ? `<div class="srch">${icon('search')}<input class="inp" id="oSearch" placeholder="${q.tab === 'inventory' ? 'Search resources or types' : 'Search deployments'}" value="${esc(q.search)}"></div>` : ''}
        ${q.tab === 'inventory' ? `<select class="inp" id="oRg"><option value="">All resource groups</option>${groups.map(g => `<option ${g === q.rg ? 'selected' : ''}>${esc(g)}</option>`).join('')}</select>` : ''}
        <span class="cnt" id="oCount"></span></div><div class="fl">${scanBtn(SCAN[q.tab])}${scopeSeg()}</div></div><div id="res"></div>`;
  },
  results() {
    const q = this.q, d = this.data, res = $('#res'), needle = q.search.toLowerCase();
    if (d.available === false) { res.innerHTML = empty(d.message); return; }

    if (q.tab === 'alerts') {
      const items = d.alerts.filter(inScope), isEvent = a => ['Log', 'Activity Log'].includes(a.signalType), groups = {},
        fired = items.filter(a => a.monitorCondition === 'Fired' && !isEvent(a)),
        events = items.filter(a => a.monitorCondition === 'Fired' && isEvent(a));
      fired.forEach(a => { const k = tidy(a.alertRule), g = groups[k] = groups[k] || {rule: k, n: 0, last: '', signal: a.signalType, severity: a.severity};
        g.n++; if (a.startTime > g.last) g.last = a.startTime; });
      const attention = Object.values(groups).sort((x, y) => y.last.localeCompare(x.last));
      const sevs = fired.map(a => sevOf(a.severity)), worst = sevs.includes('critical') ? 'critical' : sevs.includes('warning') ? 'warning' : fired.length ? 'info' : '';
      $('#oCount').textContent = `${items.length} alerts · last ${d.days} days`;
      res.innerHTML = `<div class="kpis">
        ${kpi('Still firing', fired.length, `${attention.length} distinct rule${attention.length === 1 ? '' : 's'}`, fired.length ? 'warn' : 'ok')}
        ${kpi('Resolved', items.filter(a => a.monitorCondition === 'Resolved').length, 'closed automatically')}
        ${kpi('One-time events', events.length, 'Activity Log, no resolve step')}
        ${kpi('Total', items.length, scope(d))}
        ${kpi('Worst active', worst ? worst[0].toUpperCase() + worst.slice(1) : 'None', 'by severity', worst === 'critical' ? 'err' : worst === 'warning' ? 'warn' : 'ok')}</div>
      ${card('Needs attention', table(['Severity', 'Alert rule', 'Signal', 'Times fired', 'Last fired'], attention.map(g => [
        pill(sevLabel(g.severity), tone(sevOf(g.severity))), `<span class="m">${esc(g.rule)}</span>`, `<span class="tag">${esc(g.signal || 'alert')}</span>`, g.n, `<span class="nw">${ago(g.last)}</span>`]), [3]))}
      ${events.length ? '<p class="note">Activity Log alerts, such as failed deployments, are one-time events with no resolve step. They show as "Event" in the history and are not counted as still firing.</p>' : ''}
      ${card('Alert history', table(['Status', 'Severity', 'Alert rule', 'Resource', 'Signal', 'Started'], items.slice(0, 60).map(a => [
        isEvent(a) && a.monitorCondition === 'Fired' ? pill('Event', 'info') : pill(a.monitorCondition), pill(sevLabel(a.severity), tone(sevOf(a.severity))), `<span class="m">${esc(tidy(a.alertRule))}</span>`,
        `<span class="mono">${esc(a.resourceName || 'subscription')}</span>`, `<span class="tag">${esc(a.signalType || '')}</span>`, `<span class="nw">${when(a.startTime)}</span>`])), items.length > 60 ? 'showing newest 60' : '')}`;
      return;
    }

    if (q.tab === 'deployments') {
      const items = d.events.filter(inScope).filter(e => !needle || `${e.title} ${e.resourceName}`.toLowerCase().includes(needle)), failed = items.filter(e => e.severity === 'error');
      $('#oCount').textContent = `${items.length} deployments · last 30 days`;
      res.innerHTML = `<div class="kpis">
        ${kpi('Deployments', items.length, 'last 30 days')}${kpi('Succeeded', items.length - failed.length, 'completed', 'ok')}
        ${kpi('Failed', failed.length, failed.length ? `latest ${ago(failed[0].timestamp)}` : 'none', failed.length ? 'err' : 'ok')}</div>
      ${card('Deployment history', table(['Status', 'Deployment', 'Resource group', 'When'], items.slice(0, 80).map(e => {
        const bad = e.severity === 'error', err = bad && (e.details || {}).error;
        return [pill(bad ? 'Failed' : 'Succeeded'), `<span class="m">${esc(tidy(e.title).replace(/^Deployment (failed|succeeded): /, ''))}</span>${err ? `<span class="errtx">${esc(err)}</span>` : ''}`,
          `<span class="mono">${esc(e.resourceGroup || 'subscription')}</span>`, `<span class="nw">${when(e.timestamp)}</span>`]; })))}`;
      return;
    }

    const items = d.resources.filter(inScope).filter(r => !q.rg || r.resourceGroup === q.rg).filter(r => !needle || `${r.name} ${r.type}`.toLowerCase().includes(needle))
      .sort((a, b) => (a.resourceGroup + a.name).localeCompare(b.resourceGroup + b.name));
    $('#oCount').textContent = `${items.length} resources`;
    res.innerHTML = `<div class="kpis">${kpi('Resources shown', items.length, scope(d))}${kpi('Resource types', new Set(items.map(r => r.type)).size, 'distinct')}${kpi('Resource groups', new Set(items.map(r => r.resourceGroup)).size, 'in view')}</div>
      ${card('Inventory', table(['Name', 'Type', 'Resource group', 'Location', 'SKU'], items.slice(0, 200).map(r => [
        `<span class="m">${esc(r.name)}</span>`, `<span class="mono">${esc(shortType(r.type))}</span>`, `<span class="mono">${esc(r.resourceGroup)}</span>`, esc(r.location || '—'), r.skuName ? `<span class="tag">${esc(r.skuName)}</span>` : '<span class="mono">—</span>'])), items.length > 200 ? 'showing the first 200' : '')}`;
  }
};
const scope = () => S.scope === 'all' ? 'whole subscription' : 'this project';

const quotaCard = q => {
  if (!q) return '';
  if (q.available === false) return card('Quota and usage', '<div class="empty">No quota data yet. Press Scan now.</div>', scanBtn('quota'));
  return card('Quota and usage', table(['Limit', 'Used', 'Allowed', 'Usage'], (q.items || []).map(i => [
    `<span class="m">${esc(i.label)}</span>`, i.used, i.limit,
    `<div class="share">${meter(i.pct, i.pct >= 100 ? 'err' : i.pct >= 80 ? 'warn' : '')}<span class="m">${i.pct}%</span></div>`]), [1, 2]),
    `${esc(q.region)} · whole subscription · ${ago(q.timestamp)} ${scanBtn('quota')}`) +
    '<p class="note">Free-trial subscriptions cannot raise these limits. A new VM that does not fit fails with a quota error.</p>';
};

// ---------------------------------------------------------------- Performance
const performance = {
  title: 'Performance', sub: 'CPU and memory of every virtual machine over the last 7 days',
  async load() {
    const [m, u, qd] = await Promise.all([api('metrics'), api('utilization'), api('quota').catch(() => null)]);
    if (!m.available) { $('#view').innerHTML = empty(m.message); return; }
    const info = {}; ((u.utilization || {}).vms || []).forEach(v => { info[v.resourceId] = v; });
    const vms = m.vms || [], top = Math.max(0, ...vms.map(v => (v.cpuPct || {}).p95 || 0));
    $('#view').innerHTML = `<div class="kpis">${kpi('VMs monitored', vms.length, 'CPU and memory')}${kpi('History window', m.windowDays + ' days', 'p95 shows the busy peaks, not the average')}${kpi('Busiest CPU (p95)', top.toFixed(1) + '%', 'across all VMs')}</div>
    <div class="vms">${vms.length ? vms.map(v => {
      const x = info[v.resourceId] || {}, cpu = v.cpuPct, mem = v.memory, total = x.memoryMB, pct = mb => total ? mb / total * 100 : null;
      const p95 = mem ? (total ? pct(mem.p95UsedMB) : mem.p95UsedPct) : null, avg = mem ? (total ? pct(mem.avgUsedMB) : mem.avgUsedPct) : null;
      return `<div class="card"><div class="vh"><div><b>${esc(v.name)}</b><span class="s">${x.vmSize ? `${esc(x.vmSize)} · ${x.vcpus} vCPU · ${(total / 1024).toFixed(0)} GB RAM` : esc(v.resourceGroup)}</span></div>${x.status ? pill(x.status) : ''}</div>
        ${cpu || mem ? `<div class="vb"><div class="rings">${ring(cpu ? cpu.p95 : null, 'CPU p95')}${ring(p95, 'Memory p95')}</div>
          ${kvs([['CPU average', cpu ? cpu.avg + '%' : '—'], ['CPU peak', cpu ? cpu.max + '%' : '—'], ['Memory average', avg != null ? avg.toFixed(0) + '%' : '—'], ['Memory peak', mem ? mem.maxUsedMB.toFixed(0) + ' MB' : '—'], ['Samples', `${cpu ? cpu.samples : 0} CPU · ${mem ? mem.samples : 0} mem`]])}</div>`
        : '<div class="empty">No samples in this window. Start the VM and give it a few hours.</div>'}</div>`;
    }).join('') : empty('No virtual machines found. Run /api/collect/inventory first.')}</div>
    <p class="note">B-series CPU is measured against the full core, not the burst baseline. Memory is read from inside the VM by the Azure Monitor Agent.</p>`;
    $('#view').insertAdjacentHTML('beforeend', quotaCard(qd)); UI.stamp(m.timestamp);
  }
};

// ---------------------------------------------------------------- Security
const CHECKS = [
  ['open-nsg-rule', 'Internet-open firewall rules', 'Inbound Allow rules open to the whole internet. SSH and RDP count as critical.'],
  ['public-ip', 'Public IP addresses', 'Every public IP is a way in from the internet.'],
  ['missing-tags', 'Required tags', 'project, environment, owner and managedBy on every resource of this project.']
];
const security = {
  title: 'Security', sub: 'Exposure checks that run every 5 minutes, or on demand with Scan now', data: null, events: null,
  async load() {
    if (this.data && busyTyping()) return;
    const [s, ev] = await Promise.all([api('security'), api('timeline?days=30&type=security&limit=100')]);
    this.data = s; this.events = ev; this.draw(); UI.stamp(s.timestamp);
  },
  draw() {
    const s = this.data; if (s.available === false) { $('#view').innerHTML = empty(s.message); return; }
    const f = s.findings.filter(inScope), by = k => f.filter(x => x.severity === k).length, crit = by('critical'), warn = by('warning'), order = {critical: 0, warning: 1, info: 2};
    const bad = crit + warn;
    $('#view').innerHTML = `<div class="row2"><span class="cnt">Last scan ${ago(s.timestamp)}</span><div class="fl">${scanBtn('security')}${scopeSeg()}</div></div>
    <div class="banner ${bad ? 'err' : 'ok'}">${icon(bad ? 'alert' : 'security')}<div><b>${bad ? `${bad} issue${bad === 1 ? ' needs' : 's need'} attention` : 'No exposed firewall rules or risky ports found'}</b>
      <span class="ks">${bad ? 'Review the findings below and close the exposed ports.' : 'All security checks are passing.'}</span></div></div>
    <div class="kpis">${kpi('Critical', crit, 'SSH, RDP or all ports open', crit ? 'err' : '')}${kpi('Warning', warn, 'other ports open to the internet', warn ? 'warn' : '')}${kpi('Info', by('info'), 'public IPs and tag gaps')}${kpi('Total findings', f.length, scope())}</div>
    ${card('Checks performed', table(['Check', 'What it looks for', 'Result'], CHECKS.map(([type, name, what]) => { const hits = f.filter(x => x.type === type);
      return [`<span class="m">${name}</span>`, `<span class="s" style="max-width:520px">${what}</span>`, hits.length ? pill(hits.length + ' found', hits.some(x => x.severity === 'critical') ? 'err' : 'warn') : pill('Pass', 'ok')]; })))}
    ${card('Findings', !f.length ? '<div class="empty">No findings in this scope. Nothing is exposed.</div>' : table(['Severity', 'Resource', 'Type', 'Why'], f.slice().sort((a, b) => order[a.severity] - order[b.severity]).map(x => [
      pill(x.severity[0].toUpperCase() + x.severity.slice(1), tone(x.severity)), `<span class="m">${esc(x.name)}</span><span class="s">${esc(x.resourceGroup)}</span>`, `<span class="tag">${esc(x.type)}</span>`, esc(x.reason)])))}
    ${card('History', events(this.events.events.filter(inScope).slice(0, 15)), 'last 30 days')}
    <p class="note">Firewall and public IP scans cover the whole subscription. The tag check covers only this project's resource groups.</p>`;
  }
};

// ---------------------------------------------------------------- Right-sizing and waste
const WASTE = {'idle-vm': 'Idle VM', 'stopped-vm': 'Stopped VM, still billed', 'unused-storage': 'Unused storage', 'unattached-disk': 'Unattached disk',
  'unattached-nic': 'Unattached NIC', 'unattached-public-ip': 'Unattached public IP'};
const rightsizing = {
  title: 'Right-sizing', sub: 'VMs that cost more than they use, and resources that waste money', data: null,
  async load() {
    if (this.data && busyTyping()) return;
    const d = await api('utilization'); if (!d.available) { $('#view').innerHTML = empty(d.message); return; }
    this.data = d; this.draw(); UI.stamp((d.utilization || {}).timestamp);
  },
  draw() {
    const d = this.data, u = d.utilization || {}, w = d.waste || {}; S.cur = u.currency || w.currency || S.cur;
    const vms = (u.vms || []).filter(inScope), finds = (w.findings || []).filter(inScope), count = s => vms.filter(v => v.status === s).length;
    const saving = vms.filter(v => v.status === 'over-provisioned').reduce((a, v) => a + ((v.recommendation || {}).estimatedMonthlySaving || 0), 0);
    const wasteCost = finds.reduce((a, f) => a + (f.billedCost30d || 0), 0);
    $('#view').innerHTML = `<div class="row2"><span class="cnt">Recommendations only. Nothing is ever changed automatically.</span>${scopeSeg()}</div>
    <div class="kpis">${kpi('Potential saving', money(saving, S.cur), 'per month at list price', saving ? 'ok' : '')}${kpi('Over-provisioned', count('over-provisioned'), `of ${vms.length} VM${vms.length === 1 ? '' : 's'}`, count('over-provisioned') ? 'warn' : '')}
      ${kpi('Running hot', count('high-utilization'), 'p95 at or above 85%', count('high-utilization') ? 'err' : '')}${kpi('Waste items', finds.length, `${money(wasteCost, S.cur, 2)} billed in 30 days`)}</div>
    <div class="vms">${vms.length ? vms.map(v => { const cpu = v.cpuPct, mem = v.memoryUsedPct, rec = v.recommendation;
      return `<div class="card"><div class="vh"><div><b>${esc(v.name)}</b><span class="s">${esc(v.vmSize)} · ${v.vcpus ?? '?'} vCPU · ${v.memoryMB ? (v.memoryMB / 1024).toFixed(0) : '?'} GB RAM</span></div>${pill(v.status)}</div>
        <div class="vb"><div class="rings">${ring(cpu ? cpu.p95 : null, 'CPU p95')}${ring(mem ? mem.p95 : null, 'Memory p95')}</div>
          ${kvs([['List price / month', money(v.monthlyListPrice, S.cur)], ['Billed, last 30 days', money(v.billedCost30d, S.cur, 2)], ...((v.reasons || []).length ? [['Why flagged', v.reasons.map(esc).join('<br>')]] : [])])}</div>
        ${rec ? `<div class="rec"><b>${esc(v.vmSize)} → ${esc(rec.size)}</b><div style="color:var(--mu);margin:2px 0">${rec.vcpus} vCPU · ${(rec.memoryMB / 1024).toFixed(1)} GB · ${money(rec.monthlyListPrice, S.cur)} per month</div><span class="good">Saves about ${money(rec.estimatedMonthlySaving, S.cur)} per month</span></div>`
          : (v.recommendationNote ? `<div class="s" style="padding:0 18px 16px">${esc(v.recommendationNote)}</div>` : '')}</div>`; }).join('') : empty('No virtual machines in this scope.')}</div>
    <p class="note">Savings use full-time list prices. These VMs shut down every night, so real savings are smaller. Azure can still refuse a recommended size for capacity or quota reasons.</p>
    ${card('Waste detection', table(['Kind', 'Resource', 'Why', 'Billed · 30 days'], finds.map(f => [`<span class="tag">${esc(WASTE[f.type] || f.type)}</span>`,
      `<span class="m">${esc(f.name)}</span><span class="s">${esc(f.resourceGroup)}</span>`, esc(f.reason), `<span class="m">${money(f.billedCost30d, S.cur, 2)}</span>`]), [3]))}`;
  }
};

UI.register({operations, performance, rightsizing, security});

// ---------------------------------------------------------------- interactions
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-scan]'); if (!b || b.disabled) return;
  b.disabled = true; b.textContent = 'Scanning…';
  let failed = '';
  try { await api('scan/' + b.dataset.scan, {}); } catch (err) { failed = err.message; }
  await show(S.page, true);
  if (failed) { $('#err').textContent = 'Scan failed: ' + failed; $('#err').style.display = 'block'; }
});
document.addEventListener('click', e => {
  const b = e.target.closest('[data-set]'); if (!b) return;
  const [k, v] = b.dataset.set.split('='), p = {operations, performance, rightsizing, security}[S.page];
  if (!p) return;
  if (k === 'scope') { S.scope = v; p.draw(); return; }
  if (k === 'tab') { p.q.tab = v; p.q.rg = ''; p.q.search = ''; show(S.page, true); }
});
document.addEventListener('change', e => { if (e.target.id === 'oRg') { operations.q.rg = e.target.value; operations.draw(); } });
let typing;
document.addEventListener('input', e => {
  if (e.target.id !== 'oSearch') return;
  clearTimeout(typing); typing = setTimeout(() => { operations.q.search = e.target.value.trim(); operations.results(); }, 200);
});
})();