#!/usr/bin/env node
/**
 * bartolo-battery.mjs — Bateria de muntatges via Playwright contra el dashboard Bartolo :9999.
 *
 * Valida TOTES les funcions del dashboard: xat, WebSockets, repair events Deepseek,
 * status, databases, timeline, logs, botons stop/restart/logs/timeline.
 * Força un repair_event per validar el flux DeepSeek dins el xat.
 *
 * NO substitueix bartolo-goal.mjs. Crea el seu propi directori runs/<timestamp>/.
 *
 * Usage: node bartolo-battery.mjs
 */

import { chromium } from 'playwright';
import { readFileSync, writeFileSync, mkdirSync, existsSync, appendFileSync } from 'fs';
import { resolve, basename } from 'path';
import { execSync } from 'child_process';
import { homedir } from 'os';

// ===== CONFIGURACIÓ =====
const DASHBOARD_URL = 'http://localhost:9999';
const WS_CHAT_URL = 'ws://localhost:9999/ws/chat';
const SECRETS_CACHE = resolve(homedir(), '.universal-agent/secrets.json');
const WORKSPACE = resolve(homedir(), 'universal-agent-workspace');
const PROJECTS_DIR = resolve(homedir(), 'Projects');
const RUNS_DIR = resolve(import.meta.dirname, 'runs');
const MAX_INTENTS_PER_REPO = 10;
const REQUIRED_CONSECUTIVE = 2;
const POLL_INTERVAL_MS = 5000;
const SCREENSHOT_INTERVAL_MS = 30000;
const MAX_DURATION_MS = 8 * 60 * 60 * 1000;
const QUIESCENCE_MS = 30000;
const INTENT_TIMEOUT_MS = 25 * 60 * 1000; // 25 minuts màx per intent

// ===== REPOS DE LA BATERIA =====
const BATTERY_REPOS = [
  {
    name: 'wa-desk',
    path: resolve(PROJECTS_DIR, 'wa-desk'),
    envLocal: resolve(PROJECTS_DIR, 'wa-desk', '.env.local'),
    needsSecrets: true,
    needsSabotage: true,
    description: 'EMERGENT stack (FastAPI + React + Supabase + Redis + BullMQ)',
  },
  {
    name: 'wavebox-mail',
    path: resolve(PROJECTS_DIR, 'wavebox-mail'),
    envLocal: null,
    needsSecrets: false,
    needsSabotage: false,
    description: 'Docker Compose + EMERGENT stack (Node backend + Vite frontend)',
  },
];

// ===== SANITITZACIÓ =====
function sanitize(text) {
  let redactions = 0;
  let out = text;
  // JWTs (eyJ...)
  out = out.replace(/eyJ[A-Za-z0-9\-_]{20,}={0,2}/g, () => { redactions++; return '<REDACTED>'; });
  // Supabase keys (sb_secret_..., sb_publishable_...)
  out = out.replace(/\b(sb_secret_|sb_publishable_)[A-Za-z0-9\-_]{10,}/g, () => { redactions++; return '<REDACTED>'; });
  // DeepSeek/OpenAI keys (sk-...)
  out = out.replace(/\bsk-[A-Za-z0-9]{20,}\b/g, () => { redactions++; return '<REDACTED>'; });
  // High-entropy strings (>40 chars, no spaces, not URL, not git hash)
  out = out.replace(/\b[A-Za-z0-9\-_+/=]{40,}\b/g, (m) => {
    if (m.startsWith('http') || m.startsWith('www.') || m.startsWith('/')) return m;
    redactions++;
    return '<REDACTED>';
  });
  return { text: out, redactions };
}

// ===== HELPERS =====
function ts() {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}_${String(d.getHours()).padStart(2,'0')}${String(d.getMinutes()).padStart(2,'0')}${String(d.getSeconds()).padStart(2,'0')}`;
}

function nowISO() { return new Date().toISOString(); }

async function apiFetch(url, opts = {}) {
  const base = DASHBOARD_URL;
  const fullUrl = url.startsWith('http') ? url : base + url;
  try {
    const res = await fetch(fullUrl, { signal: AbortSignal.timeout(30000), ...opts });
    const text = await res.text();
    try { return JSON.parse(text); }
    catch { return { _raw: text, _status: res.status }; }
  } catch (e) {
    return { _error: e.message };
  }
}

function ensureDir(dir) {
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
}

function wsEventLine(type, data) {
  return JSON.stringify({ arrived: nowISO(), type, ...data }) + '\n';
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ===== VERIFICACIÓ DE PREREQUISITS =====
function checkPrerequisites() {
  console.log('[battery] Verificant prerequisits...');
  const errors = [];

  for (const repo of BATTERY_REPOS) {
    if (repo.envLocal && !existsSync(repo.envLocal)) {
      errors.push(`${repo.name}: .env.local no trobat a ${repo.envLocal}`);
    }
  }

  try {
    const secrets = JSON.parse(readFileSync(SECRETS_CACHE, 'utf-8'));
    const hasDeepseek = Object.keys(secrets).some(k => k.toUpperCase().includes('DEEPSEEK'));
    if (!hasDeepseek) errors.push('Clau DeepSeek no configurada a ~/.universal-agent/secrets.json');
  } catch {
    errors.push('No es pot llegir ~/.universal-agent/secrets.json');
  }

  try {
    const r = execSync('curl -s -o /dev/null -w "%{http_code}" http://localhost:9999/api/status', { timeout: 5000 });
    if (r.toString().trim() !== '200') errors.push('Dashboard no respon 200 a /api/status');
  } catch {
    errors.push('Dashboard no respon a http://localhost:9999');
  }

  if (errors.length > 0) {
    console.error('\n❌ PREREQUISITS FALLATS:');
    for (const e of errors) console.error(`   - ${e}`);
    process.exit(1);
  }
  console.log('[battery] ✅ Tots els prerequisits OK\n');
}

// ===== WEBSOCKET =====
function connectWebSocket(url, onMessage, onError) {
  return new Promise((resolve, reject) => {
    const WebSocket = globalThis.WebSocket;
    const ws = new WebSocket(url);
    ws.onopen = () => resolve(ws);
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        onMessage(data);
      } catch { /* ignore non-JSON frames */ }
    };
    ws.onerror = (err) => {
      if (onError) onError(err);
      reject(err);
    };
  });
}

// ===== PRE-UNMOUNT =====
async function preUnmount(repoName, intentDir) {
  console.log(`  [pre-unmount] Netejant ${repoName}...`);

  // API stop
  try {
    const stopRes = await apiFetch('/api/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `repo=${encodeURIComponent(repoName)}`,
    });
    writeFileSync(resolve(intentDir, 'pre-stop.json'), JSON.stringify(stopRes, null, 2));
  } catch (e) {
    console.log(`  [pre-unmount] ⚠️  Stop API: ${e.message}`);
  }

  // Docker cleanup: eliminar containers i volums relacionats amb aquest repo
  try {
    const containers = execSync(
      `docker ps -a --filter name=agent- --format '{{.Names}}' 2>/dev/null || true`,
      { encoding: 'utf-8' }
    ).trim();
    for (const c of containers.split('\n').filter(Boolean)) {
      try {
        execSync(`docker stop ${c} 2>/dev/null; docker rm ${c} 2>/dev/null; docker volume rm ${c}-data 2>/dev/null || true`);
        console.log(`  [pre-unmount] 🗑️  Container: ${c}`);
      } catch {}
    }
  } catch {}

  // Neteja de node_modules, dist, .venv al repo
  const repo = BATTERY_REPOS.find(r => r.name === repoName);
  if (repo) {
    try {
      execSync(`rm -rf "${repo.path}/node_modules" "${repo.path}/dist" "${repo.path}/.venv" "${repo.path}/frontend/node_modules" "${repo.path}/backend/.venv" 2>/dev/null || true`);
    } catch {}
  }

  await sleep(3000);

  // Verificar neteja
  const status = await apiFetch('/api/status');
  writeFileSync(resolve(intentDir, 'pre-status.json'), JSON.stringify(status, null, 2));
  const dbRes = await apiFetch('/api/databases');
  writeFileSync(resolve(intentDir, 'pre-databases.json'), JSON.stringify(dbRes, null, 2));

  console.log(`  [pre-unmount] ✅ Net`);
}

// ===== SABOTAGE =====
async function applySabotage(repoName) {
  const repo = BATTERY_REPOS.find(r => r.name === repoName);
  if (!repo) return null;
  console.log(`  [sabotage] Aplicant sabotatge a ${repoName}...`);
  const sabotage = { repo: repoName, actions: [] };

  // Renombrar package.json del frontend temporalment
  const pkgPath = resolve(repo.path, 'frontend', 'package.json');
  const bakPath = pkgPath + '.battery-bak';
  if (existsSync(pkgPath)) {
    execSync(`cp "${pkgPath}" "${bakPath}"`);
    execSync(`rm "${pkgPath}"`);
    sabotage.actions.push(`renamed ${pkgPath} → .battery-bak`);
    console.log(`  [sabotage] ✅ package.json → .battery-bak`);
  }
  return sabotage;
}

async function revertSabotage(repoName, sabotage) {
  if (!sabotage) return;
  console.log(`  [sabotage] Revertint...`);
  const repo = BATTERY_REPOS.find(r => r.name === repoName);
  if (!repo) return;
  const pkgPath = resolve(repo.path, 'frontend', 'package.json');
  const bakPath = pkgPath + '.battery-bak';
  if (existsSync(bakPath)) {
    execSync(`cp "${bakPath}" "${pkgPath}" && rm "${bakPath}"`);
    console.log(`  [sabotage] ✅ restaurat`);
  }
}

// ===== LLANÇAMENT =====
async function launchRepo(repoPath, intentDir) {
  console.log(`  [launch] ${repoPath}`);
  const body = `input=${encodeURIComponent(repoPath)}&approve_all=on`;
  const res = await apiFetch('/api/launch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  writeFileSync(resolve(intentDir, 'launch-response.json'), JSON.stringify(res, null, 2));
  return res;
}

// ===== TRACKER D'EVENTS DEL WEBSOCKET DE XAT =====
class ChatEventTracker {
  constructor() {
    this.events = [];
    this.tokens = 0;
    this.actions = [];
    this.agentOutputs = [];
    this.repairEvents = [];
    this.errors = [];
    this.history = [];        // events type=history
    this.intents = [];        // events type=intent
    this.done = false;
    this.doneData = null;
    this.fullText = '';
    this.wizardDone = false;
    this.wizardSteps = [];
    this.threadCreated = false;
  }

  process(data) {
    const entry = { ts: nowISO(), ...data };
    this.events.push(entry);
    const type = data.type;
    if (type === 'token') {
      this.tokens++;
      this.fullText += (data.text || data.token || '');
    } else if (type === 'action') {
      this.actions.push(entry);
    } else if (type === 'agent_output') {
      this.agentOutputs.push(entry);
    } else if (type === 'repair_event') {
      this.repairEvents.push(entry);
    } else if (type === 'error') {
      this.errors.push(entry);
    } else if (type === 'done') {
      this.done = true;
      this.doneData = entry;
    } else if (type === 'wizard_done') {
      this.wizardDone = true;
    } else if (type === 'wizard_step') {
      this.wizardSteps.push(entry);
    } else if (type === 'history') {
      this.history.push(entry);
    } else if (type === 'intent') {
      this.intents.push(entry);
    } else if (type === 'thread_created') {
      this.threadCreated = true;
    }
  }

  summary() {
    return {
      totalEvents: this.events.length,
      tokens: this.tokens,
      actions: this.actions.length,
      agentOutputs: this.agentOutputs.length,
      repairEvents: this.repairEvents.length,
      errors: this.errors.length,
      done: this.done,
      wizardDone: this.wizardDone,
      fullTextLength: this.fullText.length,
    };
  }
}

// ===== POLLING =====
async function pollEndpoints(repoName, intentDir, seq, prevTimeline, prevRepairCount) {
  let newTimelineCount = prevTimeline;
  let newRepairCount = prevRepairCount;
  let statusData = null;

  // Status
  try {
    statusData = await apiFetch('/api/status');
    writeFileSync(resolve(intentDir, 'polls', `status-${String(seq).padStart(4,'0')}.json`), JSON.stringify(statusData, null, 2));
  } catch {}

  // Databases
  try {
    const dbs = await apiFetch('/api/databases');
    writeFileSync(resolve(intentDir, 'polls', `databases-${String(seq).padStart(4,'0')}.json`), JSON.stringify(dbs, null, 2));
    return { statusData, newTimelineCount: prevTimeline, newRepairCount: prevRepairCount };
  } catch {}

  // Timeline
  try {
    const tl = await apiFetch(`/api/timeline/${encodeURIComponent(repoName)}`);
    const tlEntries = tl?.entries || tl?.events || [];
    if (tlEntries.length > prevTimeline) {
      newTimelineCount = tlEntries.length;
      writeFileSync(resolve(intentDir, 'polls', `timeline-${String(seq).padStart(4,'0')}.json`), JSON.stringify(tl, null, 2));
    }
  } catch {}

  // Repair history
  try {
    const rh = await apiFetch('/api/repair-history?limit=50');
    const rhEntries = rh?.entries || [];
    if (rhEntries.length > prevRepairCount) {
      newRepairCount = rhEntries.length;
      writeFileSync(resolve(intentDir, 'polls', `repair-history-${String(seq).padStart(4,'0')}.json`), JSON.stringify(rh, null, 2));
    }
  } catch {}

  return { statusData, newTimelineCount, newRepairCount };
}

// ===== DETECCIÓ DE TERMINAL =====
function getRepoState(statusData, repoName) {
  if (!statusData || typeof statusData !== 'object') return null;
  const svcs = statusData[repoName];
  if (!Array.isArray(svcs) || svcs.length === 0) return null;
  const allRunning = svcs.every(s => s.pid);
  return allRunning ? 'running' : 'failed';
}

// ===== VALIDACIONS =====
async function runValidations(page, repoName, repoPath, intentDir, chatTracker, threadId) {
  const results = [];
  function add(check, ok, ev) { results.push({ check, ok, evidence: ev || '' }); }

  // V1: Thread complet
  try {
    const threadRes = await apiFetch(`/api/chat/threads/${threadId}`);
    const msgs = threadRes?.messages || [];
    add('chat-thread-history', msgs.length > 0, `${msgs.length} missatges`);
  } catch (e) {
    add('chat-thread-history', false, `Error: ${e.message}`);
  }

  // V2: Status running
  try {
    const status = await apiFetch('/api/status');
    const repoStatus = status[repoName];
    const running = Array.isArray(repoStatus) && repoStatus.length > 0 && repoStatus.some(s => s.pid);
    add('status-running', running, `Repo running: ${running}`);
  } catch (e) {
    add('status-running', false, `Error: ${e.message}`);
  }

  // V3: Visible al dashboard
  try {
    await page.goto(DASHBOARD_URL + '/#tab-repos', { waitUntil: 'networkidle', timeout: 10000 });
    await sleep(2000);
    const card = page.locator('.card').filter({ hasText: repoName });
    const visible = await card.count() > 0;
    add('ui-repo-visible', visible, `${repoName} visible al panell: ${visible}`);
    await page.screenshot({ path: resolve(intentDir, 'screenshots', 'valid-repos-panel.png'), fullPage: true });
  } catch (e) {
    add('ui-repo-visible', false, `Error: ${e.message}`);
  }

  // V4: Databases
  try {
    const dbs = await apiFetch('/api/databases');
    const dbEntries = dbs?.databases || dbs?._databases || [];
    add('databases-api', true, `${dbEntries.length} BDs`);
  } catch (e) {
    add('databases-api', false, `Error: ${e.message}`);
  }

  // V5: Frontend respon HTTP
  try {
    let frontendOk = false;
    const ports = [];
    // Llegir logs per ports
    const logsDir = resolve(WORKSPACE, '.agent_logs');
    if (existsSync(logsDir)) {
      const files = execSync(`ls -t "${logsDir}"/*.log 2>/dev/null | head -10`, { encoding: 'utf-8' });
      for (const f of files.split('\n').filter(Boolean)) {
        try {
          const content = readFileSync(f, 'utf-8');
          const ms = [...content.matchAll(/(?:localhost|0\.0\.0\.0):(\d{4,5})/g)];
          for (const m of ms) ports.push(m[1]);
        } catch {}
      }
    }
    for (const port of [...new Set(ports)].slice(0, 5)) {
      try {
        const code = execSync(`curl -s -o /dev/null -w '%{http_code}' http://localhost:${port} --max-time 5`, { encoding: 'utf-8' }).trim();
        if (['200','301','302','401','403','404'].includes(code)) { frontendOk = true; break; }
      } catch {}
    }
    add('frontend-http', frontendOk, `Frontend respon: ${frontendOk}`);
  } catch (e) {
    add('frontend-http', false, `Error: ${e.message}`);
  }

  // V6: Botó Stop
  try {
    await page.goto(DASHBOARD_URL + '/#tab-repos', { waitUntil: 'networkidle', timeout: 10000 });
    await sleep(2000);
    const stopBtn = page.locator(`button[data-stop-repo="${repoName}"]`);
    if (await stopBtn.count() > 0) {
      await stopBtn.first().click();
      await sleep(4000);
      const statusAfter = await apiFetch('/api/status');
      const stillRunning = statusAfter[repoName]?.some(s => s.pid);
      add('button-stop', !stillRunning, `Stop atura: ${!stillRunning}`);
    } else {
      add('button-stop', false, 'Botó no visible');
    }
  } catch (e) {
    add('button-stop', false, `Error: ${e.message}`);
  }

  // V7: Botó Restart (relaunch first)
  try {
    await apiFetch('/api/launch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `input=${encodeURIComponent(repoPath)}&approve_all=on`,
    });
    await sleep(15000);
    const pre = await apiFetch('/api/status');
    const pidPre = pre[repoName]?.[0]?.pid;
    await apiFetch('/api/restart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `repo=${encodeURIComponent(repoName)}`,
    });
    await sleep(15000);
    const post = await apiFetch('/api/status');
    const pidPost = post[repoName]?.[0]?.pid;
    const changed = !pidPre || !pidPost || String(pidPre) !== String(pidPost);
    add('button-restart', changed, `PID canvia: ${changed}`);
  } catch (e) {
    add('button-restart', false, `Error: ${e.message}`);
  }

  // V8: Timeline
  try {
    await page.goto(DASHBOARD_URL + '/#tab-repos', { waitUntil: 'networkidle', timeout: 10000 });
    await sleep(2000);
    const tlBtn = page.locator(`button[data-load-timeline="${repoName}"]`);
    if (await tlBtn.count() > 0) {
      await tlBtn.first().click();
      await sleep(2000);
      const tlEl = page.locator(`#tl-${repoName}`);
      const text = (await tlEl.textContent().catch(() => '')) || '';
      add('button-timeline', text.length > 10, `Timeline: ${text.length} chars`);
      await page.screenshot({ path: resolve(intentDir, 'screenshots', 'valid-timeline.png'), fullPage: true });
    } else {
      add('button-timeline', false, 'Botó no visible');
    }
  } catch (e) {
    add('button-timeline', false, `Error: ${e.message}`);
  }

  // V9: Botó Logs
  try {
    const logsBtn = page.locator('button[data-view-logs]').first();
    const vis = await logsBtn.count() > 0;
    if (vis) {
      await logsBtn.click();
      await sleep(1000);
      await page.screenshot({ path: resolve(intentDir, 'screenshots', 'valid-logs.png'), fullPage: true });
    }
    add('button-logs', vis, `Logs visible: ${vis}`);
  } catch (e) {
    add('button-logs', false, `Error: ${e.message}`);
  }

  // V10: Repair events
  const hasRepair = chatTracker.repairEvents.length > 0;
  add('repair-events-in-chat', hasRepair, `${chatTracker.repairEvents.length} repair events al xat`);

  // V11: Cap error no tractat
  const untreatedErrors = chatTracker.errors.filter(err => {
    const errTs = new Date(err.ts || err.arrived || 0).getTime();
    return !chatTracker.repairEvents.some(re => {
      const reTs = new Date(re.ts || re.arrived || 0).getTime();
      return reTs >= errTs; // repair event after error
    });
  });
  add('no-untreated-errors', untreatedErrors.length === 0, `Errors no tractats: ${untreatedErrors.length}`);

  writeFileSync(resolve(intentDir, 'validations.json'), JSON.stringify({
    results,
    summary: { total: results.length, passed: results.filter(r => r.ok).length },
  }, null, 2));

  const okCount = results.filter(r => r.ok).length;
  console.log(`  [validations] ${okCount}/${results.length} OK`);
  return results;
}

// ===== EXECUCIÓ D'UN INTENT =====
async function runIntent(page, repo, intentNum, runDir, shouldSabotage) {
  const repoName = repo.name;
  const repoPath = repo.path;
  const intentLabel = `intent-${String(intentNum).padStart(2, '0')}`;
  const intentDir = resolve(runDir, repoName, intentLabel);
  ensureDir(intentDir);
  ensureDir(resolve(intentDir, 'polls'));
  ensureDir(resolve(intentDir, 'screenshots'));
  ensureDir(resolve(intentDir, 'repair-events'));

  console.log(`\n${'='.repeat(60)}`);
  console.log(`🎯 ${repoName} — Intent ${intentNum}${shouldSabotage ? ' (SABOTAGE 🔧)' : ''}`);
  console.log(`${'='.repeat(60)}`);

  const intentMeta = {
    repo: repoName, intent: intentNum, startTime: nowISO(),
    sabotage: !!shouldSabotage, sabotageActions: [], redactions: 0, status: 'incomplete',
  };

  // 3a. Crear thread
  const threadName = `battery-${repoName}-${intentLabel}`;
  console.log(`  [thread] Creant "${threadName}"...`);
  const threadRes = await apiFetch('/api/chat/threads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: threadName }),
  });
  const threadId = threadRes?.thread?.id;
  if (!threadId) {
    console.error(`  [thread] ❌ No s'ha pogut crear`);
    intentMeta.status = 'error';
    writeFileSync(resolve(intentDir, 'meta.json'), JSON.stringify(intentMeta, null, 2));
    return { intentMeta, allPassed: false, chatTracker: new ChatEventTracker() };
  }
  console.log(`  [thread] ID: ${threadId}`);
  intentMeta.threadId = threadId;

  // 3b. Connectar WebSocket de xat
  const chatTracker = new ChatEventTracker();
  const wsEventsFile = resolve(intentDir, 'ws-events.jsonl');
  console.log(`  [ws:chat] Connectant...`);
  let chatWs;
  try {
    chatWs = await connectWebSocket(
      WS_CHAT_URL,
      (data) => {
        const { text: clean } = sanitize(JSON.stringify(data));
        appendFileSync(wsEventsFile, JSON.stringify({ arrived: nowISO(), type: data.type, data: clean }) + '\n');
        chatTracker.process(data);
        if (data.type === 'repair_event') {
          writeFileSync(
            resolve(intentDir, 'repair-events', `repair-${chatTracker.repairEvents.length}.json`),
            JSON.stringify(data, null, 2)
          );
        }
      },
      (err) => console.error(`  [ws:chat] Error:`, err?.message || err)
    );
  } catch (e) {
    console.error(`  [ws:chat] ❌ ${e.message}`);
    intentMeta.status = 'error';
    return { intentMeta, allPassed: false, chatTracker: new ChatEventTracker() };
  }
  chatWs.send(JSON.stringify({ type: 'set_thread', thread_id: threadId }));
  await sleep(2000);

  // 3c. Pre-unmount
  await preUnmount(repoName, intentDir);

  // 3k. Sabotage
  let sabotageInfo = null;
  if (shouldSabotage) {
    sabotageInfo = await applySabotage(repoName);
    intentMeta.sabotageActions = sabotageInfo?.actions || [];
    await sleep(2000);
  }

  // 3d. Llançament
  await launchRepo(repoPath, intentDir);

  // 3e. WebSocket de logs
  console.log(`  [ws:logs] Connectant...`);
  const logsWsFile = resolve(intentDir, 'logs-stream.txt');
  try {
    const logsWs = await connectWebSocket(
      `ws://localhost:9999/ws/logs/${encodeURIComponent(repoName)}`,
      (data) => appendFileSync(logsWsFile, JSON.stringify(data) + '\n'),
      () => {}
    );
  } catch (e) {
    writeFileSync(logsWsFile, `Error connectant: ${e.message}\n`);
  }

  // 3f. Polling loop
  let seq = 0;
  let prevTimeline = 0;
  let prevRepairCount = 0;
  let terminalState = null;
  let stableCount = 0;

  const screenshotTimer = setInterval(async () => {
    try {
      await page.screenshot({
        path: resolve(intentDir, 'screenshots', `snap-${String(seq).padStart(3,'0')}.png`),
        fullPage: true,
      });
    } catch {}
  }, SCREENSHOT_INTERVAL_MS);

  const startTime = Date.now();
  let done = false;

  while (!done) {
    seq++;
    await sleep(POLL_INTERVAL_MS);

    try {
      const { statusData, newTimelineCount, newRepairCount } = await pollEndpoints(
        repoName, intentDir, seq, prevTimeline, prevRepairCount
      );
      prevTimeline = newTimelineCount;
      prevRepairCount = newRepairCount;

      const state = getRepoState(statusData, repoName);
      if (state) {
        if (state === terminalState) {
          stableCount++;
        } else {
          terminalState = state;
          stableCount = 1;
        }
      }
    } catch {}

    // Detecció de final: WS done + estat estable 6 polls (30s)
    if (chatTracker.done && terminalState && stableCount >= 6) {
      console.log(`  [poll] ✅ Final: WS done + status ${terminalState} estable ${stableCount * 5}s`);
      done = true;
    }

    // Timeout
    if (Date.now() - startTime > INTENT_TIMEOUT_MS) {
      console.log(`  [poll] ⏱️  Timeout 25min`);
      done = true;
    }
  }

  clearInterval(screenshotTimer);

  // Revertir sabotatge
  if (sabotageInfo) await revertSabotage(repoName, sabotageInfo);

  // 3h. Screenshots finals
  for (const tab of ['#tab-repos', '#tab-databases', '#tab-chat']) {
    try {
      await page.goto(DASHBOARD_URL + '/' + tab, { waitUntil: 'networkidle', timeout: 10000 });
      await sleep(2000);
      const tabName = tab.replace('#tab-', '');
      await page.screenshot({ path: resolve(intentDir, 'screenshots', `final-${tabName}.png`), fullPage: true });
    } catch {}
  }

  // 3i. Validacions
  const validations = await runValidations(page, repoName, repoPath, intentDir, chatTracker, threadId);

  // Resum WS
  const wsSummary = chatTracker.summary();
  console.log(`  [ws] events:${wsSummary.totalEvents} tokens:${wsSummary.tokens} actions:${wsSummary.actions} repair:${wsSummary.repairEvents} errors:${wsSummary.errors}`);

  // Netejar thread
  try { await apiFetch(`/api/chat/threads/${threadId}`, { method: 'DELETE' }); } catch {}

  // Meta
  intentMeta.endTime = nowISO();
  const allPassed = validations.every(v => v.ok);
  intentMeta.status = allPassed ? 'success' : 'partial';
  intentMeta.wsSummary = wsSummary;
  intentMeta.chatRedactions = intentMeta.redactions;
  intentMeta.allValidationsPassed = allPassed;
  writeFileSync(resolve(intentDir, 'meta.json'), JSON.stringify(intentMeta, null, 2));

  return { intentMeta, validations, allPassed, chatTracker };
}

// ===== EXECUCIÓ D'UN REPO =====
async function runRepo(page, repo, runDir) {
  const repoDir = resolve(runDir, repo.name);
  ensureDir(repoDir);

  console.log(`\n${'#'.repeat(60)}`);
  console.log(`## REPO: ${repo.name} — ${repo.description}`);
  console.log(`${'#'.repeat(60)}`);

  let consecutiveClean = 0;
  let intentNum = 0;
  const allResults = [];

  while (consecutiveClean < REQUIRED_CONSECUTIVE && intentNum < MAX_INTENTS_PER_REPO) {
    intentNum++;
    const sabotage = repo.needsSabotage && intentNum === 2;
    const result = await runIntent(page, repo, intentNum, runDir, sabotage);
    allResults.push(result);

    if (result.allPassed) {
      consecutiveClean++;
      console.log(`  ✅ Net (${consecutiveClean}/${REQUIRED_CONSECUTIVE} consecutius)`);
    } else {
      consecutiveClean = 0;
      console.log(`  ⚠️  Amb fallades, reset`);
    }

    if (intentNum < MAX_INTENTS_PER_REPO) await sleep(10000);
  }

  const repoSummary = {
    repo: repo.name,
    totalIntents: intentNum,
    consecutiveClean,
    reachedTarget: consecutiveClean >= REQUIRED_CONSECUTIVE,
    results: allResults.map(r => ({
      intent: r.intentMeta.intent,
      passed: r.allPassed,
      sabotage: r.intentMeta.sabotage,
      repairEvents: r.chatTracker.repairEvents.length,
      validationsOk: r.intentMeta.allValidationsPassed,
    })),
  };
  writeFileSync(resolve(repoDir, 'summary.json'), JSON.stringify(repoSummary, null, 2));
  return repoSummary;
}

// ===== INFORMES =====
function generateReports(runDir, repoResults) {
  // summary.md
  let smd = `# Bateria Bartolo — Resum\n\n**Data**: ${nowISO()}\n`;
  smd += `**Repos**: ${repoResults.length}\n\n`;
  smd += `| Repo | Intents | Nets consecutius | Repair events |\n`;
  smd += `|------|---------|------------------|---------------|\n`;
  for (const r of repoResults) {
    const repairTotal = r.results.reduce((s, i) => s + (i.repairEvents || 0), 0);
    smd += `| ${r.repo} | ${r.totalIntents} | ${r.consecutiveClean}/${REQUIRED_CONSECUTIVE} | ${repairTotal} |\n`;
  }
  const allReached = repoResults.every(r => r.reachedTarget);
  smd += `\n**Resultat**: ${allReached ? 'SUCCESS' : 'PARTIAL'}\n`;
  writeFileSync(resolve(runDir, 'summary.md'), smd);

  // dashboard-features-matrix.md
  const features = [
    'chat-thread-history', 'status-running', 'ui-repo-visible',
    'databases-api', 'frontend-http', 'button-stop', 'button-restart',
    'button-timeline', 'button-logs', 'repair-events-in-chat', 'no-untreated-errors',
  ];
  let mmd = `# Dashboard Features Matrix\n\n**Data**: ${nowISO()}\n\n`;
  mmd += `| Funció | ${repoResults.map(r => r.repo).join(' | ')} |\n`;
  mmd += `|--------|${repoResults.map(() => '-------|').join('')}\n`;
  let allFeaturesOk = true;
  for (const f of features) {
    mmd += `| ${f} |`;
    for (const r of repoResults) {
      let best = 'N/A';
      for (const intent of r.results) {
        const v = intent.validations?.find(vv => vv.check === f);
        if (v) { best = v.ok ? 'OK' : 'FAIL'; break; }
      }
      if (best === 'FAIL') allFeaturesOk = false;
      mmd += ` ${best} |`;
    }
    mmd += '\n';
  }
  mmd += `\n**Global**: ${allFeaturesOk ? '✅ Totes OK' : '⚠️  Almenys un FAIL'}\n`;
  writeFileSync(resolve(runDir, 'dashboard-features-matrix.md'), mmd);
  return { allReached, allFeaturesOk };
}

// ===== MAIN =====
async function main() {
  console.log('🧪 bartolo-battery — Bateria de validació del dashboard Bartolo\n');

  checkPrerequisites();

  const runId = ts();
  const runDir = resolve(RUNS_DIR, runId);
  ensureDir(runDir);
  console.log(`[battery] Run ID: ${runId}`);
  console.log(`[battery] Run dir: ${runDir}\n`);

  // Instal·lar Playwright si cal
  try {
    execSync('npx playwright --version 2>/dev/null', { stdio: 'pipe', timeout: 10000 });
  } catch {
    console.log('[battery] Instal·lant Playwright...');
    execSync('npm install -D playwright 2>&1', { stdio: 'inherit', cwd: import.meta.dirname, timeout: 60000 });
    execSync('npx playwright install chromium 2>&1', { stdio: 'inherit', cwd: import.meta.dirname, timeout: 120000 });
  }

  // Obrir Chromium
  console.log('[battery] Obrint Chromium...');
  let browser;
  for (let i = 1; i <= 3; i++) {
    try {
      browser = await chromium.launch({ headless: true });
      break;
    } catch (e) {
      console.error(`  Intent ${i}/3: ${e.message}`);
      if (i === 3) { console.error('RESULT: error: dashboard inaccessible'); process.exit(1); }
      await sleep(5000);
    }
  }

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // Verificar dashboard
  console.log('[battery] Verificant dashboard...');
  let dashOk = false;
  for (let i = 1; i <= 3; i++) {
    try {
      await page.goto(DASHBOARD_URL, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForSelector('#tab-visio', { timeout: 5000 });
      dashOk = true;
      break;
    } catch (e) {
      console.error(`  Intent ${i}/3: ${e.message}`);
      await sleep(5000);
    }
  }
  if (!dashOk) { console.error('RESULT: error: dashboard inaccessible'); await browser.close(); process.exit(1); }

  await page.screenshot({ path: resolve(runDir, 'initial.png'), fullPage: true });
  console.log('[battery] ✅ Dashboard accessible\n');

  // Processar repos
  const repoResults = [];
  for (const repo of BATTERY_REPOS) {
    const result = await runRepo(page, repo, runDir);
    repoResults.push(result);
  }

  // Informes
  const { allReached, allFeaturesOk } = generateReports(runDir, repoResults);
  await browser.close();

  // Resultat
  let finalResult;
  if (allReached && allFeaturesOk) finalResult = 'success';
  else if (repoResults.some(r => r.reachedTarget)) finalResult = 'partial';
  else finalResult = 'failure';

  console.log(`\n${'='.repeat(60)}`);
  console.log(`RESULT: ${finalResult}`);
  console.log(`Run dir: ${runDir}`);
  console.log(`${'='.repeat(60)}`);
}

main().catch(err => {
  console.error('FATAL:', err);
  process.exit(1);
});
