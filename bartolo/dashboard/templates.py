"""bartolo/dashboard/templates.py — HTML+CSS+JS inline per Dashboard v2."""

INDEX_HTML = r"""<!doctype html>
<html lang="ca">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bartolo Control Center</title>
<style>
:root{--bg:#0d1117;--fg:#c9d1d9;--muted:#8b949e;--ok:#3fb950;--bad:#f85149;--card:#161b22;--accent:#58a6ff;--border:#30363d;--warn:#d29922;--input-bg:#010409}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;margin:0;padding:0;display:flex;height:100vh;overflow:hidden}
/* Sidebar */
aside{width:200px;min-width:200px;background:var(--card);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow-y:auto;padding:8px 0}
aside .logo{padding:16px;font-size:15px;font-weight:bold;color:var(--accent);border-bottom:1px solid var(--border);margin-bottom:8px}
aside a{color:var(--muted);text-decoration:none;padding:10px 16px;font-size:12px;display:flex;align-items:center;gap:8px;transition:all .15s;border-left:2px solid transparent;cursor:pointer}
aside a:hover{color:var(--fg);background:#1c2129}
aside a.active{color:var(--fg);border-left-color:var(--accent);background:#1c2129}
aside .sep{border-top:1px solid var(--border);margin:8px 0}
/* Main */
main{flex:1;display:flex;flex-direction:column;overflow:hidden}
main section{display:none;flex:1;overflow-y:auto;padding:24px}
main section.active,main section:target{display:flex;flex-direction:column}
h1{color:var(--accent);margin:0 0 4px;font-size:18px}
.sub{color:var(--muted);margin-bottom:16px;font-size:11px}
/* Cards */
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:12px}
.card h2{margin:0 0 10px;font-size:14px;color:var(--accent)}
/* Thread sidebar (inside chat) */
.chat-layout{display:flex;flex:1;overflow:hidden}
.thread-sidebar{width:220px;min-width:220px;background:var(--card);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.thread-sidebar .ts-header{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-bottom:1px solid var(--border)}
.thread-sidebar .ts-header span{font-weight:600;font-size:13px;color:var(--accent)}
.thread-sidebar .ts-header button{background:var(--accent);color:#0d1117;border:0;width:26px;height:26px;border-radius:6px;font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center}
.thread-list{flex:1;overflow-y:auto;padding:4px 0}
.thread-item{padding:8px 12px;cursor:pointer;border-left:2px solid transparent;transition:all .15s}
.thread-item:hover{background:#1c2129}
.thread-item.active{background:#1c2945;border-left-color:var(--accent)}
.thread-item .ti-title{font-size:12px;color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.thread-item .ti-meta{font-size:10px;color:var(--muted);margin-top:2px;display:flex;justify-content:space-between}
.thread-item .ti-del{display:none;color:var(--bad);font-size:10px;cursor:pointer}
.thread-item:hover .ti-del{display:inline}
.ts-footer{border-top:1px solid var(--border);padding:6px 12px;font-size:10px;color:var(--muted);display:flex;justify-content:space-between}
/* Chat area (right of thread sidebar) */
.chat-area{flex:1;display:flex;flex-direction:column;overflow:hidden}
.chat-area-header{padding:8px 16px;border-bottom:1px solid var(--border);font-size:12px;font-weight:600;display:flex;justify-content:space-between;align-items:center}
.chat-area-header .editable-title{cursor:pointer;border-bottom:1px dashed transparent}
.chat-area-header .editable-title:hover{border-bottom-color:var(--muted)}
/* Toast notifications */
#toast-container{position:fixed;bottom:16px;right:16px;z-index:200;display:flex;flex-direction:column;gap:6px;max-width:340px}
.toast{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 14px;font-size:12px;animation:slideIn .25s ease-out;display:flex;align-items:center;gap:8px;box-shadow:0 4px 12px rgba(0,0,0,.4)}
.toast.ok{border-left:3px solid var(--ok)}
.toast.bad{border-left:3px solid var(--bad)}
.toast.info{border-left:3px solid var(--accent)}
.toast .toast-close{margin-left:auto;cursor:pointer;color:var(--muted);font-size:14px}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
/* Logs inline panel */
.logs-panel{display:none;background:var(--input-bg);border:1px solid var(--border);border-radius:6px;padding:8px;margin-top:8px;max-height:250px;overflow-y:auto;font-family:monospace;font-size:11px;white-space:pre-wrap;color:var(--fg)}
.logs-panel.show{display:block}
/* Syntax highlight basics */
.syn-keyword{color:#ff7b72}
.syn-string{color:#a5d6ff}
.syn-comment{color:#8b949e;font-style:italic}
.syn-func{color:#d2a8ff}
/* Timeline */
.timeline{border-left:2px solid var(--border);margin-left:8px;padding-left:16px}
.timeline-item{padding:4px 0;font-size:11px}
.timeline-item .tl-time{color:var(--muted);font-size:10px}
.timeline-item .tl-event{color:var(--fg)}
.timeline-item.ok .tl-event{color:var(--ok)}
.timeline-item.bad .tl-event{color:var(--bad)}
/* Progress bar */
.progress-bar{width:100%;height:6px;background:var(--border);border-radius:3px;margin-top:4px;overflow:hidden}
.progress-fill{height:100%;background:var(--accent);border-radius:3px;transition:width .3s}
/* Health indicator */
.health-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}
.health-dot.ok{background:var(--ok)}
.health-dot.warn{background:var(--warn)}
.health-dot.bad{background:var(--bad)}
/* Chat */
#chat-messages{flex:1;overflow-y:auto;padding:16px 0;display:flex;flex-direction:column;gap:8px}
.msg{max-width:85%;padding:10px 14px;border-radius:12px;font-size:13px;line-height:1.5;word-break:break-word}
.msg.user{align-self:flex-end;background:var(--accent);color:#0d1117;border-bottom-right-radius:4px}
.msg.assistant{align-self:flex-start;background:var(--card);border:1px solid var(--border);border-bottom-left-radius:4px}
.msg.system{align-self:center;background:transparent;color:var(--muted);font-size:11px;font-style:italic;max-width:100%}
.msg .token{color:var(--fg)}
#chat-input-area{display:flex;gap:8px;padding:12px 0;border-top:1px solid var(--border)}
#chat-input-area input{flex:1;background:var(--input-bg);border:1px solid var(--border);color:var(--fg);padding:10px 14px;border-radius:8px;font-family:inherit;font-size:13px}
#chat-input-area button{background:var(--accent);color:#0d1117;border:0;padding:10px 18px;border-radius:8px;font-weight:bold;cursor:pointer;font-family:inherit;font-size:13px}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
/* Tables & lists */
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:var(--accent);font-weight:600;padding:8px 12px;border-bottom:1px solid var(--border);font-size:11px;text-transform:uppercase}
td{padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:top}
tr:hover{background:#1c2129}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600}
.badge.ok{background:#1b3a1b;color:var(--ok)}
.badge.bad{background:#3a1b1b;color:var(--bad)}
.badge.warn{background:#3a351b;color:var(--warn)}
.badge.info{background:#1b2a3a;color:var(--accent)}
/* Services */
.svc{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-left:3px solid var(--border);margin-bottom:6px;background:var(--input-bg);border-radius:0 4px 4px 0}
.svc.run{border-left-color:var(--ok)}
.svc.stop{border-left-color:var(--bad);opacity:.6}
.svc-info{flex:1;min-width:0}
.svc-info code{display:block;font-size:10px;color:var(--muted);word-break:break-all}
.svc-info strong{color:var(--fg);font-size:12px}
.actions{display:flex;gap:6px;flex-shrink:0}
/* Buttons */
button{color:var(--fg);background:transparent;border:1px solid var(--border);padding:5px 12px;font-size:11px;cursor:pointer;border-radius:4px;font-family:inherit}
button:hover{background:var(--border)}
button.danger{border-color:var(--bad);color:var(--bad)}
button.danger:hover{background:var(--bad);color:#fff}
button.primary{background:var(--accent);color:#0d1117;border:0;font-weight:bold}
button.primary:hover{opacity:.9;background:var(--accent)}
button.small{padding:3px 8px;font-size:10px}
input,select,textarea{background:var(--input-bg);border:1px solid var(--border);color:var(--fg);padding:8px 12px;border-radius:4px;font-family:inherit;font-size:12px}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--accent)}
.row{display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
/* Forms */
form.launch{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
form.launch input[type=text]{flex:1;min-width:250px}
form.launch label{color:var(--muted);font-size:11px;display:flex;align-items:center;gap:4px}
/* Logs */
pre.logs{background:var(--input-bg);border:1px solid var(--border);border-radius:4px;padding:12px;max-height:400px;overflow:auto;font-size:11px;color:var(--muted);white-space:pre-wrap;word-break:break-all}
pre.logs.output{max-height:300px;margin-top:8px}
.empty{color:var(--muted);font-style:italic;padding:24px;text-align:center}
.flash{padding:8px 12px;margin-bottom:12px;font-size:12px;border-radius:4px}
.flash.error{background:#3a1b1b;color:var(--bad)}
.flash.ok{background:#1b3a1b;color:var(--ok)}
.flash.info{background:#1b2a3a;color:var(--accent)}
/* KV rows */
.kv{display:flex;gap:8px;padding:5px 0;font-size:12px;align-items:center}
.kv-key{color:var(--accent);min-width:160px;font-weight:600}
.kv-val{color:var(--fg);word-break:break-all;flex:1}
.kv-val.masked{color:var(--muted)}
.mask-toggle{color:var(--accent);cursor:pointer;font-size:10px;user-select:none;margin-left:6px}
/* Model card */
.model-item{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:1px solid var(--border);font-size:12px}
.model-item:last-child{border-bottom:0}
.model-name{color:var(--fg);font-weight:600}
.model-info{color:var(--muted)}
.model-actions{display:flex;gap:6px}
/* Modal */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100;align-items:center;justify-content:center}
.modal-bg.show{display:flex}
.modal{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:24px;max-width:700px;width:90%;max-height:80vh;overflow-y:auto}
.modal h2{color:var(--accent);margin-top:0}
/* Toggle switch */
.toggle{position:relative;display:inline-block;width:44px;height:24px}
.toggle input{opacity:0;width:0;height:0}
.toggle .slider{position:absolute;cursor:pointer;inset:0;background:#30363d;border-radius:24px;transition:.3s}
.toggle .slider::before{position:absolute;content:'';height:18px;width:18px;left:3px;bottom:3px;background:var(--fg);border-radius:50%;transition:.3s}
.toggle input:checked+.slider{background:var(--ok)}
.toggle input:checked+.slider::before{transform:translateX(20px)}
/* Key cards */
.key-card{display:flex;align-items:center;gap:12px;padding:12px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px;background:var(--input-bg)}
.key-card .key-icon{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:16px;flex-shrink:0}
.key-card .key-info{flex:1;min-width:0}
.key-card .key-name{font-weight:600;font-size:13px}
.key-card .key-status{font-size:11px;color:var(--muted)}
.key-card .key-actions{display:flex;gap:6px;align-items:center}
/* System prompt */
.sys-prompt{width:100%;min-height:200px;background:var(--input-bg);color:var(--fg);border:1px solid var(--border);border-radius:8px;padding:12px;font-family:ui-monospace,monospace;font-size:12px;resize:vertical;line-height:1.5}
/* Tool detail */
.tool-card{border:1px solid var(--border);border-radius:8px;margin-bottom:8px;overflow:hidden}
.tool-card .tool-header{display:flex;align-items:center;gap:12px;padding:12px;background:var(--card);cursor:pointer}
.tool-card .tool-header:hover{background:#1c2129}
.tool-card .tool-name{font-weight:600;font-size:13px;flex:1}
.tool-card .tool-body{display:none;padding:12px;border-top:1px solid var(--border);background:var(--bg)}
.tool-card.open .tool-body{display:block}
.tool-func{margin-bottom:8px;padding:8px;background:var(--card);border-radius:6px}
.tool-func .func-name{color:var(--accent);font-weight:600;font-size:12px}
.tool-func .func-desc{color:var(--muted);font-size:11px;margin-top:2px}
.tool-func .func-params{color:var(--muted);font-size:10px;margin-top:2px}
/* Responsive */
@media(max-width:700px){body{flex-direction:column}aside{width:100%;min-width:100%;flex-direction:row;overflow-x:auto;padding:4px 8px}aside .logo{display:none}aside a{border-left:0;border-bottom:2px solid transparent;white-space:nowrap}aside a.active{border-bottom-color:var(--accent);border-left:0}main section{padding:12px}}
</style>
</head>
<body>
<aside>
  <div class="logo">Bartolo CC</div>
  <a href="#tab-chat" data-tab="chat" class="active">&#x1f4ac; Xat</a>
  <a href="#tab-models" data-tab="models">&#x1f9e0; Models</a>
  <a href="#tab-repos" data-tab="repos">&#x1f4e6; Repos</a>
  <a href="#tab-databases" data-tab="databases">&#x1f5c4; Databases</a>
  <a href="#tab-secrets" data-tab="secrets">&#x1f511; API Keys</a>
  <a href="#tab-tools" data-tab="tools">&#x1f6e0; Eines</a>
  <a href="#tab-shell" data-tab="shell">&#x2328; Shell</a>
  <a href="#tab-launch" data-tab="launch">&#x1f680; Llençar</a>
</aside>
<main>
<!-- CHAT -->
<section id="tab-chat" class="active">
  <div class="chat-layout">
    <!-- Thread sidebar -->
    <div class="thread-sidebar" id="thread-sidebar">
      <div class="ts-header">
        <span>Xats</span>
        <button id="new-thread-btn" title="Xat nou (Ctrl+N)">+</button>
      </div>
      <div class="thread-list" id="thread-list">
        <div class="empty" style="padding:12px">Cap xat</div>
      </div>
      <div class="ts-footer">
        <span id="thread-count">0 fils</span>
        <span id="clear-threads-btn" style="cursor:pointer;color:var(--bad);display:none">netejar</span>
      </div>
    </div>
    <!-- Main chat area -->
    <div class="chat-area">
      <div class="chat-area-header">
        <span class="editable-title" id="chat-title" title="Doble click per reanomenar">Xat nou</span>
        <span style="color:var(--muted);font-size:10px">Model: <span id="chat-model-name">qwen2.5:14b</span> &middot; <span id="chat-status">connectant...</span></span>
      </div>
      <div id="chat-messages"></div>
      <div id="chat-input-area">
        <input type="text" id="chat-input" placeholder="Escriu un missatge... (↑ historial, Enter enviar)">
        <button id="chat-send-btn">Enviar</button>
      </div>
    </div>
  </div>
</section>
<!-- MODELS -->
<section id="tab-models">
  <h1>&#x1f9e0; Models Ollama</h1>
  <div class="sub">Ollama a localhost:11434</div>
  <div class="card" id="models-list"><div class="empty">Carregant...</div></div>
  <div class="card">
    <h2>Descarregar model</h2>
    <div class="row">
      <input type="text" id="model-pull-name" placeholder="ex: llama3.1:8b" style="flex:1">
      <button id="model-pull-btn" class="primary">Descarregar</button>
    </div>
    <div id="model-pull-status"></div>
  </div>
</section>
<!-- REPOS -->
<section id="tab-repos">
  <h1>&#x1f4e6; Repos i Serveis</h1>
  <div class="sub" id="repos-meta">Carregant...</div>
  <div id="repos-content"><div class="empty">Carregant...</div></div>
</section>
<!-- DATABASES -->
<section id="tab-databases">
  <h1>&#x1f5c4; Databases Docker</h1>
  <div class="sub">Containers amb prefix "agent-"</div>
  <div id="db-content"><div class="empty">Carregant...</div></div>
</section>
<!-- SECRETS -->
<section id="tab-secrets">
  <h1>&#x1f511; API Keys</h1>
  <div class="sub">~/.universal-agent/secrets.json</div>
  <div id="secrets-flash"></div>
  <!-- Proveïdors IA -->
  <div class="card">
    <h2>&#x1f9e0; Proveïdors d'IA</h2>
    <div id="ai-keys-list"><div class="empty">Carregant...</div></div>
  </div>
  <!-- Altres claus -->
  <div class="card">
    <h2>&#x1f4a0; Altres claus</h2>
    <div id="other-keys-content"><div class="empty">Carregant...</div></div>
    <div class="row" style="margin-top:12px">
      <input type="text" id="secret-key" placeholder="Nom de la clau" style="flex:1">
      <input type="password" id="secret-val" placeholder="Valor" style="flex:1">
      <button id="secret-save-btn" class="primary">Desar</button>
    </div>
  </div>
</section>
<!-- TOOLS -->
<section id="tab-tools">
  <h1>&#x1f6e0; Eines i Model</h1>
  <div class="sub">Model Bartolo + tools OpenWebUI</div>
  <div id="tools-flash"></div>
  <!-- Model info -->
  <div class="card" id="model-card">
    <h2>&#x1f916; Model: <span id="bartolo-model-name">Bartolo</span></h2>
    <div id="model-info-content"><div class="empty">Carregant...</div></div>
  </div>
  <!-- Params -->
  <div class="card" id="model-params-card">
    <h2>&#x1f4ca; Paràmetres del model</h2>
    <div id="model-params-content"><div class="empty">Carregant...</div></div>
  </div>
  <!-- System prompt -->
  <div class="card">
    <h2>&#x1f4dd; Indicador del sistema</h2>
    <textarea class="sys-prompt" id="system-prompt-text" placeholder="Carregant..."></textarea>
    <div style="margin-top:8px;display:flex;gap:8px;align-items:center">
      <button id="system-prompt-save" class="primary">Desar</button>
      <span style="font-size:11px;color:var(--muted)">Requereix reiniciar OpenWebUI</span>
    </div>
  </div>
  <!-- Tools list -->
  <div class="card">
    <h2>&#x1f527; Eines disponibles</h2>
    <div id="tools-list"><div class="empty">Carregant...</div></div>
  </div>
</section>
<!-- SHELL -->
<section id="tab-shell">
  <h1>&#x2328; Shell Exec</h1>
  <div class="sub">Token de seguretat (caduca 120s)</div>
  <div id="shell-flash"></div>
  <div class="card">
    <div class="row">
      <input type="text" id="shell-cmd" placeholder="docker ps, ollama list, pwd..." style="flex:1">
      <button id="shell-gen-btn" class="primary">Generar Token</button>
    </div>
    <div id="shell-token-area" style="display:none;margin-top:8px">
      <div class="row">
        <input type="text" id="shell-token-confirm" placeholder="Enganxa el token per confirmar" style="flex:1">
        <button id="shell-exec-btn" class="danger">Executar</button>
      </div>
    </div>
    <pre class="logs output" id="shell-output" style="display:none"></pre>
  </div>
</section>
<!-- LAUNCH -->
<section id="tab-launch">
  <h1>&#x1f680; Llençar Repo</h1>
  <div class="sub">Executa l'agent amb --input</div>
  <div id="launch-flash"></div>
  <div class="card">
    <form id="launch-form" class="launch">
      <input type="text" name="input" id="launch-input" placeholder="URL git / carpeta / .zip" required style="flex:1;min-width:280px">
      <label><input type="checkbox" name="dockerize" value="1" id="launch-dockerize"> dockerize</label>
      <label><input type="checkbox" name="approve_all" value="1" checked id="launch-approve"> approve-all</label>
      <label><input type="checkbox" name="no_refine" value="1" checked id="launch-norefine"> sense LLM</label>
      <button type="submit" class="primary">Llençar</button>
    </form>
  </div>
</section>
</main>
<!-- Tool source modal -->
<div class="modal-bg" id="tool-modal"><div class="modal"><h2 id="tool-modal-title"></h2><textarea class="sys-prompt" id="tool-modal-source" style="max-height:65vh;min-height:300px" spellcheck="false"></textarea><div style="margin-top:8px;display:flex;gap:8px"><button class="primary" onclick="saveToolSource()">Desar</button><button onclick="document.getElementById('tool-modal').classList.remove('show')">Tancar</button></div></div></div>
<div id="toast-container"></div>

<script>
const WS_URL = 'ws://' + location.host + '/ws/chat';
const CLIENT_ID = 'dash-' + Math.random().toString(36).slice(2,10);
let ws = null;
let wsReconnectTimer = null;

// ===== NAVIGATION =====
let _intervals = {};
let _lastChanges = {};

function startPolling(tab, fn, fastMs, slowMs) {
  stopPolling(tab);
  _lastChanges[tab] = Date.now();
  _intervals[tab] = setInterval(function() {
    var elapsed = Date.now() - (_lastChanges[tab] || 0);
    var interval = elapsed < 30000 ? (fastMs || 2000) : (slowMs || 15000);
    // Only poll if tab is active
    var sec = document.getElementById('tab-' + tab);
    if (!sec || !sec.classList.contains('active')) return;
    fn();
  }, fastMs || 2000);
}

function stopPolling(tab) {
  if (_intervals[tab]) { clearInterval(_intervals[tab]); _intervals[tab] = null; }
}

function bumpPolling(tab) {
  _lastChanges[tab] = Date.now();
}

let _loadedTabs = {};

function switchTab(t) {
  document.querySelectorAll('main section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('aside a').forEach(a => a.classList.remove('active'));
  const sec = document.getElementById('tab-' + t);
  if (sec) sec.classList.add('active');
  const nav = document.querySelector('aside a[data-tab="' + t + '"]');
  if (nav) nav.classList.add('active');
  location.hash = 'tab-' + t;
  // Lazy load tab data
  if (!_loadedTabs[t]) { _loadedTabs[t] = true; loadTabData(t); }
  // Stop polling for tabs we're leaving
  if (t !== 'repos') stopPolling('repos');
  if (t !== 'databases') stopPolling('databases');
}

function loadTabData(t) {
  if (t === 'models') loadModels();
  if (t === 'repos') { loadStatus(); startPolling('repos', loadStatus, 2000, 15000); }
  if (t === 'databases') { loadDatabases(); startPolling('databases', loadDatabases, 5000, 30000); }
  if (t === 'secrets') loadSecrets();
  if (t === 'tools') loadTools();
}

// ===== WEBSOCKET CHAT =====
let currentMsgEl = null;
let _currentThreadId = null;
let _threads = [];
let _inputHistory = [];
let _historyIdx = -1;
let _savedInput = '';

function connectWS() {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  try {
    ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      document.getElementById('chat-status').innerHTML = '<span class="badge ok">connectat</span>';
      if (_currentThreadId) {
        ws.send(JSON.stringify({type:'set_thread', thread_id:_currentThreadId}));
      }
    };
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === 'token') appendToken(data.token);
      else if (data.type === 'done') finishMessage();
      else if (data.type === 'intent') addChatMessage('system', 'Intent: ' + data.intent);
      else if (data.type === 'error') addChatMessage('system', 'Error: ' + esc(data.error));
      else if (data.type === 'action') {
        if (data.done) addChatMessage('assistant', data.done);
        else addChatMessage('system', 'Executant: ' + esc(data.action));
      }
      else if (data.type === 'history') {
        document.getElementById('chat-messages').innerHTML = '';
        currentMsgEl = null;
        (data.messages||[]).forEach(m => addChatMessage(m.role, m.content));
      }
      else if (data.type === 'thread_created') {
        loadThreads().then(() => selectThread(data.thread.id, true));
      }
    };
    ws.onclose = () => {
      document.getElementById('chat-status').innerHTML = '<span class="badge warn">reconnectant...</span>';
      if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
      wsReconnectTimer = setTimeout(connectWS, 3000);
    };
    ws.onerror = () => ws.close();
  } catch(e) { setTimeout(connectWS, 3000); }
}

function sendChat() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg || !ws || ws.readyState !== WebSocket.OPEN) return;
  addChatMessage('user', msg);
  // Add to input history (deduplicate)
  if (!_inputHistory.length || _inputHistory[_inputHistory.length-1] !== msg) {
    _inputHistory.push(msg);
  }
  _historyIdx = -1;
  _savedInput = '';
  input.value = '';
  currentMsgEl = null;
  ws.send(JSON.stringify({type:'chat', message:msg, thread_id:_currentThreadId}));
  // Refresh thread list after a moment
  setTimeout(loadThreads, 500);
}

function addChatMessage(role, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  el.textContent = text;
  document.getElementById('chat-messages').appendChild(el);
  el.scrollIntoView({behavior:'smooth'});
}
function appendToken(token) {
  if (!currentMsgEl) {
    currentMsgEl = document.createElement('div');
    currentMsgEl.className = 'msg assistant';
    document.getElementById('chat-messages').appendChild(currentMsgEl);
  }
  currentMsgEl.textContent += token;
  currentMsgEl.scrollIntoView({behavior:'smooth'});
}
function finishMessage() { currentMsgEl = null; }

// ===== INPUT HISTORY (arrow up/down) =====
document.getElementById('chat-input').addEventListener('keydown', function(e) {
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (_historyIdx === -1) {
      _savedInput = this.value;
      _historyIdx = _inputHistory.length - 1;
    } else if (_historyIdx > 0) {
      _historyIdx--;
    }
    if (_historyIdx >= 0 && _historyIdx < _inputHistory.length) {
      this.value = _inputHistory[_historyIdx];
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (_historyIdx >= 0 && _historyIdx < _inputHistory.length - 1) {
      _historyIdx++;
      this.value = _inputHistory[_historyIdx];
    } else {
      _historyIdx = -1;
      this.value = _savedInput;
    }
  } else if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
});

document.getElementById('chat-send-btn').addEventListener('click', sendChat);

// ===== THREAD MANAGEMENT =====
async function loadThreads() {
  try {
    const r = await fetch('/api/chat/threads');
    const data = await r.json();
    _threads = data.threads || [];
    renderThreadList();
  } catch(e) {}
}

function renderThreadList() {
  const el = document.getElementById('thread-list');
  if (!_threads.length) {
    el.innerHTML = '<div class="empty" style="padding:12px">Cap xat</div>';
    document.getElementById('thread-count').textContent = '0 fils';
    document.getElementById('clear-threads-btn').style.display = 'none';
    return;
  }
  document.getElementById('thread-count').textContent = _threads.length + ' fils';
  document.getElementById('clear-threads-btn').style.display = 'inline';
  let h = '';
  for (const t of _threads) {
    const active = t.id === _currentThreadId ? ' active' : '';
    const timeAgo = relativeTime(t.updated_at);
    h += '<div class="thread-item'+active+'" data-thread-id="'+escUrl(t.id)+'">';
    h += '<div class="ti-title">'+esc(t.title)+'</div>';
    h += '<div class="ti-meta"><span>'+timeAgo+' &middot; '+t.msg_count+' msgs</span>';
    h += '<span class="ti-del" data-delete-thread="'+escUrl(t.id)+'">&#x1f5d1;</span></div>';
    h += '</div>';
  }
  el.innerHTML = h;
}

function relativeTime(ts) {
  if (!ts) return '';
  const diff = Math.floor(Date.now()/1000) - ts;
  if (diff < 60) return 'fa un moment';
  if (diff < 3600) return Math.floor(diff/60) + ' min';
  if (diff < 86400) return Math.floor(diff/3600) + ' h';
  if (diff < 604800) return Math.floor(diff/86400) + ' dies';
  return new Date(ts*1000).toLocaleDateString('ca');
}

async function selectThread(id, silent) {
  _currentThreadId = id;
  localStorage.setItem('bartolo-thread', id);
  document.getElementById('chat-messages').innerHTML = '';
  currentMsgEl = null;
  // Load messages from server
  try {
    const r = await fetch('/api/chat/threads/' + encodeURIComponent(id));
    const data = await r.json();
    if (data.messages) {
      data.messages.forEach(m => addChatMessage(m.role, m.content));
    }
    if (data.thread) {
      document.getElementById('chat-title').textContent = data.thread.title;
    }
  } catch(e) {}
  renderThreadList();
  if (!silent && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type:'set_thread', thread_id:id}));
  }
  document.getElementById('chat-input').focus();
}

async function createThread() {
  try {
    const r = await fetch('/api/chat/threads', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
    const data = await r.json();
    if (data.ok && data.thread) {
      await loadThreads();
      selectThread(data.thread.id, false);
    }
  } catch(e) {}
}

async function deleteThread(id) {
  if (!confirm('Esborrar aquest fil de conversa?')) return;
  await fetch('/api/chat/threads/' + encodeURIComponent(id), {method:'DELETE'});
  if (_currentThreadId === id) {
    _currentThreadId = null;
    document.getElementById('chat-messages').innerHTML = '';
    document.getElementById('chat-title').textContent = 'Xat nou';
    localStorage.removeItem('bartolo-thread');
  }
  await loadThreads();
}

async function renameThread(id) {
  const title = prompt('Nou nom del fil:', '');
  if (!title) return;
  await fetch('/api/chat/threads/' + encodeURIComponent(id), {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:title})});
  await loadThreads();
  if (_currentThreadId === id) {
    document.getElementById('chat-title').textContent = title;
  }
}

// Thread header double-click to rename
document.getElementById('chat-title').addEventListener('dblclick', function() {
  if (_currentThreadId) renameThread(_currentThreadId);
});

// New thread button
document.getElementById('new-thread-btn').addEventListener('click', createThread);

// Clear all threads
document.getElementById('clear-threads-btn').addEventListener('click', async function() {
  if (!confirm('Esborrar TOTS els fils de conversa?')) return;
  for (const t of _threads) {
    await fetch('/api/chat/threads/' + encodeURIComponent(t.id), {method:'DELETE'});
  }
  _threads = [];
  _currentThreadId = null;
  document.getElementById('chat-messages').innerHTML = '';
  document.getElementById('chat-title').textContent = 'Xat nou';
  localStorage.removeItem('bartolo-thread');
  renderThreadList();
});

// Load input history from server
async function loadInputHistory() {
  try {
    const r = await fetch('/api/chat/history');
    const data = await r.json();
    if (data.history) _inputHistory = data.history;
  } catch(e) {}
}

// ===== MODELS =====
async function loadModels() {
  try {
    const r = await fetch('/api/models');
    const data = await r.json();
    renderModels(data);
  } catch(e) { document.getElementById('models-list').innerHTML = '<div class="empty">Error</div>'; }
}
function renderModels(data) {
  if (!data.models || !data.models.length) {
    document.getElementById('models-list').innerHTML = '<div class="empty">Cap model trobat</div>';
    return;
  }
  let h = '<table><thead><tr><th>Model</th><th>Mida</th><th>Tool Calling</th><th></th></tr></thead><tbody>';
  for (const m of data.models) {
    const tc = m.tool_calling ? '<span class="badge ok">compatible</span>' : (m.tool_calling === false ? '<span class="badge bad">no compatible</span>' : '<span class="badge info">desconegut</span>');
    h += '<tr><td><div class="model-name">' + esc(m.name) + '</div></td><td>' + esc(m.size || '-') + '</td><td>' + tc + '</td>' +
      '<td><button class="small primary" data-select-model="' + escUrl(m.name) + '">Seleccionar</button></td></tr>';
  }
  h += '</tbody></table>';
  document.getElementById('models-list').innerHTML = h;
}
function selectModel(name) {
  document.getElementById('chat-model-name').textContent = name;
  addChatMessage('system', 'Model canviat a: ' + name);
}
document.getElementById('model-pull-btn').addEventListener('click', async () => {
  const name = document.getElementById('model-pull-name').value.trim();
  if (!name) return;
  const stat = document.getElementById('model-pull-status');
  stat.innerHTML = '<span class="spinner"></span> Descarregant ' + esc(name) + '...';
  const r = await fetch('/api/models/pull', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:name})});
  const data = await r.json();
  stat.innerHTML = data.ok ? '<span class="badge ok">OK</span> ' + esc(data.message) : '<span class="badge bad">Error</span> ' + esc(data.message);
  if (data.ok) setTimeout(loadModels, 2000);
});

// ===== REPOS =====
async function loadStatus() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    renderRepos(data);
  } catch(e) { document.getElementById('repos-content').innerHTML = '<div class="empty">Error</div>'; }
}
function renderRepos(data) {
  const repos = Object.entries(data).filter(([k]) => !k.startsWith('_'));
  document.getElementById('repos-meta').textContent = repos.length + ' repos';
  if (!repos.length) {
    document.getElementById('repos-content').innerHTML = '<div class="empty">Cap repo arrencat</div>';
    return;
  }
  let h = '';
  for (const [repo, svcs] of repos) {
    if (!svcs||!svcs.length) continue;
    let sh = '';
    for (const s of svcs) {
      const alive = !!s.pid;
      sh += '<div class="svc '+(alive?'run':'stop')+'"><div class="svc-info"><strong>'+(alive?'&#x1f7e2; RUNNING':'&#x1f534; STOPPED')+' &middot; PID '+(s.pid||'?')+'</strong> &middot; step: <code>'+esc(s.step_id||'')+'</code><code>'+esc(s.command||'')+'</code></div>'+
        '<div class="actions"><button class="small" data-view-logs="'+escUrl(repo)+'/'+escUrl(s.step_id||'')+'">Logs</button>'+
        '<button class="small danger" data-stop-repo="'+escUrl(repo)+'">Stop</button></div></div>';
    }
    h += '<div class="card"><h2>'+esc(repo)+'</h2>'+sh+'</div>';
  }
  document.getElementById('repos-content').innerHTML = h || '<div class="empty">Cap servei</div>';
}
async function stopRepo(name) {
  await fetch('/api/stop', {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'repo='+encodeURIComponent(name)});
  loadStatus();
}

// ===== DATABASES =====
async function loadDatabases() {
  try {
    const r = await fetch('/api/databases');
    const data = await r.json();
    renderDatabases(data);
  } catch(e) { document.getElementById('db-content').innerHTML = '<div class="empty">Error</div>'; }
}
function renderDatabases(data) {
  if (!data.containers || !data.containers.length) {
    document.getElementById('db-content').innerHTML = '<div class="empty">Cap container Docker actiu</div>';
    return;
  }
  let h = '<table><thead><tr><th>Nom</th><th>Imatge</th><th>Ports</th><th>Connexió</th></tr></thead><tbody>';
  for (const db of data.containers) {
    h += '<tr><td><strong>'+esc(db.name)+'</strong><br><span class="badge ok">'+esc(db.status||'')+'</span></td><td>'+esc(db.image||'')+'</td><td>'+esc(db.ports||'')+'</td><td style="color:var(--accent)">'+esc(db.connect_url||'')+'</td></tr>';
  }
  h += '</tbody></table>';
  document.getElementById('db-content').innerHTML = h;
}

// ===== SECRETS =====
async function loadSecrets() {
  try {
    const r = await fetch('/api/secrets');
    const data = await r.json();
    renderAiKeys(data.secrets || {}, data.known_key_types || []);
    renderOtherKeys(data.secrets || {});
  } catch(e) { document.getElementById('ai-keys-list').innerHTML = '<div class="empty">Error</div>'; }
}

function renderAiKeys(secrets, knownTypes) {
  const providers = [
    {key: 'ANTHROPIC_API_KEY', name: 'Anthropic', icon: 'A', color: '#d4a574', provider: 'anthropic'},
    {key: 'DEEPSEEK_API_KEY', name: 'DeepSeek', icon: 'D', color: '#4a9eff', provider: 'deepseek'},
    {key: 'OPENAI_API_KEY', name: 'OpenAI', icon: 'O', color: '#74aa9c', provider: 'openai'},
  ];
  let h = '';
  for (const p of providers) {
    const s = secrets[p.key] || null;
    const configured = !!s && s.value === '••••••••';
    const active = configured && s.active !== false;
    const statusCls = configured ? (active ? 'ok' : 'warn') : 'bad';
    const statusText = configured ? (active ? 'activa' : 'desactivada') : 'no configurada';
    h += '<div class="key-card">';
    h += '<div class="key-icon" style="background:'+p.color+'22;color:'+p.color+'">'+p.icon+'</div>';
    h += '<div class="key-info"><div class="key-name">'+p.name+'</div><div class="key-status"><span class="badge '+statusCls+'">'+statusText+'</span> &middot; <code>'+p.key+'</code></div></div>';
    h += '<div class="key-actions">';
    if (configured) {
      h += '<label class="toggle"><input type="checkbox" '+(active?'checked':'')+' data-toggle-secret="'+p.key+'" onchange="toggleSecret(\''+p.key+'\')"><span class="slider"></span></label>';
      h += '<button class="small" data-edit-secret="'+p.key+'">Editar</button>';
    } else {
      h += '<button class="small primary" data-edit-secret="'+p.key+'">Configurar</button>';
    }
    if (configured) {
      h += '<button class="small" data-test-secret="'+p.provider+'">Test</button>';
      h += '<button class="small danger" data-delete-secret="'+p.key+'">Eliminar</button>';
    }
    h += '</div></div>';
    // Inline edit form (hidden)
    h += '<div id="edit-'+p.key+'" style="display:none;padding:8px;margin-top:-4px;margin-bottom:8px;background:var(--card);border-radius:4px">';
    h += '<div class="row"><input type="password" id="edit-val-'+p.key+'" placeholder="Nou valor per '+p.key+'" style="flex:1">';
    h += '<button class="small primary" data-save-secret="'+p.key+'">Desar</button>';
    h += '<button class="small" data-cancel-edit="'+p.key+'">Cancel·lar</button></div></div>';
  }
  document.getElementById('ai-keys-list').innerHTML = h;
}

function renderOtherKeys(secrets) {
  const otherKeys = {};
  for (const [k, v] of Object.entries(secrets)) {
    if (!['ANTHROPIC_API_KEY','DEEPSEEK_API_KEY','OPENAI_API_KEY'].includes(k)) {
      otherKeys[k] = v;
    }
  }
  const el = document.getElementById('other-keys-content');
  if (!Object.keys(otherKeys).length) {
    el.innerHTML = '<div class="empty">Cap altra clau</div>';
    return;
  }
  let h = '<table><thead><tr><th>Clau</th><th>Valor</th><th></th></tr></thead><tbody>';
  for (const [k, v] of Object.entries(otherKeys)) {
    h += '<tr><td style="color:var(--accent);font-weight:600">'+esc(k)+'</td><td>'+esc(String(v.value||'••••••••'))+'</td>'+
      '<td><button class="small danger" data-delete-secret="'+escUrl(k)+'">Eliminar</button></td></tr>';
  }
  h += '</tbody></table>';
  el.innerHTML = h;
}

function toggleSecret(key) {
  fetch('/api/secrets/' + encodeURIComponent(key) + '/toggle', {method:'POST'})
    .then(() => loadSecrets());
}

async function testSecret(provider) {
  const r = await fetch('/api/secrets/test/' + provider, {method:'POST'});
  const d = await r.json();
  document.getElementById('secrets-flash').innerHTML = d.ok
    ? '<div class="flash ok">'+esc(d.message)+'</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
}

async function saveSecret(key) {
  const v = document.getElementById('edit-val-'+key).value.trim();
  if (!v) return;
  const r = await fetch('/api/secrets/' + encodeURIComponent(key), {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:v})});
  const d = await r.json();
  document.getElementById('secrets-flash').innerHTML = d.ok
    ? '<div class="flash ok">Clau desada</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
  loadSecrets();
}

async function deleteSecret(key) {
  await fetch('/api/secrets/' + encodeURIComponent(key), {method:'DELETE'});
  loadSecrets();
}

document.getElementById('secret-save-btn').addEventListener('click', async () => {
  const k = document.getElementById('secret-key').value.trim();
  const v = document.getElementById('secret-val').value.trim();
  if (!k || !v) return;
  const r = await fetch('/api/secrets/' + encodeURIComponent(k), {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:v})});
  const d = await r.json();
  document.getElementById('secrets-flash').innerHTML = d.ok
    ? '<div class="flash ok">Clau desada</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
  document.getElementById('secret-key').value = '';
  document.getElementById('secret-val').value = '';
  loadSecrets();
});

// ===== TOOLS =====
async function loadTools() {
  try {
    const [toolsR, modelR] = await Promise.all([
      fetch('/api/tools'),
      fetch('/api/model/bartolo')
    ]);
    const toolsData = await toolsR.json();
    const modelData = await modelR.json();
    renderModelInfo(modelData);
    renderModelParams(modelData);
    renderToolList(toolsData.tools || [], toolsData.active_tool_ids || []);
    // System prompt
    const sp = document.getElementById('system-prompt-text');
    if (sp && modelData.system_prompt) sp.value = modelData.system_prompt;
  } catch(e) {
    document.getElementById('tools-list').innerHTML = '<div class="empty">Error carregant</div>';
  }
}

function renderModelInfo(data) {
  const caps = data.capabilities || {};
  const capNames = Object.entries(caps).filter(([,v]) => v).map(([k]) => k.replace(/_/g,' '));
  document.getElementById('bartolo-model-name').textContent = data.name || 'Bartolo';
  document.getElementById('model-info-content').innerHTML =
    '<table><tbody>' +
    '<tr><td>Model base</td><td style="color:var(--accent)">'+esc(data.base_model_id||'?')+'</td></tr>' +
    '<tr><td>Actiu</td><td>'+(data.is_active?'<span class="badge ok">sí</span>':'<span class="badge bad">no</span>')+'</td></tr>' +
    '<tr><td>Capacitats</td><td>'+esc(capNames.join(', ')||'cap')+'</td></tr>' +
    '<tr><td>Eines assignades</td><td>'+esc(String((data.tool_ids||[]).length))+'</td></tr>' +
    '</tbody></table>';
}

function renderModelParams(data) {
  const params = data.params || {};
  let h = '<table><tbody>';
  for (const [k, v] of Object.entries(params)) {
    if (k === 'system') continue;
    h += '<tr><td style="color:var(--muted)">'+esc(k)+'</td><td>'+esc(String(v))+'</td></tr>';
  }
  h += '</tbody></table>';
  if (!Object.keys(params).length) h = '<div class="empty">Paràmetres per defecte</div>';
  document.getElementById('model-params-content').innerHTML = h;
}

function renderToolList(tools, activeIds) {
  if (!tools || !tools.length) {
    document.getElementById('tools-list').innerHTML = '<div class="empty">Cap eina trobada</div>';
    return;
  }
  let h = '';
  for (const t of tools) {
    const active = activeIds.includes(t.id);
    h += '<div class="tool-card'+(t._open?' open':'')+'" id="tool-card-'+escUrl(t.id)+'">';
    h += '<div class="tool-header" data-tool-toggle="'+escUrl(t.id)+'">';
    h += '<div class="tool-name">'+esc(t.name)+'</div>';
    h += '<span class="badge '+(active?'ok':'bad')+'">'+(active?'activa':'inactiva')+'</span>';
    h += '<span style="font-size:11px;color:var(--muted)">'+t.function_count+' funcions</span>';
    h += '</div>';
    h += '<div class="tool-body">';
    h += '<div style="margin-bottom:8px;display:flex;gap:8px">';
    h += '<button class="small primary" data-view-tool="'+escUrl(t.id)+','+escUrl(t.name)+'">Veure codi</button>';
    h += '<button class="small '+(active?'danger':'ok')+'" data-tool-toggle-btn="'+escUrl(t.id)+'">'+(active?'Desactivar':'Activar')+'</button>';
    h += '</div>';
    // Functions from specs
    if (t.functions && t.functions.length) {
      h += '<div style="font-size:11px;color:var(--muted);margin-bottom:4px">Funcions:</div>';
      for (const f of t.functions) {
        h += '<div class="tool-func"><div class="func-name">'+esc(f.name)+'()</div>';
        h += '<div class="func-desc">'+esc(f.description||'')+'</div>';
        if (f.parameters && f.parameters.length) {
          h += '<div class="func-params">Params: '+esc(f.parameters.join(', '))+'</div>';
        }
        h += '</div>';
      }
    }
    h += '</div></div>';
  }
  document.getElementById('tools-list').innerHTML = h;
}

function toggleToolCard(id) {
  const card = document.getElementById('tool-card-'+id);
  if (card) card.classList.toggle('open');
}

async function toggleTool(id) {
  const r = await fetch('/api/tools/' + encodeURIComponent(id) + '/toggle', {method:'POST'});
  const d = await r.json();
  document.getElementById('tools-flash').innerHTML = d.ok
    ? '<div class="flash ok">Tool '+esc(id)+' '+esc(d.status)+'. Reinicia OpenWebUI.</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
  if (d.ok) loadTools();
}

async function viewToolSource(id, name) {
  const r = await fetch('/api/tools/' + encodeURIComponent(id) + '/source');
  const data = await r.json();
  document.getElementById('tool-modal-title').textContent = name || data.name || '';
  document.getElementById('tool-modal-source').value = data.source || '(no disponible)';
  // Store tool id for save
  document.getElementById('tool-modal').setAttribute('data-tool-id', id);
  document.getElementById('tool-modal').classList.add('show');
}

async function saveToolSource() {
  const id = document.getElementById('tool-modal').getAttribute('data-tool-id');
  const source = document.getElementById('tool-modal-source').value;
  if (!id || !source) return;
  const r = await fetch('/api/tools/' + encodeURIComponent(id) + '/source', {
    method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source:source})
  });
  const d = await r.json();
  document.getElementById('tools-flash').innerHTML = d.ok
    ? '<div class="flash ok">'+esc(d.message)+'</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
}

document.getElementById('system-prompt-save').addEventListener('click', async () => {
  const sp = document.getElementById('system-prompt-text').value;
  const r = await fetch('/api/model/bartolo', {
    method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({system_prompt:sp})
  });
  const d = await r.json();
  document.getElementById('tools-flash').innerHTML = d.ok
    ? '<div class="flash ok">'+esc(d.message)+'</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
});

// ===== SHELL =====
document.getElementById('shell-gen-btn').addEventListener('click', async () => {
  const cmd = document.getElementById('shell-cmd').value.trim();
  if (!cmd) return;
  const r = await fetch('/api/exec', {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'cmd='+encodeURIComponent(cmd)});
  const data = await r.json();
  if (data.token) {
    document.getElementById('shell-token-area').style.display = 'block';
    document.getElementById('shell-output').style.display = 'none';
    document.getElementById('shell-flash').innerHTML = '<div class="flash info">Token generat. Enganxa\'l per confirmar.</div>';
  } else {
    document.getElementById('shell-flash').innerHTML = '<div class="flash error">'+esc(data.error||'Error')+'</div>';
  }
});
document.getElementById('shell-exec-btn').addEventListener('click', async () => {
  const token = document.getElementById('shell-token-confirm').value.trim();
  const cmd = document.getElementById('shell-cmd').value.trim();
  if (!token||!cmd) return;
  const r = await fetch('/api/exec/confirm', {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'token='+encodeURIComponent(token)+'&cmd='+encodeURIComponent(cmd)});
  const data = await r.json();
  const out = document.getElementById('shell-output');
  out.style.display = 'block';
  out.textContent = data.output || data.error || '';
  document.getElementById('shell-token-area').style.display = 'none';
});

// ===== LAUNCH =====
document.getElementById('launch-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const params = new URLSearchParams(fd);
  const r = await fetch('/api/launch', {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:params});
  if (r.ok) {
    document.getElementById('launch-flash').innerHTML = '<div class="flash ok">Repo llençat! Mira la pestanya Repos.</div>';
    switchTab('repos'); localStorage.setItem('bartolo-tab','repos');
    setTimeout(loadStatus, 3000);
  } else {
    document.getElementById('launch-flash').innerHTML = '<div class="flash error">Error al llençar</div>';
  }
});

// ===== TOAST NOTIFICATIONS =====
let _toastQueue = [];
function showToast(msg, type) {
  type = type || 'info';
  _toastQueue.push({msg:msg, type:type});
  if (_toastQueue.length > 3) _toastQueue.shift();
  renderToasts();
  setTimeout(function() {
    _toastQueue = _toastQueue.filter(function(t) { return t.msg !== msg; });
    renderToasts();
  }, 5000);
}
function renderToasts() {
  var container = document.getElementById('toast-container');
  var h = '';
  for (var i = 0; i < _toastQueue.length; i++) {
    var t = _toastQueue[i];
    h += '<div class="toast '+t.type+'"><span>'+esc(t.msg)+'</span><span class="toast-close" onclick="this.parentElement.remove()">x</span></div>';
  }
  container.innerHTML = h;
}

// ===== UTILS =====
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function escUrl(s) { return encodeURIComponent(s); }

// ===== DELEGATED CLICK HANDLERS =====
document.addEventListener('click', function(e) {
  // Thread click
  const threadEl = e.target.closest('[data-thread-id]');
  if (threadEl && !e.target.closest('[data-delete-thread]')) {
    selectThread(decodeURIComponent(threadEl.getAttribute('data-thread-id')), false);
    return;
  }
  // Thread delete
  const delThreadEl = e.target.closest('[data-delete-thread]');
  if (delThreadEl) {
    deleteThread(decodeURIComponent(delThreadEl.getAttribute('data-delete-thread')));
    return;
  }
  // Models
  const el = e.target.closest('[data-select-model]');
  if (el) {
    const name = decodeURIComponent(el.getAttribute('data-select-model'));
    document.getElementById('chat-model-name').textContent = name;
    addChatMessage('system', 'Model canviat a: ' + name);
    return;
  }
  // Repos
  const stopEl = e.target.closest('[data-stop-repo]');
  if (stopEl) {
    stopRepo(decodeURIComponent(stopEl.getAttribute('data-stop-repo')));
    return;
  }
  const logEl = e.target.closest('[data-view-logs]');
  if (logEl) {
    const parts = logEl.getAttribute('data-view-logs').split('/');
    const repo = decodeURIComponent(parts[0]);
    const step = decodeURIComponent(parts.slice(1).join('/'));
    window.open('/api/logs?repo=' + encodeURIComponent(repo) + '&step=' + encodeURIComponent(step));
    return;
  }
  // Secrets - toggle
  const toggleEl = e.target.closest('[data-toggle-secret]');
  if (toggleEl) {
    toggleSecret(decodeURIComponent(toggleEl.getAttribute('data-toggle-secret')));
    return;
  }
  // Secrets - delete
  const delEl = e.target.closest('[data-delete-secret]');
  if (delEl) {
    deleteSecret(decodeURIComponent(delEl.getAttribute('data-delete-secret')));
    return;
  }
  // Secrets - edit
  const editEl = e.target.closest('[data-edit-secret]');
  if (editEl) {
    const key = editEl.getAttribute('data-edit-secret');
    const editDiv = document.getElementById('edit-'+key);
    if (editDiv) editDiv.style.display = editDiv.style.display === 'none' ? 'block' : 'none';
    return;
  }
  // Secrets - save
  const saveEl = e.target.closest('[data-save-secret]');
  if (saveEl) {
    saveSecret(saveEl.getAttribute('data-save-secret'));
    return;
  }
  // Secrets - cancel edit
  const cancelEl = e.target.closest('[data-cancel-edit]');
  if (cancelEl) {
    document.getElementById('edit-'+cancelEl.getAttribute('data-cancel-edit')).style.display = 'none';
    return;
  }
  // Secrets - test
  const testEl = e.target.closest('[data-test-secret]');
  if (testEl) {
    testSecret(testEl.getAttribute('data-test-secret'));
    return;
  }
  // Tools - view source
  const toolEl = e.target.closest('[data-view-tool]');
  if (toolEl) {
    const parts = toolEl.getAttribute('data-view-tool').split(',');
    viewToolSource(decodeURIComponent(parts[0]), decodeURIComponent(parts[1] || ''));
    return;
  }
  // Tools - toggle activation
  const toolToggleEl = e.target.closest('[data-tool-toggle-btn]');
  if (toolToggleEl) {
    toggleTool(decodeURIComponent(toolToggleEl.getAttribute('data-tool-toggle-btn')));
    return;
  }
  // Tools - expand/collapse card
  const toolCardEl = e.target.closest('[data-tool-toggle]');
  if (toolCardEl) {
    toggleToolCard(decodeURIComponent(toolCardEl.getAttribute('data-tool-toggle')));
    return;
  }
});

// ===== INIT =====
document.getElementById('chat-status').innerHTML = '<span class="badge ok">connectant...</span>';

// Sidebar tab navigation
document.querySelectorAll('aside a[data-tab]').forEach(function(a) {
  a.addEventListener('click', function(e) {
    e.preventDefault();
    var t = this.getAttribute('data-tab');
    switchTab(t);
    localStorage.setItem('bartolo-tab', t);
  });
});

// WebSocket chat
connectWS();

// Load threads and history
loadThreads();
loadInputHistory();

// Init: activate stored tab and load its data
const activeTab = localStorage.getItem('bartolo-tab') || 'chat';
switchTab(activeTab);

// Restore last thread
const lastThread = localStorage.getItem('bartolo-thread');
if (lastThread) {
  _currentThreadId = lastThread;
  setTimeout(function() {
    selectThread(lastThread, true);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type:'set_thread', thread_id:lastThread}));
    }
  }, 300);
}

// Global keyboard shortcuts
document.addEventListener('keydown', function(e) {
  if (e.ctrlKey && e.key === 'n') {
    e.preventDefault();
    createThread();
  }
  if (e.ctrlKey && e.key === 'w') {
    e.preventDefault();
    if (_currentThreadId) deleteThread(_currentThreadId);
  }
});

</script>
</body>
</html>
"""


def render_index() -> str:
    return INDEX_HTML


def render_logs(repo: str, step: str, workspace) -> str:
    import html
    log_dir = workspace / ".agent_logs"
    content_parts = []
    for f in sorted(log_dir.glob(f"*{step}*.log")):
        content_parts.append(f"=== {f.name} ===\n" + f.read_text(encoding="utf-8", errors="ignore")[-8000:])
    repo_dir = workspace / repo
    for sub in ("backend", "frontend", ""):
        candidate = (repo_dir / sub / ".agent_last_run.log") if sub else (repo_dir / ".agent_last_run.log")
        if candidate.exists():
            content_parts.append(f"=== {candidate.relative_to(workspace)} ===\n" + candidate.read_text(encoding="utf-8", errors="ignore")[-8000:])
    content = "\n\n".join(content_parts) or "(sense logs)"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Logs {repo}/{step}</title>
<style>body{{background:#0d1117;color:#c9d1d9;font-family:ui-monospace,monospace;margin:0;padding:24px}}
a{{color:#58a6ff}}pre{{background:#010409;padding:12px;border-radius:4px;white-space:pre-wrap;word-break:break-all;font-size:11px;color:#8b949e;max-height:85vh;overflow:auto}}</style></head>
<body><a href="/">← Tornar</a> · <strong>{html.escape(repo)}/{html.escape(step)}</strong><pre>{html.escape(content)}</pre></body></html>"""
