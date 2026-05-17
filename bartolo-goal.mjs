#!/usr/bin/env node
/**
 * bartolo-goal.mjs — Playwright script per disparar un muntatge via dashboard Bartolo :9999
 * Llegeix .env.local, pobla la cache de secrets, obre el dashboard, envia "munta",
 * gestiona el wizard automàticament, captura tota la sessió i guarda transcript + screenshots.
 */

import { chromium } from 'playwright';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { execSync } from 'child_process';
import { homedir } from 'os';

// ===== CONFIGURACIÓ =====
const DASHBOARD_URL = 'http://localhost:9999';
const REPO_PATH = resolve(homedir(), 'Projects/wa-desk');
const ENV_LOCAL = resolve(REPO_PATH, '.env.local');
const SECRETS_CACHE = resolve(homedir(), '.universal-agent/secrets.json');
const RUNS_DIR = resolve(import.meta.dirname, 'runs');
const MAX_DURATION_MS = 6 * 60 * 60 * 1000; // 6 hores
const SCREENSHOT_INTERVAL_MS = 60_000; // cada 60 segons
const SAVE_INTERVAL_MS = 30_000; // transcript cada 30 segons
const QUIESCENCE_MS = 15_000; // 15 segons sense canvis = final

// ===== REQUIRED KEYS =====
const REQUIRED_KEYS = [
  'SUPABASE_URL', 'SUPABASE_ANON_KEY', 'SUPABASE_SERVICE_ROLE_KEY',
  'JWT_SECRET', 'SUPABASE_PUBLISHABLE_KEY',
  'SUPERADMIN_EMAIL', 'SUPERADMIN_PASSWORD',
  'ADMIN_EMAIL', 'ADMIN_PASSWORD',
];

// ===== SANITITZACIÓ =====
function sanitize(text) {
  let count = 0;
  let out = text;
  // JWTs (eyJ...)
  out = out.replace(/eyJ[A-Za-z0-9\-_]{20,}={0,2}/g, (m) => { count++; return '<REDACTED>'; });
  // Supabase keys (sb_secret_..., sb_publishable_...)
  out = out.replace(/\b(sb_secret_|sb_publishable_)[A-Za-z0-9\-_]{10,}/g, (m) => { count++; return '<REDACTED>'; });
  // High-entropy strings (>20 chars, no spaces, looks like a key)
  out = out.replace(/\b[A-Za-z0-9\-_+/=]{40,}\b/g, (m) => {
    // Skip URLs and common patterns
    if (m.startsWith('http') || m.startsWith('www.')) return m;
    count++;
    return '<REDACTED>';
  });
  return { text: out, redactions: count };
}

// ===== TIMESTAMP =====
function ts() {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}_${String(d.getHours()).padStart(2,'0')}${String(d.getMinutes()).padStart(2,'0')}${String(d.getSeconds()).padStart(2,'0')}`;
}

// ===== MAIN =====
async function main() {
  // --- 0. Setup ---
  console.log('[bartolo-goal] Iniciant...');
  const runId = ts();
  const runDir = resolve(RUNS_DIR, runId);
  const ssDir = resolve(runDir, 'screenshots');
  mkdirSync(runDir, { recursive: true });
  mkdirSync(ssDir, { recursive: true });

  const meta = {
    start_time: new Date().toISOString(),
    end_time: null,
    chat_url: DASHBOARD_URL + '/#tab-chat',
    status: 'incomplete',
    redactions: 0,
  };

  // --- 1. Verificar .env.local ---
  console.log('[bartolo-goal] Verificant .env.local...');
  if (!existsSync(ENV_LOCAL)) {
    console.error(`ERROR: ${ENV_LOCAL} no existeix. Crea'l manualment amb les credencials.`);
    meta.status = 'error';
    meta.error = '.env.local not found';
    writeFileSync(resolve(runDir, 'meta.json'), JSON.stringify(meta, null, 2));
    process.exit(1);
  }

  const envContent = readFileSync(ENV_LOCAL, 'utf-8');
  const envVars = {};
  for (const line of envContent.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq === -1) continue;
    envVars[trimmed.substring(0, eq)] = trimmed.substring(eq + 1);
  }

  const missing = REQUIRED_KEYS.filter(k => !envVars[k] || envVars[k].includes('EDITA'));
  if (missing.length > 0) {
    console.error(`ERROR: Claus incompletes o truncades a .env.local: ${missing.join(', ')}`);
    console.error('Edita .env.local amb els valors complets abans de continuar.');
    meta.status = 'error';
    meta.error = `Missing/incomplete keys: ${missing.join(', ')}`;
    writeFileSync(resolve(runDir, 'meta.json'), JSON.stringify(meta, null, 2));
    process.exit(1);
  }
  console.log(`[bartolo-goal] ${REQUIRED_KEYS.length} claus verificades.`);

  // Mostrar noms de claus (mai valors)
  console.log('[bartolo-goal] Claus trobades:');
  for (const k of REQUIRED_KEYS) console.log(`  - ${k}: ***`);

  // --- 2. Poblar secrets cache ---
  console.log('[bartolo-goal] Poblant cache de secrets...');
  const secretsDir = dirname(SECRETS_CACHE);
  if (!existsSync(secretsDir)) mkdirSync(secretsDir, { recursive: true });

  let cache = {};
  if (existsSync(SECRETS_CACHE)) {
    try { cache = JSON.parse(readFileSync(SECRETS_CACHE, 'utf-8')); } catch {}
  }

  // Mapejar .env.local keys → cache keys
  const keyMap = {
    SUPABASE_URL: 'SUPABASE_URL',
    SUPABASE_ANON_KEY: 'SUPABASE_ANON_KEY',
    SUPABASE_SERVICE_ROLE_KEY: 'SUPABASE_SERVICE_ROLE_KEY',
    JWT_SECRET: 'JWT_SECRET',
    SUPABASE_PUBLISHABLE_KEY: 'SUPABASE_PUBLISHABLE_KEY',
  };
  for (const [envKey, cacheKey] of Object.entries(keyMap)) {
    if (envVars[envKey]) cache[cacheKey] = envVars[envKey];
  }
  // Afegir també DATABASE_URL per PostgreSQL local
  if (!cache.DATABASE_URL) {
    cache.DATABASE_URL = 'postgresql://agentuser:agentpass@localhost:5432/agentdb';
  }
  writeFileSync(SECRETS_CACHE, JSON.stringify(cache, null, 2));
  console.log('[bartolo-goal] Cache de secrets actualitzada.');

  // --- 3. Llençar Playwright ---
  console.log('[bartolo-goal] Arrencant Chromium...');

  // Verificar Playwright instal·lat
  try { execSync('npx playwright --version', { stdio: 'pipe' }); } catch {
    console.log('[bartolo-goal] Instal·lant Playwright...');
    execSync('npm i -D playwright', { stdio: 'inherit', cwd: import.meta.dirname });
    execSync('npx playwright install chromium', { stdio: 'inherit', cwd: import.meta.dirname });
  }

  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({
    viewport: { width: 1400, height: 900 },
    locale: 'ca',
  });
  const page = await context.newPage();

  // Col·lecció de transcripció
  let transcript = '';
  let totalRedactions = 0;
  const messages = []; // {role, content, time}

  function appendTranscript(role, content) {
    const time = new Date().toISOString();
    const s = sanitize(content);
    totalRedactions += s.redactions;
    messages.push({ role, content: s.text, time });
    transcript += `## ${role} (${time})\n\n${s.text}\n\n---\n\n`;
  }

  // --- 4. Obrir dashboard ---
  console.log('[bartolo-goal] Obrint dashboard...');
  let loaded = false;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await page.goto(DASHBOARD_URL, { timeout: 15_000, waitUntil: 'domcontentloaded' });
      await page.waitForSelector('#chat-input', { timeout: 10_000, state: 'attached' });
      loaded = true;
      break;
    } catch {
      console.log(`  Intent ${attempt + 1}/3 fallit, reintentant...`);
      await new Promise(r => setTimeout(r, 5000));
    }
  }
  if (!loaded) {
    console.error('ERROR: No s\'ha pogut carregar el dashboard.');
    meta.status = 'error';
    meta.error = 'Dashboard not reachable';
    writeFileSync(resolve(runDir, 'meta.json'), JSON.stringify(meta, null, 2));
    await browser.close();
    process.exit(1);
  }

  // Guardar URL del xat
  writeFileSync(resolve(runDir, 'chat-url.txt'), DASHBOARD_URL + '/#tab-chat');

  // --- 5. Navegar al Chat i crear xat nou ---
  console.log('[bartolo-goal] Navegant al Xat...');
  await page.click('nav a[data-tab="chat"]');
  await page.waitForTimeout(500);

  // Fer clic a "Xat nou" (botó +)
  const newThreadBtn = page.locator('#new-thread-btn');
  if (await newThreadBtn.isVisible()) {
    await newThreadBtn.click();
    await page.waitForTimeout(500);
    console.log('[bartolo-goal] Xat nou creat.');
  }

  // --- 6. Enviar el missatge de muntatge ---
  const mountMessage = `munta ${REPO_PATH}

Carrega les variables d'entorn des de .env.local (ja són a la cache de secrets).
Base de dades: Supabase remot. No migris dades, només estructura (schema).
Crea els usuaris admin (superadmin i admin) a la BD local amb les credencials del .env.local.
Desmunta qualsevol estat anterior abans de muntar.`;

  console.log('[bartolo-goal] Enviant missatge de muntatge...');
  appendTranscript('user', mountMessage);

  const chatInput = page.locator('#chat-input');
  await chatInput.fill(mountMessage);
  await page.waitForTimeout(200);

  // Fer clic a Enviar
  await page.click('#chat-send-btn');
  console.log('[bartolo-goal] Missatge enviat. Esperant resposta...');

  // --- 7. Bucle principal de captura ---
  const startTime = Date.now();
  let lastDomSnapshot = '';
  let lastChangeTime = Date.now();
  let wizardActive = false;
  let screenshotInterval;

  // Captura incremental cada 60s
  screenshotInterval = setInterval(async () => {
    try {
      await page.screenshot({ path: resolve(ssDir, `capture_${Date.now()}.png`), fullPage: true });
    } catch {}
  }, SCREENSHOT_INTERVAL_MS);

  // Guardat incremental de transcript cada 30s
  const saveInterval = setInterval(() => {
    if (transcript) {
      meta.redactions = totalRedactions;
      writeFileSync(resolve(runDir, 'transcript.md'), transcript);
      writeFileSync(resolve(runDir, 'meta.json'), JSON.stringify(meta, null, 2));
    }
  }, SAVE_INTERVAL_MS);

  // Funció per obtenir missatges del DOM
  async function getChatMessages() {
    return await page.evaluate(() => {
      const msgs = document.querySelectorAll('#chat-messages .msg');
      return Array.from(msgs).map(m => ({
        role: m.classList.contains('user') ? 'user' :
              m.classList.contains('assistant') ? 'assistant' : 'system',
        text: m.textContent || '',
      }));
    });
  }

  // Funció per gestionar wizard
  async function handleWizardStep() {
    try {
      // Detectar si hi ha un wizard form actiu
      const wizardForm = page.locator('.wizard-form');
      if (!(await wizardForm.isVisible().catch(() => false))) return false;

      wizardActive = true;
      const stepTitle = await page.locator('.wizard-step-title').first().textContent().catch(() => '');
      console.log(`[bartolo-goal] Wizard step detectat: ${stepTitle?.trim()}`);

      // Determinar quin tipus de pas és
      const title = (stepTitle || '').toLowerCase();

      if (title.includes('carpeta') || title.includes('workspace')) {
        // Pas workspace: usar el repo path com a carpeta
        const wsInput = page.locator('.wizard-input[data-wizard-input="workspace"]');
        if (await wsInput.isVisible().catch(() => false)) {
          await wsInput.fill(REPO_PATH);
          console.log('[bartolo-goal] Wizard workspace: usant repo path.');
        }
      } else if (title.includes('cloud')) {
        // Pas cloud_choice: seleccionar "local" per a tot
        const localToggles = page.locator('.wt-toggle input[value="local"]');
        const count = await localToggles.count().catch(() => 0);
        for (let i = 0; i < count; i++) {
          const toggle = localToggles.nth(i);
          if (!(await toggle.isChecked().catch(() => true))) {
            await toggle.click().catch(() => {});
          }
        }
        console.log('[bartolo-goal] Wizard cloud: seleccionat local per a tot.');
      } else if (title.includes('supabase') && title.includes('migra')) {
        // Pas supabase_migrate: seleccionar "Sí"
        const yesBtn = page.locator('.wizard-btn-primary').filter({ hasText: /Sí|yes/i }).first();
        if (await yesBtn.isVisible().catch(() => false)) {
          await yesBtn.click().catch(() => {});
          console.log('[bartolo-goal] Wizard supabase_migrate: Sí.');
        }
      } else if (title.includes('confirm') || title.includes('resum')) {
        // Pas confirm: fer clic a "Munta"
        console.log('[bartolo-goal] Wizard confirm: muntant...');
      }

      // Fer clic a "Continua" / "Munta" si existeix (wizard-btn-primary)
      // Buscar en ordre: primer .wizard-btn-primary, després .wizard-btn-skip (Ometre)
      const continueBtn = page.locator('.wizard-form .wizard-btn-primary').last();
      if (await continueBtn.isVisible().catch(() => false)) {
        const btnText = await continueBtn.textContent().catch(() => '');
        if (!btnText.includes('Tornar')) {
          await continueBtn.click().catch(() => {});
          console.log(`[bartolo-goal] Wizard: clicat "${btnText?.trim()}"`);
          await page.waitForTimeout(1000);
        }
      }
      return true;
    } catch (e) {
      console.log(`[bartolo-goal] Error gestionant wizard: ${e.message}`);
      return false;
    }
  }

  // Bucle principal d'espera
  try {
    while (Date.now() - startTime < MAX_DURATION_MS) {
      await page.waitForTimeout(1000);

      // Gestionar wizard si n'hi ha
      const wasWizard = await handleWizardStep();
      if (wasWizard) {
        lastChangeTime = Date.now();
        continue;
      }

      // Si abans hi havia wizard i ara ja no, l'agent s'ha llençat
      if (wizardActive && !wasWizard) {
        wizardActive = false;
        console.log('[bartolo-goal] Wizard completat. Agent en marxa...');
        lastChangeTime = Date.now();
      }

      // Capturar missatges nous del DOM
      const currentMsgs = await getChatMessages();
      const snapshot = JSON.stringify(currentMsgs.map(m => m.text?.slice(-100)));

      if (snapshot !== lastDomSnapshot) {
        lastDomSnapshot = snapshot;
        lastChangeTime = Date.now();

        // Afegir missatges nous a la transcripció
        for (const msg of currentMsgs) {
          const existing = messages.find(m => m.content === msg.text && m.role === msg.role);
          if (!existing && msg.text?.trim()) {
            appendTranscript(msg.role, msg.text);
          }
        }
      }

      // Detectar si l'agent ha acabat (missatge amb URL o resum final)
      const allText = currentMsgs.map(m => m.text).join(' ');
      const donePatterns = [
        /Emergent stack iniciat/i,
        /Passos totals:/i,
        /Smoke Tests/i,
        /Per aturar:/i,
        /objectiu assolit/i,
        /dos intents consecutius/i,
        /No he pogut/i,
        /Error:/i,
      ];
      const isDone = donePatterns.some(p => p.test(allText));
      const quiescent = (Date.now() - lastChangeTime) > QUIESCENCE_MS;

      if (isDone && quiescent) {
        console.log('[bartolo-goal] Senyal de finalització detectat.');
        break;
      }
    }
  } catch (e) {
    console.error(`[bartolo-goal] Error al bucle: ${e.message}`);
    meta.status = 'error';
    meta.error = e.message;
  }

  // --- 8. Finalització ---
  clearInterval(screenshotInterval);
  clearInterval(saveInterval);

  // Captura final
  await page.screenshot({ path: resolve(ssDir, 'final.png'), fullPage: true }).catch(() => {});

  // Determinar estat final
  const finalMsgs = await getChatMessages();
  const finalText = finalMsgs.map(m => m.text).join(' ');

  if (finalText.includes('Emergent stack iniciat') ||
      finalText.includes('objectiu assolit') ||
      finalText.includes('dos intents consecutius')) {
    meta.status = 'success';
  } else if (finalText.includes('Error:') || finalText.includes('No he pogut')) {
    meta.status = 'error';
    meta.error = 'Agent reported failure';
  } else {
    meta.status = 'incomplete';
  }

  meta.end_time = new Date().toISOString();
  meta.redactions = totalRedactions;

  // Guardar transcript final
  writeFileSync(resolve(runDir, 'transcript.md'), transcript);
  writeFileSync(resolve(runDir, 'meta.json'), JSON.stringify(meta, null, 2));

  console.log(`\nRESULT: ${meta.status}`);
  if (totalRedactions > 0) {
    console.log(`WARNING: ${totalRedactions} secrets redactats a la transcripció.`);
  }
  console.log(`Transcripció: ${runDir}/transcript.md`);
  console.log(`Screenshots: ${ssDir}/`);
  console.log(`Meta: ${runDir}/meta.json`);

  await browser.close();
  process.exit(meta.status === 'success' ? 0 : 1);
}

main().catch(e => {
  console.error('ERROR fatal:', e);
  process.exit(1);
});
