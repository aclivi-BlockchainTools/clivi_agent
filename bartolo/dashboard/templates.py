"""bartolo/dashboard/templates.py — HTML+CSS+JS inline per Dashboard v2."""

_CSS = """\
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');
:root{
  --bg:#09090b;--surface:#111115;--card:#16161b;--fg:#e0e0e0;--muted:#6b6b78;
  --ok:#a6e22e;--bad:#f92672;--warn:#e6c547;
  --accent:#a6e22e;--accent2:#e6c547;--accent-glow:rgba(166,226,46,.15);
  --border:#1e1e24;--border-light:#2a2a35;--input-bg:#0d0d10;
  --font-body:'JetBrains Mono',monospace;--font-display:'JetBrains Mono',monospace;
  --glow-green:0 0 14px rgba(166,226,46,.18);--glow-amber:0 0 14px rgba(230,197,71,.12);
}
*{box-sizing:border-box}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border-light);border-radius:0}
::-webkit-scrollbar-thumb:hover{background:var(--muted)}
::-webkit-scrollbar-corner{background:var(--bg)}

body{
  background:var(--bg);color:var(--fg);font-family:var(--font-body);font-size:13px;
  margin:0;padding:0;display:flex;flex-direction:column;height:100vh;overflow:hidden;
  font-feature-settings:'calt' 1,'liga' 1;
}
/* Grid background */
body::before{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background-image:
    linear-gradient(rgba(255,255,255,.012) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,.012) 1px,transparent 1px);
  background-size:32px 32px;
  mask-image:radial-gradient(ellipse at 50% 0%,#000 60%,transparent 100%);
}

/* ===== TOP NAV BAR ===== */
nav{display:flex;align-items:center;gap:0;height:44px;min-height:44px;background:var(--surface);border-bottom:1px solid var(--border);position:relative;z-index:10;padding:0 8px}
nav .logo{
  font-family:var(--font-body);font-size:13px;font-weight:700;color:var(--accent);
  padding:0 16px;letter-spacing:0;display:flex;align-items:center;gap:8px;
  white-space:nowrap;user-select:none;
}
nav .logo .cursor{display:inline-block;width:8px;height:15px;background:var(--accent);animation:blink 1s step-end infinite;vertical-align:middle;margin-left:2px}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
nav .nav-links{display:flex;align-items:center;gap:0;flex:1;overflow-x:auto;height:100%}
nav a{
  color:var(--muted);text-decoration:none;padding:0 14px;font-size:10px;font-weight:500;
  display:flex;align-items:center;gap:6px;height:100%;transition:all .15s ease;
  border-bottom:2px solid transparent;white-space:nowrap;cursor:pointer;
  letter-spacing:.3px;text-transform:uppercase;
}
nav a:hover{color:var(--fg);background:rgba(166,226,46,.03)}
nav a.active{color:var(--accent);border-bottom-color:var(--accent);background:rgba(166,226,46,.04)}
nav .nav-status{display:flex;align-items:center;gap:8px;padding:0 14px;font-size:10px;color:var(--muted)}
nav .nav-dot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 6px var(--accent);animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
/* Keyboard help */
.kb-help-btn{width:20px;height:20px;border-radius:50%;border:1px solid var(--border-light);background:transparent;color:var(--muted);font-size:11px;font-weight:600;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;transition:all .15s;margin-left:6px}
.kb-help-btn:hover{color:var(--accent);border-color:var(--accent)}
.kb-panel{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);z-index:150;display:none;animation:fadeSlide .2s ease}
.kb-panel.show{display:block}
.kb-panel-inner{display:flex;align-items:center;gap:0;background:var(--card);border:1px solid var(--border-light);border-radius:4px;padding:6px 4px;box-shadow:0 4px 20px rgba(0,0,0,.5);white-space:nowrap}
.kb-item{display:flex;align-items:center;gap:6px;padding:4px 10px;font-size:9px;color:var(--muted);white-space:nowrap}
.kb-item kbd{display:inline-block;padding:1px 5px;background:var(--input-bg);border:1px solid var(--border);border-radius:2px;font-family:var(--font-body);font-size:8px;color:var(--accent);letter-spacing:.3px}
.kb-sep{width:1px;height:14px;background:var(--border)}
.kb-close{background:transparent;border:0;color:var(--muted);cursor:pointer;font-size:15px;padding:0 6px;line-height:1;transition:color .12s}
.kb-close:hover{color:var(--bad)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}

/* ===== MAIN CONTENT ===== */
main{flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative;z-index:1}
main section{display:none;flex:1;overflow-y:auto;padding:32px;animation:fadeSlide .2s ease}
main section.active,main section:target{display:flex;flex-direction:column}
@keyframes fadeSlide{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}

h1{font-family:var(--font-body);color:var(--accent);margin:0 0 4px;font-size:13px;font-weight:600;letter-spacing:0;text-transform:uppercase}
.sub{color:var(--muted);margin-bottom:28px;font-size:10px;font-family:var(--font-body);letter-spacing:.2px}

/* ===== CARDS ===== */
.card{
  background:var(--card);border:1px solid var(--border);border-radius:2px;padding:20px;
  margin-bottom:12px;transition:border-color .2s;
}
.card:hover{border-color:var(--border-light)}
.card h2{margin:0 0 12px;font-family:var(--font-body);font-size:11px;color:var(--accent);font-weight:500;letter-spacing:.5px;text-transform:uppercase}

/* ===== CHAT LAYOUT ===== */
.chat-layout{display:flex;flex:1;overflow:hidden;gap:0}
/* Thread sidebar */
.thread-sidebar{width:230px;min-width:230px;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.thread-sidebar .ts-header{display:flex;justify-content:space-between;align-items:center;padding:14px 14px 10px;border-bottom:1px solid var(--border)}
.thread-sidebar .ts-header span{font-weight:600;font-size:10px;font-family:var(--font-body);color:var(--accent);text-transform:uppercase;letter-spacing:.6px}
.thread-sidebar .ts-header button{background:var(--accent);color:#09090b;border:0;width:24px;height:24px;border-radius:1px;font-size:15px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-weight:700;transition:background .15s}
.thread-sidebar .ts-header button:hover{background:#b8f536}
.thread-list{flex:1;overflow-y:auto;padding:2px 0}
.thread-item{padding:10px 14px;cursor:pointer;border-left:2px solid transparent;transition:all .12s ease}
.thread-item:hover{background:rgba(166,226,46,.03)}
.thread-item.active{background:rgba(166,226,46,.05);border-left-color:var(--accent)}
.thread-item .ti-title{font-size:10px;color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:500}
.thread-item .ti-meta{font-size:9px;color:var(--muted);margin-top:3px;display:flex;justify-content:space-between}
.thread-item .ti-del{display:none;color:var(--bad);font-size:10px;cursor:pointer}
.thread-item:hover .ti-del{display:inline}
.ts-footer{border-top:1px solid var(--border);padding:8px 14px;font-size:9px;color:var(--muted);display:flex;justify-content:space-between}
/* Chat area */
.chat-area{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0;position:relative}
.chat-area-header{padding:12px 20px;border-bottom:1px solid var(--border);font-size:11px;font-weight:500;display:flex;justify-content:space-between;align-items:center}
.chat-area-header .editable-title{cursor:pointer;border-bottom:1px dashed transparent}
.chat-area-header .editable-title:hover{border-bottom-color:var(--muted)}

/* ===== TOASTS ===== */
#toast-container{position:fixed;bottom:20px;right:20px;z-index:200;display:flex;flex-direction:column;gap:8px;max-width:360px}
.toast{
  background:var(--card);border:1px solid var(--border-light);border-radius:2px;padding:12px 16px;
  font-size:11px;animation:slideIn .25s cubic-bezier(.16,1,.3,1);display:flex;align-items:center;
  gap:10px;box-shadow:0 8px 24px rgba(0,0,0,.6);
}
.toast.ok{border-left:3px solid var(--ok)}
.toast.bad{border-left:3px solid var(--bad)}
.toast.info{border-left:3px solid var(--accent)}
.toast .toast-close{margin-left:auto;cursor:pointer;color:var(--muted);font-size:15px;font-weight:700}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}

/* ===== CHAT MESSAGES ===== */
#chat-messages{flex:1;overflow-y:auto;padding:16px 20px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:78%;padding:10px 14px;border-radius:2px;font-size:11px;line-height:1.6;word-break:break-word}
.msg.user{
  align-self:flex-end;background:rgba(166,226,46,.06);color:var(--fg);
  border:1px solid rgba(166,226,46,.12);border-right:2px solid var(--accent);
}
.msg.assistant{
  align-self:flex-start;background:var(--card);border:1px solid var(--border);
  border-left:2px solid var(--accent2);
}
.msg.system{align-self:center;background:transparent;color:var(--muted);font-size:9px;font-style:italic;max-width:100%}
.msg-time{display:block;font-size:8px;color:var(--muted);margin-top:4px;opacity:.6;letter-spacing:.2px}
.msg.system .msg-time{display:none}
.msg .token{color:var(--fg)}
#chat-input-area{display:flex;gap:10px;padding:14px 20px;border-top:1px solid var(--border)}
#chat-input-area textarea{
  flex:1;background:var(--input-bg);border:1px solid var(--border);color:var(--fg);
  padding:10px 14px;border-radius:2px;font-family:inherit;font-size:11px;resize:none;
  min-height:39px;max-height:120px;line-height:1.5;transition:border-color .15s,box-shadow .15s;
}
#chat-input-area textarea:focus{outline:0;border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
#chat-input-area button{
  background:var(--accent);color:#09090b;border:0;padding:9px 22px;border-radius:2px;
  font-weight:600;cursor:pointer;font-family:inherit;font-size:11px;transition:all .15s;
  letter-spacing:.5px;text-transform:uppercase;
}
#chat-input-area button:hover{background:#b8f536;box-shadow:var(--glow-green)}
/* Copy button on messages */
.msg-copy{position:absolute;top:4px;right:4px;width:22px;height:22px;display:none;align-items:center;justify-content:center;background:var(--surface);border:1px solid var(--border);border-radius:2px;cursor:pointer;font-size:10px;color:var(--muted);transition:all .12s;z-index:2}
.msg-copy:hover{color:var(--accent);border-color:var(--accent)}
.msg{position:relative;padding-right:30px !important}
.msg:hover .msg-copy{display:flex}
.msg-no-copy .msg-copy,.msg.system .msg-copy{display:none !important}
/* Markdown rendering */
.md-code{background:var(--input-bg);border:1px solid var(--border);border-radius:2px;padding:10px 14px;overflow-x:auto;font-family:var(--font-body);font-size:9px;line-height:1.5;margin:6px 0;white-space:pre;color:var(--fg)}
.md-code code{background:transparent;padding:0;font-size:inherit;color:inherit}
.md-inline{background:var(--input-bg);padding:1px 5px;border-radius:2px;font-family:var(--font-body);font-size:9px;color:var(--accent2)}
.msg a{color:var(--accent);text-decoration:underline;text-underline-offset:2px}
.msg a:hover{color:#b8f536}
.msg strong{color:var(--fg);font-weight:600}
.msg em{color:var(--accent2);font-style:italic}
/* Scroll-to-bottom button */
#scroll-bottom-btn{position:absolute;bottom:80px;right:28px;width:32px;height:32px;display:none;align-items:center;justify-content:center;background:var(--card);border:1px solid var(--border-light);border-radius:2px;cursor:pointer;font-size:14px;color:var(--accent);z-index:5;transition:all .12s;box-shadow:0 2px 8px rgba(0,0,0,.4)}
#scroll-bottom-btn:hover{background:var(--accent);color:#09090b;border-color:var(--accent)}
.spinner{display:inline-block;width:13px;height:13px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .5s linear infinite;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}

/* ===== TABLES ===== */
table{width:100%;border-collapse:collapse;font-size:10px}
th{
  text-align:left;color:var(--accent);font-weight:500;padding:10px 14px;
  border-bottom:1px solid var(--border-light);font-size:9px;text-transform:uppercase;
  letter-spacing:.8px;font-family:var(--font-body);
}
td{padding:9px 14px;border-bottom:1px solid var(--border);vertical-align:top}
tr:hover{background:rgba(166,226,46,.02)}
tr:nth-child(even){background:rgba(255,255,255,.008)}

/* ===== BADGES ===== */
.badge{display:inline-block;padding:1px 8px;border-radius:2px;font-size:8px;font-weight:600;letter-spacing:.5px;text-transform:uppercase}
.badge.ok{background:rgba(166,226,46,.1);color:var(--ok);border:1px solid rgba(166,226,46,.2)}
.badge.bad{background:rgba(249,38,114,.1);color:var(--bad);border:1px solid rgba(249,38,114,.2)}
.badge.warn{background:rgba(230,197,71,.1);color:var(--warn);border:1px solid rgba(230,197,71,.2)}
.badge.info{background:rgba(166,226,46,.06);color:var(--accent);border:1px solid rgba(166,226,46,.12)}

/* ===== SERVICES ===== */
.svc{
  display:flex;justify-content:space-between;align-items:center;padding:12px 16px;
  border-left:3px solid var(--border);margin-bottom:6px;background:var(--input-bg);
  border-radius:0 2px 2px 0;transition:border-color .3s;
}
.svc.run{border-left-color:var(--ok)}
.svc.stop{border-left-color:var(--bad);opacity:.45}
.svc-info{flex:1;min-width:0}
.svc-info code{display:block;font-size:9px;color:var(--muted);word-break:break-all}
.svc-info strong{color:var(--fg);font-size:11px}
.actions{display:flex;gap:6px;flex-shrink:0}

/* Sistema (escàner de ports) */
.sys-svc-header{display:flex;justify-content:space-between;padding:6px 16px;font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border);margin-bottom:4px}
.sys-svc{display:flex;justify-content:space-between;align-items:center;padding:6px 16px;font-size:10px;border-left:3px solid var(--border);margin-bottom:2px;background:var(--input-bg);border-radius:0 2px 2px 0;transition:border-color .3s}
.sys-svc.known{border-left-color:var(--ok)}
.sys-svc.unknown{border-left-color:var(--muted);opacity:.6}
.sys-svc-name{flex:1;min-width:0;color:var(--fg)}
.sys-svc-port{flex-shrink:0;width:70px;text-align:right;font-family:var(--font-body);font-size:10px;color:var(--accent)}
.sys-svc-port a{color:var(--accent)}
.sys-svc-pid{flex-shrink:0;width:60px;text-align:right;font-size:9px;color:var(--muted)}
.browse-entry:hover{background:var(--border)}

/* ===== BUTTONS ===== */
button{
  color:var(--fg);background:transparent;border:1px solid var(--border);padding:6px 14px;
  font-size:10px;cursor:pointer;border-radius:2px;font-family:inherit;transition:all .15s;
  letter-spacing:.3px;
}
button:hover{background:rgba(166,226,46,.06);border-color:var(--accent);color:var(--accent)}
button.danger{border-color:var(--bad);color:var(--bad)}
button.danger:hover{background:rgba(249,38,114,.08);border-color:var(--bad)}
button.primary{
  background:var(--accent);color:#09090b;border:0;font-weight:600;letter-spacing:.5px;
  text-transform:uppercase;transition:all .15s;
}
button.primary:hover{background:#b8f536;box-shadow:var(--glow-green)}
button.small{padding:3px 10px;font-size:9px}
input,select,textarea{
  background:var(--input-bg);border:1px solid var(--border);color:var(--fg);
  padding:9px 12px;border-radius:2px;font-family:inherit;font-size:11px;
  transition:border-color .15s,box-shadow .15s;
}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.row{display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap}

/* ===== FORMS ===== */
form.launch{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
form.launch input[type=text]{flex:1;min-width:250px}
form.launch label{color:var(--muted);font-size:9px;display:flex;align-items:center;gap:5px}

/* ===== LOGS ===== */
pre.logs{
  background:var(--input-bg);border:1px solid var(--border);border-radius:2px;padding:14px;
  max-height:400px;overflow:auto;font-size:10px;color:var(--muted);white-space:pre-wrap;word-break:break-all;
}
pre.logs.output{max-height:300px;margin-top:10px}
.empty{color:var(--muted);font-style:italic;padding:32px;text-align:center;font-size:10px}

/* ===== FLASH MESSAGES ===== */
.flash{padding:10px 14px;margin-bottom:14px;font-size:10px;border-radius:2px;border-left:3px solid transparent}
.flash.error{background:rgba(249,38,114,.06);color:var(--bad);border-left-color:var(--bad)}
.flash.ok{background:rgba(166,226,46,.05);color:var(--ok);border-left-color:var(--ok)}
.flash.info{background:rgba(166,226,46,.04);color:var(--accent);border-left-color:var(--accent)}

/* ===== KEY-VALUE ===== */
.kv{display:flex;gap:10px;padding:5px 0;font-size:10px;align-items:center}
.kv-key{color:var(--accent);min-width:170px;font-weight:500;letter-spacing:.4px}
.kv-val{color:var(--fg);word-break:break-all;flex:1}
.kv-val.masked{color:var(--muted)}
.mask-toggle{color:var(--accent);cursor:pointer;font-size:9px;user-select:none;margin-left:6px;transition:opacity .15s}
.mask-toggle:hover{opacity:.7}

/* ===== MODEL ITEMS ===== */
.model-item{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid var(--border);font-size:10px;transition:background .1s}
.model-item:last-child{border-bottom:0}
.model-item:hover{background:rgba(166,226,46,.02)}
.model-name{color:var(--fg);font-weight:500}
.model-info{color:var(--muted)}
.model-actions{display:flex;gap:6px}

/* ===== MODAL ===== */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:100;align-items:center;justify-content:center;backdrop-filter:blur(3px)}
.modal-bg.show{display:flex}
.modal{background:var(--card);border:1px solid var(--border-light);border-radius:2px;padding:28px;max-width:700px;width:92%;max-height:82vh;overflow-y:auto;box-shadow:0 12px 40px rgba(0,0,0,.7)}
.modal h2{font-family:var(--font-body);color:var(--accent);margin-top:0;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.5px}

/* ===== TOGGLE ===== */
.toggle{position:relative;display:inline-block;width:44px;height:24px}
.toggle input{opacity:0;width:0;height:0}
.toggle .slider{position:absolute;cursor:pointer;inset:0;background:var(--border);border-radius:2px;transition:.25s}
.toggle .slider::before{position:absolute;content:'';height:18px;width:18px;left:3px;bottom:3px;background:var(--fg);border-radius:1px;transition:.25s}
.toggle input:checked+.slider{background:var(--ok)}
.toggle input:checked+.slider::before{transform:translateX(20px)}

/* ===== KEY CARDS ===== */
.key-card{
  display:flex;align-items:center;gap:14px;padding:14px;border:1px solid var(--border);
  border-radius:2px;margin-bottom:6px;background:var(--input-bg);transition:border-color .15s;
}
.key-card:hover{border-color:var(--accent)}
.key-card .key-icon{width:34px;height:34px;border-radius:2px;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:14px;flex-shrink:0;background:rgba(166,226,46,.08);color:var(--accent)}
.key-card .key-info{flex:1;min-width:0}
.key-card .key-name{font-weight:500;font-size:11px}
.key-card .key-status{font-size:9px;color:var(--muted);margin-top:2px}
.key-card .key-actions{display:flex;gap:6px;align-items:center}

/* ===== SYSTEM PROMPT ===== */
.sys-prompt{
  width:100%;min-height:200px;background:var(--input-bg);color:var(--fg);border:1px solid var(--border);
  border-radius:2px;padding:14px;font-family:var(--font-body);font-size:10px;resize:vertical;
  line-height:1.6;transition:border-color .15s;
}
.sys-prompt:focus{outline:0;border-color:var(--accent)}

/* ===== TOOL CARDS ===== */
.tool-card{border:1px solid var(--border);border-radius:2px;margin-bottom:8px;overflow:hidden;transition:border-color .15s}
.tool-card:hover{border-color:var(--border-light)}
.tool-card .tool-header{display:flex;align-items:center;gap:12px;padding:14px;background:var(--card);cursor:pointer;transition:background .1s}
.tool-card .tool-header:hover{background:rgba(166,226,46,.02)}
.tool-card .tool-name{font-weight:500;font-size:11px;flex:1}
.tool-card .tool-body{display:none;padding:14px;border-top:1px solid var(--border);background:var(--bg)}
.tool-card.open .tool-body{display:block}
.tool-func{margin-bottom:6px;padding:10px;background:var(--card);border-radius:2px;border:1px solid var(--border)}
.tool-func .func-name{color:var(--accent);font-weight:500;font-size:10px}
.tool-func .func-desc{color:var(--muted);font-size:9px;margin-top:3px}
.tool-func .func-params{color:var(--muted);font-size:9px;margin-top:2px}

/* ===== OVERVIEW ===== */
.overview-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.stat-card{
  background:var(--card);border:1px solid var(--border);border-radius:2px;
  padding:20px 24px;transition:border-color .2s;position:relative;overflow:hidden;
}
.stat-card::after{content:'';position:absolute;top:0;right:0;width:40%;height:100%;background:linear-gradient(90deg,transparent,rgba(166,226,46,.01));pointer-events:none}
.stat-card:hover{border-color:var(--border-light)}
.stat-card h3{font-family:var(--font-body);color:var(--accent);font-size:9px;margin:0 0 12px;font-weight:500;letter-spacing:.8px;text-transform:uppercase}
.stat-card .stat-num{font-family:var(--font-body);font-size:42px;color:var(--fg);margin-bottom:2px;font-weight:300;letter-spacing:-2px}
.stat-card .stat-label{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px}

/* ===== TIMELINE ===== */
.timeline{border-left:1px solid var(--border-light);margin-left:8px;padding-left:16px}
.timeline-item{padding:4px 0;font-size:10px}
.timeline-item .tl-time{color:var(--muted);font-size:9px}
.timeline-item .tl-event{color:var(--fg)}
.timeline-item.ok .tl-event{color:var(--ok)}
.timeline-item.bad .tl-event{color:var(--bad)}

/* ===== PROGRESS BAR ===== */
.progress-bar{width:100%;height:4px;background:var(--border);border-radius:2px;margin-top:4px;overflow:hidden}
.progress-fill{height:100%;background:var(--accent);border-radius:2px;transition:width .3s}

/* ===== HEALTH DOT ===== */
.health-dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:4px}
.health-dot.ok{background:var(--ok);box-shadow:0 0 6px var(--accent)}
.health-dot.warn{background:var(--warn)}
.health-dot.bad{background:var(--bad)}

/* ===== GLOBAL LOADING BAR ===== */
#global-loading-bar{position:fixed;top:0;left:0;height:2px;background:var(--accent);transition:width .3s,opacity .3s;z-index:9999;width:0;opacity:0;box-shadow:0 0 8px var(--accent)}

/* ===== GREEN FLASH ===== */
@keyframes greenFlash{0%{box-shadow:0 0 10px rgba(166,226,46,.4)}100%{box-shadow:0 0 0 0 rgba(166,226,46,0)}}
.svc.flash-ok{animation:greenFlash 2s ease-out;border-left-color:var(--ok)!important}

/* ===== LOGS STREAM ===== */
.logs-stream{
  background:var(--input-bg);border:1px solid var(--border);border-radius:2px;padding:10px;
  margin-top:10px;max-height:350px;overflow-y:auto;font-family:var(--font-body);font-size:9px;
  color:var(--fg);white-space:pre-wrap;display:none;
}
.logs-stream.show{display:block}
.logs-panel{display:none;background:var(--input-bg);border:1px solid var(--border);border-radius:2px;padding:8px;margin-top:8px;max-height:250px;overflow-y:auto;font-family:monospace;font-size:9px;white-space:pre-wrap;color:var(--fg)}
.logs-panel.show{display:block}

/* ===== REPAIR EVENTS ===== */
.msg.repair{font-size:10px;font-style:normal;padding:9px 14px;border-left:3px solid var(--accent);background:var(--card);border-radius:2px}
.msg.repair.fallback{border-left-color:var(--accent)}
.msg.repair.kb{border-left-color:var(--ok)}
.msg.repair.ollama{border-left-color:var(--accent)}
.msg.repair.deepseek{border-left-color:var(--warn);background:rgba(230,197,71,.05)}
.msg.repair.anthropic{border-left-color:var(--warn)}
.msg.repair.success{border-left-color:var(--ok);background:rgba(166,226,46,.04)}
.msg.repair.failure{border-left-color:var(--bad);background:rgba(249,38,114,.04)}
.msg.repair.diagnosis{font-style:italic;border-left-color:var(--muted)}
.repair-badge{display:inline-block;padding:1px 7px;border-radius:2px;font-size:8px;font-weight:700;margin-right:6px;text-transform:uppercase;letter-spacing:.4px}
.repair-badge.fb{background:rgba(166,226,46,.1);color:var(--accent)}
.repair-badge.kb{background:rgba(166,226,46,.1);color:var(--ok)}
.repair-badge.ollama{background:rgba(166,226,46,.1);color:var(--accent)}
.repair-badge.deepseek{background:rgba(230,197,71,.1);color:var(--warn)}
.repair-badge.anthropic{background:rgba(230,197,71,.08);color:var(--warn)}
.agent-line{display:block;font-size:11px;color:var(--muted);padding:1px 0;line-height:1.5}
.agent-line.step{font-size:12px;color:var(--fg);font-weight:600;padding:5px 0 3px}
.agent-line.info{color:var(--accent)}
.agent-line.warn{color:var(--warn)}
.agent-block{max-height:600px;overflow-y:auto;background:var(--input-bg);border:1px solid var(--border-light);border-radius:2px;padding:10px 14px;margin:6px 0;min-height:80px}
.agent-block::before{content:'PROGRÉS';display:block;font-size:9px;color:var(--accent);letter-spacing:.8px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--border);font-weight:600}
.repair-table-wrap{overflow-x:auto}
.repair-cmd{
  font-family:var(--font-body);font-size:8px;background:var(--input-bg);padding:3px 8px;
  border-radius:2px;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block;
}

/* ===== WIZARD ===== */
.wizard-form{
  background:var(--card);border:1px solid var(--border);border-radius:2px;padding:18px;
  margin:6px 0;animation:fadeIn .2s ease;
}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.wizard-progress-bar{width:100%;height:2px;background:var(--border);border-radius:0;margin-bottom:16px;overflow:hidden}
.wizard-progress-fill{height:100%;background:var(--accent);transition:width .35s ease}
.wizard-step-title{font-family:var(--font-body);font-size:12px;color:var(--accent);margin-bottom:6px;font-weight:600;text-transform:uppercase;letter-spacing:.4px}
.wizard-step-sub{font-size:9px;color:var(--muted);margin-bottom:14px}
.wizard-label{display:block;font-size:9px;color:var(--muted);margin-bottom:5px;font-weight:500;text-transform:uppercase;letter-spacing:.6px}
.wizard-input{width:100%;background:var(--input-bg);border:1px solid var(--border);color:var(--fg);padding:10px 12px;border-radius:2px;font-family:inherit;font-size:11px;margin-bottom:12px;transition:border-color .15s}
.wizard-input:focus{outline:0;border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.wizard-input-wrap{position:relative}
.wizard-input-wrap .wizard-toggle-vis{position:absolute;right:8px;top:50%;transform:translateY(-50%);background:var(--border);border:0;color:var(--muted);padding:4px 10px;border-radius:2px;font-size:9px;cursor:pointer;transition:background .15s}
.wizard-input-wrap .wizard-toggle-vis:hover{background:var(--border-light)}
.wizard-hint{font-size:9px;color:var(--warn);margin-bottom:12px;background:rgba(230,197,71,.06);padding:8px 12px;border-radius:2px;border-left:2px solid var(--warn)}
.wizard-buttons{display:flex;gap:8px;justify-content:flex-end;margin-top:8px}
.wizard-btn-primary{background:var(--accent);color:#09090b;border:0;padding:8px 18px;border-radius:2px;font-weight:600;cursor:pointer;font-family:inherit;font-size:10px;letter-spacing:.5px;text-transform:uppercase;transition:all .15s}
.wizard-btn-primary:hover{background:#b8f536;box-shadow:var(--glow-green)}
.wizard-btn-secondary{background:transparent;color:var(--muted);border:1px solid var(--border);padding:8px 18px;border-radius:2px;cursor:pointer;font-family:inherit;font-size:10px;transition:all .15s}
.wizard-btn-secondary:hover{border-color:var(--accent);color:var(--fg)}
.wizard-btn-skip{background:transparent;color:var(--warn);border:1px solid var(--warn);padding:8px 18px;border-radius:2px;cursor:pointer;font-family:inherit;font-size:10px;transition:all .15s}
.wizard-btn-skip:hover{background:rgba(230,197,71,.08)}
.wizard-toggle-group{display:flex;flex-direction:column;gap:8px;margin-bottom:14px}
.wizard-toggle-row{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;background:var(--input-bg);border:1px solid var(--border);border-radius:2px;transition:border-color .15s}
.wizard-toggle-row:hover{border-color:var(--border-light)}
.wizard-toggle-row .wt-label{font-size:11px;color:var(--fg)}
.wizard-toggle-row .wt-info{font-size:9px;color:var(--muted)}
.wizard-summary{display:flex;flex-direction:column;gap:8px;margin-bottom:14px}
.wizard-summary-row{display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid var(--border);font-size:10px}
.wizard-summary-row:last-child{border-bottom:0}
.wizard-summary-row .ws-label{color:var(--muted)}
.wizard-summary-row .ws-val{color:var(--fg);font-weight:500}
.wizard-masked{color:var(--warn)}

/* ===== SYNTAX HIGHLIGHT ===== */
.syn-keyword{color:#f92672}.syn-string{color:#e6c547}.syn-comment{color:#6b6b78;font-style:italic}.syn-func{color:#a6e22e}

/* ===== RESPONSIVE ===== */
@media(max-width:750px){
  body{flex-direction:column}
  nav{height:auto;flex-wrap:wrap;padding:4px}
  nav .nav-links{overflow-x:auto;height:36px}
  nav a{padding:0 10px;font-size:9px}
  nav .nav-status{display:none}
  main section{padding:16px}
  .chat-layout{flex-direction:column}
  .thread-sidebar{width:100%;min-width:100%;max-height:180px}
  .overview-grid{grid-template-columns:1fr}
}
"""

_HTML_BODY = """\
<nav>
  <div class="logo">BARTOLO<span class="cursor"></span></div>
  <div class="nav-links">
    <a href="#tab-visio" data-tab="visio" class="active">Visio</a>
    <a href="#tab-chat" data-tab="chat">Xat</a>
    <a href="#tab-models" data-tab="models">Models</a>
    <a href="#tab-repos" data-tab="repos">Repos</a>
    <a href="#tab-databases" data-tab="databases">DBs</a>
    <a href="#tab-secrets" data-tab="secrets">Keys</a>
    <a href="#tab-tools" data-tab="tools">Eines</a>
    <a href="#tab-shell" data-tab="shell">Shell</a>
    <a href="#tab-launch" data-tab="launch">Llençar</a>
    <a href="#tab-repairs" data-tab="repairs">Repairs</a>
  </div>
  <div class="nav-status"><span class="nav-dot"></span><span id="nav-hostname"></span><button class="kb-help-btn" id="kb-help-btn" title="Dreceres de teclat">?</button></div>
</nav>
<main>
<!-- VISIÓ GENERAL -->
<section id="tab-visio" class="active">
  <h1>Visió General</h1>
  <div class="sub">Estat del sistema</div>
  <div class="overview-grid">
    <div class="stat-card">
      <h3>Repos</h3>
      <div id="visio-repos"><span class="stat-num">—</span></div>
    </div>
    <div class="stat-card">
      <h3>Models</h3>
      <div id="visio-models"><span class="stat-num">—</span></div>
    </div>
    <div class="stat-card">
      <h3>Databases</h3>
      <div id="visio-databases"><span class="stat-num">—</span></div>
    </div>
    <div class="stat-card">
      <h3>Sistema</h3>
      <div id="visio-system"><span class="stat-num">—</span></div>
    </div>
    <div class="stat-card" style="grid-column:1/-1">
      <h3>Events recents</h3>
      <div id="visio-timeline" class="timeline">Carregant...</div>
    </div>
  </div>
</section>
<!-- CHAT -->
<section id="tab-chat">
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
      <div id="scroll-bottom-btn" title="Baixar" onclick="document.getElementById('chat-messages').scrollTo({top:document.getElementById('chat-messages').scrollHeight,behavior:'smooth'})">↓</div>
      <div id="chat-input-area">
        <textarea id="chat-input" placeholder="Escriu un missatge... (↑ historial, Enter enviar, Shift+Enter salt línia)" rows="1"></textarea>
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
  <div class="sub">WebSocket en temps real</div>
  <div id="shell-flash"></div>
  <div class="card">
    <div class="row">
      <input type="text" id="shell-cmd" placeholder="docker ps, ollama list, pwd..." style="flex:1">
      <button id="shell-exec-btn" class="primary">Executar (Enter)</button>
    </div>
    <pre class="logs output" id="shell-output" style="min-height:200px;max-height:400px"></pre>
    <div id="shell-history-area" style="margin-top:8px;display:none">
      <div style="color:var(--muted);font-size:10px;margin-bottom:4px">Historial:</div>
      <div id="shell-history-list" style="font-size:11px"></div>
    </div>
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
<!-- REPARACIONS -->
<section id="tab-repairs">
  <h1>&#x1f527; Historial de Reparacions</h1>
  <div class="sub">Errors corregits automaticament durant els muntatges</div>
  <div id="repairs-flash"></div>
  <div class="card">
    <div class="repair-table-wrap">
      <table>
        <thead><tr><th>Data</th><th>Repo</th><th>Stack</th><th>Error</th><th>Solucio</th><th>Font</th></tr></thead>
        <tbody id="repairs-tbody">
          <tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px">
            Cap reparacio registrada. Quan Bartolo corregeixi errors durant un muntatge, apareixeran aqui.
          </td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
</main>
<div id="kb-panel" class="kb-panel">
  <div class="kb-panel-inner">
    <span class="kb-item"><kbd>Ctrl+1..9</kbd> Pestanyes</span>
    <span class="kb-sep"></span>
    <span class="kb-item"><kbd>Ctrl+N</kbd> Xat nou</span>
    <span class="kb-sep"></span>
    <span class="kb-item"><kbd>Ctrl+W</kbd> Eliminar xat</span>
    <span class="kb-sep"></span>
    <span class="kb-item"><kbd>Enter</kbd> Enviar</span>
    <span class="kb-sep"></span>
    <span class="kb-item"><kbd>&uarr;&darr;</kbd> Historial</span>
    <button class="kb-close" onclick="document.getElementById('kb-panel').classList.remove('show')">&times;</button>
  </div>
</div>
<!-- Tool source modal -->
<div class="modal-bg" id="tool-modal"><div class="modal"><h2 id="tool-modal-title"></h2><textarea class="sys-prompt" id="tool-modal-source" style="max-height:65vh;min-height:300px" spellcheck="false"></textarea><pre id="tool-preview" class="logs" style="max-height:65vh;overflow:auto;display:none"></pre><div style="margin-top:8px;display:flex;gap:8px"><button class="primary" onclick="saveToolSource()">Desar</button><button class="small" onclick="toggleSyntaxPreview()">Preview</button><button onclick="document.getElementById('tool-modal').classList.remove('show')">Tancar</button></div></div></div>
"""

_JS = r"""
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
  document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
  const sec = document.getElementById('tab-' + t);
  if (sec) sec.classList.add('active');
  const navEl = document.querySelector('nav a[data-tab="' + t + '"]');
  if (navEl) navEl.classList.add('active');
  location.hash = 'tab-' + t;
  // Lazy load tab data
  if (!_loadedTabs[t]) { _loadedTabs[t] = true; loadTabData(t); }
  // Stop polling for tabs we're leaving
  if (t !== 'repos') stopPolling('repos');
  if (t !== 'databases') stopPolling('databases');
  if (t !== 'visio') stopPolling('visio');
}

function loadTabData(t) {
  if (t === 'chat') { loadThreads(); loadInputHistory(); }
  if (t === 'models') loadModels();
  if (t === 'repos') { loadStatus(); startPolling('repos', loadStatus, 2000, 15000); }
  if (t === 'databases') { loadDatabases(); startPolling('databases', loadDatabases, 5000, 30000); }
  if (t === 'secrets') loadSecrets();
  if (t === 'tools') loadTools();
  if (t === 'visio') { loadOverview(); startPolling('visio', loadOverview, 5000, 15000); }
  if (t === 'repairs') loadRepairHistory();
}

// ===== WEBSOCKET CHAT =====
let currentMsgEl = null;
let _currentThreadId = null;
let _threads = [];
let _inputHistory = [];
let _historyIdx = -1;
let _savedInput = '';
	let _localMessages = [];  // buffer local per sobreviure a reconnexions WebSocket

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
      else if (data.type === 'done') {
	        if (currentMsgEl) finishMessage();
	        else if (data.full_text) addChatMessage('assistant', data.full_text);
	      }
      else if (data.type === 'intent') addChatMessage('system', 'Intent: ' + data.intent);
      else if (data.type === 'error') addChatMessage('system', 'Error: ' + esc(data.error));
      else if (data.type === 'action') {
        if (data.done) addChatMessage('assistant', data.done);
        else addChatMessage('system', 'Executant: ' + esc(data.action));
      }
      else if (data.type === 'history') {
        // Preservar missatges locals si el servidor retorna buit (reconnexió WebSocket)
        var msgs = data.messages || [];
        if (!msgs.length && _localMessages.length) {
          // El servidor no té missatges — preservem els locals
          return;
        }
        document.getElementById('chat-messages').innerHTML = '';
        currentMsgEl = null;
        _localMessages = [];
        msgs.forEach(function(m) {
          _localMessages.push({role: m.role, content: m.content});
          addChatMessage(m.role, m.content);
        });
      }
      else if (data.type === 'wizard_step') { renderWizardStep(data); }
      else if (data.type === 'wizard_done') {
        if (_currentWizardMsgEl) {
          const el = _currentWizardMsgEl;
          el.innerHTML = esc(data.message || 'Muntatge iniciat.');
          el.style.whiteSpace = 'pre-wrap';
          _currentWizardMsgEl = null;
        }
      }
      else if (data.type === 'wizard_error') {
        if (_currentWizardMsgEl) {
          const el = _currentWizardMsgEl;
          el.textContent = 'Error: ' + (data.error || 'Error desconegut');
          el.style.color = 'var(--bad)';
          _currentWizardMsgEl = null;
        } else {
          addChatMessage('system', 'Error wizard: ' + esc(data.error || ''));
        }
      }
      else if (data.type === 'agent_output') {
        handleAgentOutput(data.lines);
      }
      else if (data.type === 'repair_event') {
        handleRepairEvent(data);
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
  autoResizeChatInput();
  currentMsgEl = null;
  ws.send(JSON.stringify({type:'chat', message:msg, thread_id:_currentThreadId}));
  // Refresh thread list after a moment
  setTimeout(loadThreads, 500);
}

// ===== MARKDOWN RENDERER =====
function renderMarkdown(text) {
  if (!text) return '';
  var t = esc(text);
  // Store code blocks
  var blocks = [];
  t = t.replace(/```(\w*)\n?([\s\S]*?)```/g, function(_, lang, code) {
    var trimmed = code.replace(/\n+$/, '');
    blocks.push('<pre class="md-code'+(lang?' md-lang-'+esc(lang):'')+'"><code>' + trimmed + '</code></pre>');
    return '\x00BLK' + (blocks.length - 1) + '\x00';
  });
  // Inline code
  t = t.replace(/`([^`]+)`/g, '<code class="md-inline">$1</code>');
  // Bold
  t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // Italic
  t = t.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  // Links
  t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  // Restore code blocks
  t = t.replace(/\x00BLK(\d+)\x00/g, function(_, i) { return blocks[parseInt(i)] || ''; });
  // Line breaks
  t = t.replace(/\n/g, '<br>');
  return t;
}

function _addCopyBtn(el) {
  var btn = document.createElement('span');
  btn.className = 'msg-copy';
  btn.title = 'Copiar';
  btn.textContent = '⎘';
  btn.addEventListener('click', function(e) {
    e.stopPropagation();
    var text = el.getAttribute('data-raw') || el.textContent || '';
    navigator.clipboard.writeText(text).then(function() {
      btn.textContent = '✓';
      setTimeout(function() { btn.textContent = '⎘'; }, 1200);
    }).catch(function() {});
  });
  el.appendChild(btn);
}
function _timeStr() {
  var now = new Date();
  return ('0'+now.getHours()).slice(-2) + ':' + ('0'+now.getMinutes()).slice(-2);
}
function _addTime(el) {
  var t = document.createElement('span');
  t.className = 'msg-time';
  t.textContent = _timeStr();
  el.appendChild(t);
}
function addChatMessage(role, text, raw) {
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  if (role === 'system') {
    el.innerHTML = renderMarkdown(text);
    el.style.whiteSpace = 'normal';
  } else {
    el.innerHTML = renderMarkdown(text);
    el.style.whiteSpace = 'pre-wrap';
  }
  // Store raw text for copy
  el.setAttribute('data-raw', raw || text);
  _addTime(el);
  _addCopyBtn(el);
  document.getElementById('chat-messages').appendChild(el);
  _localMessages.push({role: role, content: raw || text});
  el.scrollIntoView({behavior:'smooth'});
}
function appendToken(token) {
  if (!currentMsgEl) {
    currentMsgEl = document.createElement('div');
    currentMsgEl.className = 'msg assistant';
    currentMsgEl.style.whiteSpace = 'pre-wrap';
    currentMsgEl._streamText = '';
    document.getElementById('chat-messages').appendChild(currentMsgEl);
  }
  currentMsgEl._streamText = (currentMsgEl._streamText || '') + token;
  currentMsgEl.textContent = currentMsgEl._streamText;
  currentMsgEl.scrollIntoView({behavior:'smooth'});
}
function finishMessage() {
  if (currentMsgEl) {
    var raw = currentMsgEl._streamText || '';
    currentMsgEl.innerHTML = renderMarkdown(raw);
    currentMsgEl.style.whiteSpace = 'pre-wrap';
    currentMsgEl.setAttribute('data-raw', raw);
    _addTime(currentMsgEl);
    _addCopyBtn(currentMsgEl);
    _localMessages.push({role: 'assistant', content: raw});
  }
  currentMsgEl = null;
}

// ===== SCROLL-TO-BOTTOM =====
document.addEventListener('DOMContentLoaded', function() {
  var chatMsgs = document.getElementById('chat-messages');
  if (!chatMsgs) return;
  var btn = document.getElementById('scroll-bottom-btn');
  chatMsgs.addEventListener('scroll', function() {
    var dist = chatMsgs.scrollHeight - chatMsgs.scrollTop - chatMsgs.clientHeight;
    btn.style.display = dist > 100 ? 'flex' : 'none';
  });
});

// ===== AGENT OUTPUT & REPAIR EVENTS =====
let _agentBlockEl = null;
let _autoScroll = true;

function handleAgentOutput(lines) {
  if (!lines) return;
  var chatEl = document.getElementById('chat-messages');
  // Track if user has scrolled up
  _autoScroll = chatEl.scrollHeight - chatEl.scrollTop - chatEl.clientHeight < 40;
  // Create or reuse the agent output block
  if (!_agentBlockEl) {
    _agentBlockEl = document.createElement('div');
    _agentBlockEl.className = 'msg system agent-block';
    chatEl.appendChild(_agentBlockEl);
  }
  lines.split('\n').forEach(function(line) {
    var span = document.createElement('span');
    span.className = 'agent-line';
    if (/^--- Step \d+\/\d+/.test(line)) span.className += ' step';
    else if (/^\[INFO\]/.test(line)) span.className += ' info';
    else if (/^\[WARN\]/.test(line)) span.className += ' warn';
    else if (/^=== RESUM/.test(line)) span.className += ' step';
    // Fer URLs clicables
    var urlMatch = line.match(/https?:\/\/\S+/);
    if (urlMatch) {
      var url = urlMatch[0].replace(/[.,;]$/, '');
      span.innerHTML = esc(line).replace(esc(url), '<a href="'+esc(url)+'" target="_blank" rel="noopener" style="color:var(--accent)">'+esc(url)+'</a>');
    } else {
      span.textContent = line;
    }
    _agentBlockEl.appendChild(span);
  });
  // Trim old lines to keep block manageable
  while (_agentBlockEl.children.length > 300) _agentBlockEl.firstChild.remove();
  if (_autoScroll) _agentBlockEl.scrollIntoView({behavior:'smooth'});
}

function handleRepairEvent(data) {
  _agentBlockEl = null; // close agent block before showing a repair event
  var stage = data.stage || data.type || '';
  var badgeMap = {fallback:{cls:'fb',label:'Pla B'},kb:{cls:'kb',label:'KB'},ollama:{cls:'ollama',label:'Ollama'},
                  deepseek:{cls:'deepseek',label:'DeepSeek API'},anthropic:{cls:'anthropic',label:'Anthropic API'}};
  var badge = badgeMap[stage] || {cls:'',label:stage};
  var el = document.createElement('div');
  el.className = 'msg repair ' + (stage === 'repair_success' ? 'success' :
    stage === 'repair_failed' ? 'failure' : stage);
  if (stage === 'repair_diagnosis') el.className += ' diagnosis';
  var html = '';
  if (stage === 'repair_success') {
    html = '<span class="repair-badge ok">OK</span> <b>Reparat via ' + esc(data.source) + '</b>';
    if (data.fix_command) html += ' <code style="font-size:10px">' + esc(data.fix_command) + '</code>';
    if (data.error_type) html += ' <span style="color:var(--muted);font-size:10px">[' + esc(data.error_type) + ']</span>';
  } else if (stage === 'repair_failed') {
    html = '<span class="repair-badge bad">KO</span> <b>Reparació fallida</b> després de ' + (data.attempts||'?') + ' intents';
  } else if (stage === 'repair_diagnosis') {
    html = '<span style="color:var(--muted)">Diagnosi:</span> <b>' + esc(data.description||'') + '</b>';
    if (data.error_type) html += ' <span class="badge info">' + esc(data.error_type) + '</span>';
  } else if (stage === 'repair_stage' || stage === 'repair_suggestion') {
    var b = badgeMap[data.stage] || badgeMap[stage] || {};
    html = '<span class="repair-badge ' + (b.cls||'') + '">' + (b.label||stage) + '</span>';
    if (stage === 'deepseek') html += ' <b>Crida a DeepSeek API</b>';
    else if (stage === 'anthropic') html += ' <b>Crida a Anthropic API</b>';
    else if (stage === 'kb') html += ' <b>KB hit</b>';
    else if (stage === 'ollama') html += ' <b>Reparant amb Ollama</b>';
    else html += ' <b>' + esc(stage) + '</b>';
    if (data.reason) html += ' <span style="color:var(--muted);font-size:10px">(' + esc(data.reason) + ')</span>';
    if (data.command) html += ' <code style="font-size:10px;display:block;margin-top:3px">' + esc(data.command) + '</code>';
    if (data.error_type) html += ' <span class="badge info" style="margin-left:4px">' + esc(data.error_type) + '</span>';
  }
  el.innerHTML = html;
  document.getElementById('chat-messages').appendChild(el);
  el.scrollIntoView({behavior:'smooth'});
}

// ===== WIZARD FORMS =====
let _currentWizardMsgEl = null;
let _wizardProcessing = false;

function wizEl(tag, cls, attrs) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (attrs) Object.entries(attrs).forEach(([k,v]) => { if (v != null) el[k] = v; });
  return el;
}
function wizButton(text, cls, handler) {
  const b = wizEl('button', cls);
  b.textContent = text;
  b.addEventListener('click', handler);
  return b;
}
function wizInput(type, placeholder, val, cls) {
  const i = wizEl('input', cls || 'wizard-input');
  i.type = type;
  if (placeholder) i.placeholder = placeholder;
  if (val != null) i.value = val;
  return i;
}

function clearWizard() {
  if (_currentWizardMsgEl) { _currentWizardMsgEl.querySelector('.wizard-form').remove(); _currentWizardMsgEl = null; }
}

function wizBackButton() {
  return wizButton('Tornar', 'wizard-btn-secondary', function() {
    submitWizardResponse('_back', {action:'back'});
  });
}

function submitWizardResponse(step, data) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (_wizardProcessing) return;
  _wizardProcessing = true;
  // Deshabilitar tots els botons del wizard per evitar doble enviament
  if (_currentWizardMsgEl) {
    var btns = _currentWizardMsgEl.querySelectorAll('.wizard-btn-primary, .wizard-btn-skip, .wizard-btn-secondary');
    btns.forEach(function(b) { b.disabled = true; b.style.opacity = '0.5'; });
    var inp = _currentWizardMsgEl.querySelector('.wizard-input');
    if (inp) inp.disabled = true;
  }
  ws.send(JSON.stringify({type:'wizard_response', thread_id:_currentThreadId, step:step, data:data}));
}

function renderWizardStep(data) {
  _wizardProcessing = false;
  const step = data.step;
  const payload = data.payload || {};
  const stepIndex = data.step_index != null ? data.step_index : 0;
  const totalSteps = data.total_steps || 5;

  // Find existing wizard bubble or create one
  let wrapper;
  if (_currentWizardMsgEl) {
    wrapper = _currentWizardMsgEl;
    // Remove old wizard form
    const oldForm = wrapper.querySelector('.wizard-form');
    if (oldForm) oldForm.remove();
  } else {
    wrapper = document.createElement('div');
    wrapper.className = 'msg assistant msg-no-copy';
    wrapper.style.whiteSpace = 'normal';
    document.getElementById('chat-messages').appendChild(wrapper);
    _currentWizardMsgEl = wrapper;
  }

  const form = wizEl('div', 'wizard-form');
  const total = data.total_steps || 5;

  // Progress bar
  const pct = total > 1 ? Math.round((stepIndex / (total - 1)) * 100) : 0;
  form.innerHTML += '<div class="wizard-progress-bar"><div class="wizard-progress-fill" style="width:' + pct + '%"></div></div><div class="wizard-step-sub">Pas ' + (stepIndex + 1) + ' de ' + total + '</div>';

  if (step === 'workspace') buildWorkspaceForm(form, payload);
  else if (step === 'secret') buildSecretForm(form, payload);
  else if (step === 'cloud_choice') buildCloudChoiceForm(form, payload);
  else if (step === 'supabase_migrate') buildSupabaseMigrateForm(form, payload);
  else if (step === 'confirm') buildConfirmForm(form, payload);

  wrapper.appendChild(form);
  form.scrollIntoView({behavior:'smooth'});
}

function buildWorkspaceForm(form, p) {
  form.innerHTML += '<div class="wizard-step-title">Carpeta de muntatge</div>';
  form.innerHTML += '<div class="wizard-label">On vols muntar <code style="background:var(--input-bg);padding:2px 6px;border-radius:3px">' + esc(p.repo_url || '') + '</code>?</div>';
  const inp = wizInput('text', '', p.default_value || '', 'wizard-input');
  // Row: input + browse button
  const row = wizEl('div', '');
  row.style.cssText = 'display:flex;gap:8px;align-items:center';
  row.appendChild(inp);
  const browseBtn = wizButton('Explora', 'wizard-btn-secondary');
  browseBtn.style.cssText = 'white-space:nowrap;flex-shrink:0';
  row.appendChild(browseBtn);
  form.appendChild(row);
  // File browser panel
  const browser = wizEl('div', '');
  browser.style.cssText = 'display:none;margin-top:10px;border:1px solid var(--border-light);border-radius:6px;padding:8px;max-height:280px;overflow-y:auto;background:var(--input-bg)';
  form.appendChild(browser);
  // Browse button handler
  browseBtn.addEventListener('click', function() {
    if (browser.style.display === 'none') {
      browser.style.display = 'block';
      browseBtn.textContent = 'Amaga';
      loadBrowserPath(browser, inp.value || '~');
    } else {
      browser.style.display = 'none';
      browseBtn.textContent = 'Explora';
    }
  });
  // Also update input when user types in it directly
  inp.setAttribute('data-wizard-input', 'workspace');
  // When user selects a folder from browser, update input
  inp.addEventListener('input', function() { /* user typed manually */ });
  const btns = wizEl('div', 'wizard-buttons');
  btns.appendChild(wizButton('Continua', 'wizard-btn-primary', function() {
    submitWizardResponse('workspace', {workspace: inp.value});
  }));
  form.appendChild(btns);
}

function loadBrowserPath(browser, pathStr) {
  // Find the associated input field (the one in the same form as this browser)
  var wizardForm = browser.closest('.wizard-form');
  var targetInput = wizardForm ? wizardForm.querySelector('.wizard-input') : document.querySelector('.wizard-input');
  var targetBrowseBtn = wizardForm ? wizardForm.querySelector('.wizard-btn-secondary') : document.querySelector('.wizard-btn-secondary');
  fetch('/api/browse-fs?path=' + encodeURIComponent(pathStr))
    .then(function(r) { return r.json(); })
    .then(function(data) {
      browser.innerHTML = '';
      // Breadcrumb + select button
      var top = document.createElement('div');
      top.style.cssText = 'display:flex;gap:8px;align-items:center;margin-bottom:8px;font-size:11px';
      var selBtn = document.createElement('button');
      selBtn.textContent = 'Selecciona';
      selBtn.className = 'wizard-btn-primary';
      selBtn.style.cssText = 'font-size:10px;padding:3px 10px';
      selBtn.addEventListener('click', function() {
        if (targetInput) targetInput.value = data.path;
        browser.style.display = 'none';
        if (targetBrowseBtn) targetBrowseBtn.textContent = 'Explora';
      });
      top.appendChild(selBtn);
      var bc = document.createElement('span');
      bc.style.cssText = 'color:var(--muted);word-break:break-all';
      bc.textContent = data.path;
      top.appendChild(bc);
      browser.appendChild(top);
      // Parent dir
      if (data.parent) {
        var parentRow = document.createElement('div');
        parentRow.className = 'browse-entry';
        parentRow.style.cssText = 'padding:6px 8px;cursor:pointer;border-radius:4px;display:flex;gap:6px;align-items:center;font-size:11px';
        parentRow.innerHTML = '&#x1f4c1; ..';
        parentRow.addEventListener('click', function() { loadBrowserPath(browser, data.parent); });
        browser.appendChild(parentRow);
      }
      // Entries
      if (!data.entries || data.entries.length === 0) {
        var empty = document.createElement('div');
        empty.style.cssText = 'color:var(--muted);font-size:11px;padding:8px';
        empty.textContent = '(directori buit)';
        browser.appendChild(empty);
      } else {
        data.entries.forEach(function(e) {
          var erow = document.createElement('div');
          erow.style.cssText = 'padding:6px 8px;cursor:pointer;border-radius:4px;display:flex;gap:6px;align-items:center;font-size:11px';
          erow.className = 'browse-entry';
          if (e.is_dir) {
            erow.innerHTML = '<span style="color:var(--accent2)">&#x1f4c1;</span> <span>' + esc(e.name) + '</span>';
          }
          if (e.is_dir) {
            erow.addEventListener('click', function() { loadBrowserPath(browser, e.path); });
            browser.appendChild(erow);
          }
        });
      }
      // Error
      if (data.error) {
        var err = document.createElement('div');
        err.style.cssText = 'color:var(--bad);font-size:11px;padding:4px 8px';
        err.textContent = data.error;
        browser.appendChild(err);
      }
    })
    .catch(function(err) {
      browser.innerHTML = '<div style="color:var(--bad);font-size:11px;padding:4px 8px">Error de connexió</div>';
    });
}

function buildSecretForm(form, p) {
  const key = p.key || '';
  const hint = p.hint || '';
  const desc = p.description || '';
  const required = p.required !== false;
  const remaining = p.remaining || [];

  // Title with required/optional badge
  const badgeCls = required ? 'badge bad' : 'badge info';
  const badgeLabel = required ? 'Obligatori' : 'Opcional';
  form.innerHTML += '<div class="wizard-step-title">' + esc(p.label || key) + ' <span class="' + badgeCls + '" style="font-size:10px">' + badgeLabel + '</span></div>';
  if (desc) form.innerHTML += '<div style="font-size:11px;color:var(--fg);margin-bottom:10px;line-height:1.5">' + esc(desc) + '</div>';
  if (hint) form.innerHTML += '<div class="wizard-hint">Format: ' + esc(hint) + '</div>';
  const wrap = wizEl('div', 'wizard-input-wrap');
  const inp = wizInput('password', 'Valor per a ' + key, '', 'wizard-input');
  wrap.appendChild(inp);
  const toggle = wizButton('Mostra', 'wizard-toggle-vis');
  toggle.addEventListener('click', function() {
    inp.type = inp.type === 'password' ? 'text' : 'password';
    toggle.textContent = inp.type === 'password' ? 'Mostra' : 'Amaga';
  });
  wrap.appendChild(toggle);
  form.appendChild(wrap);
  if (remaining.length) {
    const remDiv = wizEl('div', '');
    remDiv.style.cssText = 'font-size:10px;color:var(--muted);margin-bottom:10px';
    remDiv.textContent = 'Falten: ' + remaining.join(', ');
    form.appendChild(remDiv);
  }
  const btns = wizEl('div', 'wizard-buttons');
  btns.appendChild(wizBackButton());
  btns.appendChild(wizButton('Ometre', 'wizard-btn-skip', function() {
    submitWizardResponse('secret', {key:key, value:'', skipped:true});
  }));
  btns.appendChild(wizButton('Continua', 'wizard-btn-primary', function() {
    submitWizardResponse('secret', {key:key, value:inp.value, skipped:false});
  }));
  form.appendChild(btns);
  inp.addEventListener('keydown', function(e) { if (e.key === 'Enter') { e.preventDefault(); submitWizardResponse('secret', {key:key, value:inp.value, skipped:false}); } });
  setTimeout(function() { inp.focus(); }, 100);
}

function buildCloudChoiceForm(form, p) {
  const services = p.services || [];
  form.innerHTML += '<div class="wizard-step-title">Serveis Cloud</div>';
  form.innerHTML += '<div class="wizard-label">Tria si vols usar els serveis cloud originals o alternatiu local Docker</div>';
  const group = wizEl('div', 'wizard-toggle-group');
  const choices = {};
  services.forEach(function(svc) {
    const row = wizEl('div', 'wizard-toggle-row');
    const info = wizEl('div', '');
    info.innerHTML = '<div class="wt-label">' + esc(svc.label) + '</div><div class="wt-info">Cloud original o ' + esc(svc.local) + ' via Docker</div>';
    row.appendChild(info);
    // Toggle: off = local, on = cloud
    const toggle = wizEl('label', 'toggle');
    const chk = wizEl('input', '');
    chk.type = 'checkbox';
    chk.checked = false; // default local
    choices[svc.key] = 'local';
    chk.addEventListener('change', function() { choices[svc.key] = chk.checked ? 'cloud' : 'local'; });
    toggle.appendChild(chk);
    toggle.appendChild(wizEl('span', 'slider'));
    row.appendChild(toggle);
    group.appendChild(row);
    choices[svc.key] = 'local'; // initialize
  });
  form.appendChild(group);
  const btns = wizEl('div', 'wizard-buttons');
  btns.appendChild(wizBackButton());
  btns.appendChild(wizButton('Continua', 'wizard-btn-primary', function() {
    submitWizardResponse('cloud_choice', {choices:choices});
  }));
  form.appendChild(btns);
}

function buildSupabaseMigrateForm(form, p) {
  form.innerHTML += '<div class="wizard-step-title">Migració de Supabase</div>';
  form.innerHTML += '<div class="wizard-label">' + esc(p.question || 'Vols replicar les dades al PostgreSQL local?') + '</div>';
  form.innerHTML += '<div style="font-size:11px;color:var(--muted);margin-bottom:12px">' + esc(p.description || '') + '</div>';
  const btns = wizEl('div', 'wizard-buttons');
  btns.appendChild(wizBackButton());
  btns.appendChild(wizButton('No, gràcies', 'wizard-btn-secondary', function() {
    submitWizardResponse('supabase_migrate', {migrate:false});
  }));
  btns.appendChild(wizButton('Sí, replica dades', 'wizard-btn-primary', function() {
    submitWizardResponse('supabase_migrate', {migrate:true});
  }));
  form.appendChild(btns);
}

function buildConfirmForm(form, p) {
  form.innerHTML += '<div class="wizard-step-title">Confirmació</div>';
  const summary = wizEl('div', 'wizard-summary');
  summary.innerHTML += '<div class="wizard-summary-row"><span class="ws-label">Workspace</span><span class="ws-val">' + esc(p.workspace || '') + '</span></div>';
  summary.innerHTML += '<div class="wizard-summary-row"><span class="ws-label">Repo</span><span class="ws-val">' + esc(p.repo_url || '') + '</span></div>';
  if (p.secrets && Object.keys(p.secrets).length) {
    const keys = Object.keys(p.secrets).map(function(k) { return '<span class="wizard-masked">' + esc(k) + '</span>'; }).join(', ');
    summary.innerHTML += '<div class="wizard-summary-row"><span class="ws-label">Secrets</span><span class="ws-val">' + keys + '</span></div>';
  }
  if (p.cloud_choices && Object.keys(p.cloud_choices).length) {
    Object.entries(p.cloud_choices).forEach(function(e) {
      const icon = e[1] === 'local' ? '(local Docker)' : '(cloud)';
      summary.innerHTML += '<div class="wizard-summary-row"><span class="ws-label">' + esc(e[0]) + '</span><span class="ws-val">' + esc(icon) + '</span></div>';
    });
  }
  if (p.supabase_migrate) {
    summary.innerHTML += '<div class="wizard-summary-row"><span class="ws-label">Migració Supabase</span><span class="ws-val">Sí</span></div>';
  }
  form.appendChild(summary);
  const btns = wizEl('div', 'wizard-buttons');
  btns.appendChild(wizBackButton());
  btns.appendChild(wizButton('Munta', 'wizard-btn-primary', function() {
    submitWizardResponse('confirm', {});
  }));
  form.appendChild(btns);
}

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

function autoResizeChatInput() {
  const ta = document.getElementById('chat-input');
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
}
document.getElementById('chat-input').addEventListener('input', autoResizeChatInput);

// ===== THREAD MANAGEMENT =====
async function loadThreads() {
  try {
    const r = await apiFetch('/api/chat/threads');
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
  _localMessages = [];
  // Load messages from server
  try {
    const r = await apiFetch('/api/chat/threads/' + encodeURIComponent(id));
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
    const r = await apiFetch('/api/chat/threads', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
    const data = await r.json();
    if (data.ok && data.thread) {
      await loadThreads();
      selectThread(data.thread.id, false);
    }
  } catch(e) {}
}

async function deleteThread(id) {
  if (!confirm('Esborrar aquest fil de conversa?')) return;
  await apiFetch('/api/chat/threads/' + encodeURIComponent(id), {method:'DELETE'});
  if (_currentThreadId === id) {
    _currentThreadId = null;
    _localMessages = [];
    document.getElementById('chat-messages').innerHTML = '';
    document.getElementById('chat-title').textContent = 'Xat nou';
    localStorage.removeItem('bartolo-thread');
  }
  await loadThreads();
}

async function renameThread(id) {
  const title = prompt('Nou nom del fil:', '');
  if (!title) return;
  await apiFetch('/api/chat/threads/' + encodeURIComponent(id), {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:title})});
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
    await apiFetch('/api/chat/threads/' + encodeURIComponent(t.id), {method:'DELETE'});
  }
  _threads = [];
  _currentThreadId = null;
  _localMessages = [];
  document.getElementById('chat-messages').innerHTML = '';
  document.getElementById('chat-title').textContent = 'Xat nou';
  localStorage.removeItem('bartolo-thread');
  renderThreadList();
});

// Load input history from server
async function loadInputHistory() {
  try {
    const r = await apiFetch('/api/chat/history');
    const data = await r.json();
    if (data.history) _inputHistory = data.history;
  } catch(e) {}
}

// ===== MODELS =====
async function loadModels() {
  try {
    const r = await apiFetch('/api/models');
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
  const r = await apiFetch('/api/models/pull', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:name})});
  const data = await r.json();
  stat.innerHTML = data.ok ? '<span class="badge ok">OK</span> ' + esc(data.message) : '<span class="badge bad">Error</span> ' + esc(data.message);
  if (data.ok) setTimeout(loadModels, 2000);
});

// ===== REPOS =====
async function loadStatus() {
  try {
    const r = await apiFetch('/api/status');
    const data = await r.json();
    renderRepos(data);
  } catch(e) { document.getElementById('repos-content').innerHTML = '<div class="empty">Error</div>'; }
}
function renderRepos(data) {
  const repos = Object.entries(data).filter(([k]) => !k.startsWith('_'));
  document.getElementById('repos-meta').textContent = repos.length + ' repos';
  let h = '';
  // Repo services
  if (repos.length > 0) {
    h += '<div class="section-label" style="font-size:9px;color:var(--accent);text-transform:uppercase;letter-spacing:.8px;margin-bottom:8px;font-weight:600">Serveis muntats</div>';
  }
  for (const [repo, svcs] of repos) {
    if (!svcs||!svcs.length) continue;
    let sh = '';
    for (const s of svcs) {
      const alive = !!s.pid;
      // Extract URL from command
      let url = '';
      let port = '';
      const cmd = s.command||'';
      let m = cmd.match(/(?:PORT|port|--port)[= ](\d{4,5})/);
      if (m) port = m[1];
      if (!port) {
        const parts = cmd.split(/\s+/);
        const last = parts[parts.length-1];
        m = last.match(/:(\d{4,5})\b/);
        if (m) port = m[1];
      }
      if (port) url = 'http://localhost:' + port;
      sh += '<div class="svc '+(alive?'run':'stop')+'"><div class="svc-info"><strong>'+(alive?'&#x1f7e2; OK':'&#x1f534; STOP')+' &middot; PID '+(s.pid||'?')+(url ? ' &middot; <a href="'+esc(url)+'" target="_blank" rel="noopener">'+esc(url)+'</a>' : '')+'</strong><br><code style="font-size:11px;word-break:break-all">'+esc(s.step_id||'')+'</code> <code style="font-size:11px;word-break:break-all">'+esc(cmd)+'</code></div>'+
        '<div class="actions"><button class="small" data-view-logs="'+escUrl(repo)+'/'+escUrl(s.step_id||'')+'">Logs</button>'+
        '<button class="small" data-live-logs="'+escUrl(repo)+'">En directe</button>'+
        '<button class="small primary" data-restart-repo="'+escUrl(repo)+'">Restart</button>'+
        '<button class="small danger" data-stop-repo="'+escUrl(repo)+'">Stop</button></div></div>';
    }
    h += '<div class="card"><h2>&#x1f4c1; '+esc(repo)+'</h2>'+sh+
      '<div class="timeline" id="tl-'+escUrl(repo)+'" style="display:none;margin-top:8px"></div>'+
      '<div style="margin-top:4px"><button class="small" data-load-timeline="'+escUrl(repo)+'">Timeline</button></div>'+
      '</div>';
  }
  // Databases section
  var dbs = data._databases || [];
  if (dbs.length > 0) {
    h += '<div class="section-label" style="font-size:9px;color:var(--accent2);text-transform:uppercase;letter-spacing:.8px;margin:12px 0 8px;font-weight:600">Bases de dades</div>';
    for (var di = 0; di < dbs.length; di++) {
      var db = dbs[di];
      var dbTypeIcon = db.type === 'postgresql' ? '&#x1f418;' : (db.type === 'mongodb' ? '&#x1f334;' : (db.type === 'mysql' ? '&#x1f42c;' : (db.type === 'redis' ? '&#x1f534;' : '&#x1f5c4;')));
      h += '<div class="card" style="border-left-color:var(--accent2)">';
      h += '<div style="display:flex;justify-content:space-between;align-items:center">';
      h += '<strong style="color:var(--accent2)">'+dbTypeIcon+' '+esc(db.type)+'</strong>';
      h += '<span style="font-size:10px;color:var(--muted)">'+esc(db.container||'')+(db.repo?' <span style="color:var(--accent);font-weight:500">['+esc(db.repo)+']</span>':'')+'</span>';
      h += '</div>';
      h += '<div style="font-size:11px;margin-top:6px;color:var(--fg)">';
      h += '<span style="color:var(--muted)">host:</span> localhost:' + esc(String(db.port||'?')) + ' &middot; ';
      h += '<span style="color:var(--muted)">user:</span> agentuser &middot; ';
      h += '<span style="color:var(--muted)">db:</span> agentdb';
      h += '</div>';
      if (db.connection_url) {
        h += '<div style="margin-top:4px"><code style="font-size:10px;word-break:break-all;color:var(--accent)">'+esc(db.connection_url)+'</code></div>';
      }
      h += '</div>';
    }
  }
  // Sistema
  var sysSvcs = data._system || [];
  if (sysSvcs.length > 0) {
    h += '<div class="section-label" style="font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;margin:12px 0 8px;font-weight:600">Sistema</div>';
    h += '<div class="card" style="border-color:var(--border-light)">';
    h += '<div class="sys-svc-header"><span>Servei</span><span>Port</span><span>PID</span></div>';
    for (var si = 0; si < sysSvcs.length; si++) {
      var s = sysSvcs[si];
      var icon = s.known ? '&#x1f7e2;' : '&#x26aa;';
      var url = s.port < 65535 ? 'http://localhost:' + s.port : '';
      h += '<div class="sys-svc '+(s.known?'known':'unknown')+'">'+
        '<span class="sys-svc-name">'+icon+' '+esc(s.name)+'</span>'+
        '<span class="sys-svc-port"><a href="'+esc(url)+'" target="_blank" rel="noopener">:'+s.port+'</a></span>'+
        '<span class="sys-svc-pid">'+(s.pid||'?')+'</span>'+
        '</div>';
    }
    h += '</div>';
  }
  document.getElementById('repos-content').innerHTML = h || '<div class="empty">Cap servei</div>';
}
async function stopRepo(name) {
  await apiFetch('/api/stop', {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'repo='+encodeURIComponent(name)});
  flashService(name);
  loadStatus();
}

async function restartRepo(name) {
  showToast('Reiniciant ' + name + '...', 'info');
  await apiFetch('/api/restart', {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'repo='+encodeURIComponent(name)});
  showToast(name + ' reiniciat. Verifica la pestanya Repos.', 'ok');
  flashService(name);
  bumpPolling('repos');
  setTimeout(loadStatus, 5000);
}

async function loadTimeline(repo) {
  const el = document.getElementById('tl-' + repo.replace(/[^a-zA-Z0-9]/g, '_'));
  if (!el) return;
  el.style.display = 'block';
  el.innerHTML = '<span class="spinner"></span> Carregant...';
  try {
    const r = await apiFetch('/api/timeline/' + encodeURIComponent(repo));
    const data = await r.json();
    if (!data.events || !data.events.length) {
      el.innerHTML = '<div class="empty">Cap event</div>';
      return;
    }
    let h = '';
    for (const e of data.events) {
      const cls = e.level === 'error' ? 'bad' : (e.level === 'ok' ? 'ok' : '');
      h += '<div class="timeline-item '+cls+'"><span class="tl-time">'+esc(e.time||'')+'</span> <span class="tl-event">'+esc(e.event)+'</span></div>';
    }
    el.innerHTML = h;
  } catch(e) { el.innerHTML = '<div class="empty">Error</div>'; }
}

// ===== DATABASES =====
async function loadDatabases() {
  try {
    const r = await apiFetch('/api/databases');
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
    const cmd = db.connect_cmd ? '<br><code style="font-size:11px">'+esc(db.connect_cmd)+'</code>' : '';
    h += '<tr><td><strong>'+esc(db.name)+'</strong><br><span class="badge ok">'+esc(db.status||'')+'</span></td><td>'+esc(db.image||'')+'</td><td>'+esc(db.ports||'')+'</td><td style="color:var(--accent)">'+esc(db.connect_url||'')+cmd+'</td></tr>';
  }
  h += '</tbody></table>';
  document.getElementById('db-content').innerHTML = h;
}

// ===== SECRETS =====
async function loadSecrets() {
  try {
    const r = await apiFetch('/api/secrets');
    const data = await r.json();
    renderAiKeys(data.secrets || {}, data.known_key_types || []);
    renderOtherKeys(data.secrets || {});
  } catch(e) { document.getElementById('ai-keys-list').innerHTML = '<div class="empty">Error: '+esc(String(e.message||e))+'</div>'; }
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
  apiFetch('/api/secrets/' + encodeURIComponent(key) + '/toggle', {method:'POST'})
    .then(() => loadSecrets());
}

async function testSecret(provider) {
  const r = await apiFetch('/api/secrets/test/' + provider, {method:'POST'});
  const d = await r.json();
  document.getElementById('secrets-flash').innerHTML = d.ok
    ? '<div class="flash ok">'+esc(d.message)+'</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
}

async function saveSecret(key) {
  const v = document.getElementById('edit-val-'+key).value.trim();
  if (!v) return;
  const r = await apiFetch('/api/secrets/' + encodeURIComponent(key), {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:v})});
  const d = await r.json();
  document.getElementById('secrets-flash').innerHTML = d.ok
    ? '<div class="flash ok">Clau desada</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
  loadSecrets();
}

async function deleteSecret(key) {
  await apiFetch('/api/secrets/' + encodeURIComponent(key), {method:'DELETE'});
  loadSecrets();
}

document.getElementById('secret-save-btn').addEventListener('click', async () => {
  const k = document.getElementById('secret-key').value.trim();
  const v = document.getElementById('secret-val').value.trim();
  if (!k || !v) return;
  const r = await apiFetch('/api/secrets/' + encodeURIComponent(k), {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:v})});
  const d = await r.json();
  document.getElementById('secrets-flash').innerHTML = d.ok
    ? '<div class="flash ok">Clau desada</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
  document.getElementById('secret-key').value = '';
  document.getElementById('secret-val').value = '';
  loadSecrets();
});

// ===== TOOLS =====
function highlightPython(code) {
  return code
    .replace(/(["]{3}[\s\S]*?["]{3}|'{3}[\s\S]*?'{3})/g, '<span class="syn-string">$1</span>')
    .replace(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g, '<span class="syn-string">$1</span>')
    .replace(/(#.*$)/gm, '<span class="syn-comment">$1</span>')
    .replace(/\b(def|class|import|from|return|if|else|elif|for|while|try|except|finally|with|as|yield|async|await|raise|pass|break|continue|and|or|not|in|is|None|True|False)\b/g, '<span class="syn-keyword">$1</span>')
    .replace(/\b([a-zA-Z_]\w*)\s*\(/g, '<span class="syn-func">$1</span>(');
}

function toggleSyntaxPreview() {
  var el = document.getElementById('tool-modal-source');
  var preview = document.getElementById('tool-preview');
  if (el.style.display === 'none') {
    el.style.display = '';
    preview.style.display = 'none';
  } else {
    el.style.display = 'none';
    preview.style.display = 'block';
    preview.innerHTML = highlightPython(el.value);
  }
}

async function loadTools() {
  try {
    const [toolsR, modelR] = await Promise.all([
      apiFetch('/api/tools'),
      apiFetch('/api/model/bartolo')
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
  const r = await apiFetch('/api/tools/' + encodeURIComponent(id) + '/toggle', {method:'POST'});
  const d = await r.json();
  document.getElementById('tools-flash').innerHTML = d.ok
    ? '<div class="flash ok">Tool '+esc(id)+' '+esc(d.status)+'. Reinicia OpenWebUI.</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
  if (d.ok) loadTools();
}

async function viewToolSource(id, name) {
  const r = await apiFetch('/api/tools/' + encodeURIComponent(id) + '/source');
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
  const r = await apiFetch('/api/tools/' + encodeURIComponent(id) + '/source', {
    method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source:source})
  });
  const d = await r.json();
  document.getElementById('tools-flash').innerHTML = d.ok
    ? '<div class="flash ok">'+esc(d.message)+'</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
}

document.getElementById('system-prompt-save').addEventListener('click', async () => {
  const sp = document.getElementById('system-prompt-text').value;
  const r = await apiFetch('/api/model/bartolo', {
    method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({system_prompt:sp})
  });
  const d = await r.json();
  document.getElementById('tools-flash').innerHTML = d.ok
    ? '<div class="flash ok">'+esc(d.message)+'</div>'
    : '<div class="flash error">'+esc(d.error)+'</div>';
});

// ===== SHELL (WebSocket) =====
let shellWs = null;
function shellExec() {
  const cmd = document.getElementById('shell-cmd').value.trim();
  if (!cmd) return;
  const out = document.getElementById('shell-output');
  out.textContent = '$ ' + cmd + '\n';
  if (!shellWs || shellWs.readyState !== WebSocket.OPEN) {
    shellWs = new WebSocket('ws://' + location.host + '/ws/shell');
    shellWs.onmessage = function(e) {
      const d = JSON.parse(e.data);
      if (d.type === 'output') out.textContent += d.line + '\n';
      else if (d.type === 'done') {
        out.textContent += '\n[returncode: ' + d.returncode + ']';
        if (d.history) renderShellHistory(d.history);
      }
      else if (d.type === 'error') out.textContent += 'ERROR: ' + d.error + '\n';
      out.scrollTop = out.scrollHeight;
    };
    shellWs.onclose = function() { shellWs = null; };
    shellWs.onopen = function() { shellWs.send(JSON.stringify({cmd:cmd})); };
  } else {
    shellWs.send(JSON.stringify({cmd:cmd}));
  }
  document.getElementById('shell-cmd').value = '';
}

function renderShellHistory(history) {
  var area = document.getElementById('shell-history-area');
  area.style.display = 'block';
  var list = document.getElementById('shell-history-list');
  list.innerHTML = history.slice(-10).map(function(c, i) {
    return '<div style="cursor:pointer;color:var(--accent);padding:2px 0" data-shell-history="'+i+'">'+esc(c)+'</div>';
  }).join('');
}

document.getElementById('shell-exec-btn').addEventListener('click', shellExec);
document.getElementById('shell-cmd').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') { e.preventDefault(); shellExec(); }
});

// ===== LAUNCH =====
document.getElementById('launch-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const params = new URLSearchParams(fd);
  const r = await apiFetch('/api/launch', {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:params});
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

// ===== REPAIR HISTORY =====
async function loadRepairHistory() {
  try {
    var res = await apiFetch('/api/repair-history?limit=50');
    var tbody = document.getElementById('repairs-tbody');
    if (!res.entries || !res.entries.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px">Cap reparacio registrada. Quan Bartolo corregeixi errors durant un muntatge, apareixeran aqui.</td></tr>';
      return;
    }
    var sourceBadge = {kb:'ok',ollama:'info',deepseek:'warn',anthropic:'warn',fallback:'info'};
    var html = '';
    res.entries.forEach(function(e) {
      var ts = e.timestamp ? e.timestamp.slice(0,16).replace('T',' ') : '';
      var badgeCls = sourceBadge[e.source] || 'info';
      html += '<tr>' +
        '<td style="white-space:nowrap;font-size:10px;color:var(--muted)">' + esc(ts) + '</td>' +
        '<td>' + esc(e.repo_name || '-') + '</td>' +
        '<td><span class="badge info">' + esc(e.stack) + '</span></td>' +
        '<td><span class="badge bad">' + esc(e.error_type) + '</span></td>' +
        '<td><span class="repair-cmd" title="' + esc(e.fix_command||'') + '">' + esc(e.fix_command||'') + '</span></td>' +
        '<td><span class="badge ' + badgeCls + '">' + esc(e.source) + '</span></td>' +
        '</tr>';
    });
    tbody.innerHTML = html;
  } catch(err) { /* silencios */ }
}

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
    // Find or create logs panel
    let panelId = 'logs-' + repo.replace(/[^a-zA-Z0-9]/g, '_');
    let panel = document.getElementById(panelId);
    let svcDiv = logEl.closest('.svc');
    if (!panel && svcDiv) {
      panel = document.createElement('div');
      panel.id = panelId;
      panel.className = 'logs-panel show';
      svcDiv.appendChild(panel);
    }
    if (panel) {
      panel.textContent = 'Carregant...';
      apiFetch('/api/logs?repo=' + encodeURIComponent(repo) + '&step=' + encodeURIComponent(step))
        .then(r => r.text())
        .then(text => { panel.textContent = text; })
        .catch(() => { panel.textContent = 'Error'; });
    }
    return;
  }
  const liveEl = e.target.closest('[data-live-logs]');
  if (liveEl) {
    const repo = decodeURIComponent(liveEl.getAttribute('data-live-logs'));
    connectLogsWS(repo);
    return;
  }
  // Repos - restart
  const restartEl = e.target.closest('[data-restart-repo]');
  if (restartEl) {
    const repo = decodeURIComponent(restartEl.getAttribute('data-restart-repo'));
    restartRepo(repo);
    return;
  }
  // Repos - timeline
  const tlEl = e.target.closest('[data-load-timeline]');
  if (tlEl) {
    loadTimeline(decodeURIComponent(tlEl.getAttribute('data-load-timeline')));
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

// Keyboard help toggle
document.getElementById('kb-help-btn').addEventListener('click', function(e) {
  e.stopPropagation();
  document.getElementById('kb-panel').classList.toggle('show');
});
document.addEventListener('click', function() {
  document.getElementById('kb-panel').classList.remove('show');
});

// Nav tab navigation
document.querySelectorAll('nav a[data-tab]').forEach(function(a) {
  a.addEventListener('click', function(e) {
    e.preventDefault();
    var t = this.getAttribute('data-tab');
    switchTab(t);
    localStorage.setItem('bartolo-tab', t);
  });
});

// Set hostname in nav
var _info = document.getElementById('sys-info');
if (_info) document.getElementById('nav-hostname').textContent = _info.dataset.hostname || '';

// WebSocket chat
connectWS();

// Load threads and history
loadThreads();
loadInputHistory();

let _loadingCount = 0;

// Init: activate stored tab and load its data
const activeTab = localStorage.getItem('bartolo-tab') || 'visio';
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
  if (e.ctrlKey && !e.shiftKey && !e.altKey && e.key >= '1' && e.key <= '9') {
    e.preventDefault();
    var idx = parseInt(e.key) - 1;
    if (idx < TAB_ORDER.length) switchTab(TAB_ORDER[idx]);
  }
  if (e.ctrlKey && e.key === 'n') {
    e.preventDefault();
    createThread();
  }
  if (e.ctrlKey && e.key === 'w') {
    e.preventDefault();
    if (_currentThreadId) deleteThread(_currentThreadId);
  }
});
// ===== OVERVIEW =====
const TAB_ORDER = ['visio','chat','models','repos','databases','secrets','tools','shell','launch'];

async function loadOverview() {
  try {
    const [statusR, modelsR, dbR, timelineR] = await Promise.all([
      apiFetch('/api/status'),
      apiFetch('/api/models'),
      apiFetch('/api/databases'),
      apiFetch('/api/timeline')
    ]);
    const status = await statusR.json();
    const models = await modelsR.json();
    const db = await dbR.json();
    const tl = await timelineR.json();
    renderOverview(status, models, db, tl);
  } catch(e) {}
}

function renderOverview(status, models, db, tl) {
  const repos = Object.entries(status).filter(function(e) { return !e[0].startsWith('_'); });
  let activeRepos = 0, stoppedRepos = 0, running = 0, stopped = 0;
  repos.forEach(function(e) {
    var svcs = e[1];
    if (!svcs || !svcs.length) return;
    var hasRunning = false, hasStopped = false;
    svcs.forEach(function(s) {
      if (s.pid) { running++; hasRunning = true; }
      else { stopped++; hasStopped = true; }
    });
    if (hasRunning) activeRepos++;
    else if (hasStopped) stoppedRepos++;
  });
  document.getElementById('visio-repos').innerHTML =
    '<span class="stat-num">'+activeRepos+'</span><span class="stat-label"> actius</span> &middot; ' +
    '<span class="stat-num" style="color:var(--muted)">'+running+'</span><span class="stat-label"> serveis</span>';

  // Timeline
  var tlEvents = (tl && tl.events) ? tl.events : [];
  var tlHtml = '';
  if (tlEvents.length) {
    for (var i = 0; i < Math.min(tlEvents.length, 15); i++) {
      var e = tlEvents[i];
      var cls = e.level === 'error' ? 'bad' : (e.level === 'ok' ? 'ok' : '');
      tlHtml += '<div class="timeline-item '+cls+'"><span class="tl-time">'+esc(e.time||'')+'</span> <span class="tl-event">'+esc(e.event)+'</span></div>';
    }
  } else {
    tlHtml = '<div class="timeline-item"><span class="tl-event" style="color:var(--muted)">Cap event recent</span></div>';
  }
  document.getElementById('visio-timeline').innerHTML = tlHtml;

  var modelCount = (models.models || []).length;
  var modelNames = (models.models || []).slice(0,3).map(function(m) { return m.name; }).join(', ');
  document.getElementById('visio-models').innerHTML =
    '<span class="stat-num">'+modelCount+'</span><span class="stat-label"> models</span>' +
    (modelNames ? '<div style="font-size:11px;color:var(--muted);margin-top:4px">'+esc(modelNames)+'</div>' : '');

  var dbCount = (db.containers || []).length;
  document.getElementById('visio-databases').innerHTML =
    '<span class="stat-num">'+dbCount+'</span><span class="stat-label"> contenidors</span>';

  var info = document.getElementById('sys-info');
  var uptime = Math.floor((Date.now()/1000) - parseInt(info.dataset.startTime));
  var h = Math.floor(uptime/3600), m = Math.floor((uptime%3600)/60);
  var sysSvcs = (status._system || []);
  var sysKnown = sysSvcs.filter(function(s) { return s.known; }).length;
  document.getElementById('visio-system').innerHTML =
    '<span class="stat-num">'+info.dataset.hostname+'</span>' +
    '<div class="stat-label">Python '+info.dataset.python+' &middot; uptime '+h+'h '+m+'m</div>' +
    '<div class="stat-label" style="margin-top:4px">'+sysSvcs.length+' ports oberts &middot; '+sysKnown+' coneguts</div>';
}

// ===== GLOBAL LOADING INDICATOR =====
function startLoading() { _loadingCount++; updateLoadingBar(); }
function stopLoading() { _loadingCount = Math.max(0, _loadingCount - 1); updateLoadingBar(); }
function updateLoadingBar() {
  var bar = document.getElementById('global-loading-bar');
  bar.style.width = _loadingCount > 0 ? '100%' : '0';
  bar.style.opacity = _loadingCount > 0 ? '1' : '0';
}
async function apiFetch(url, opts) {
  startLoading();
  try { return await fetch(url, opts); }
  finally { stopLoading(); }
}

// ===== GREEN FLASH =====
function flashService(repo) {
  var cards = document.querySelectorAll('.card');
  cards.forEach(function(card) {
    var h2 = card.querySelector('h2');
    if (h2 && h2.textContent === repo) {
      var svcs = card.querySelectorAll('.svc');
      svcs.forEach(function(svc) {
        svc.classList.add('flash-ok');
        setTimeout(function() { svc.classList.remove('flash-ok'); }, 2000);
      });
    }
  });
}

// ===== LIVE LOGS =====
let _logsWs = null;
function connectLogsWS(repo) {
  if (_logsWs) _logsWs.close();
  var safeId = 'logs-stream-' + repo.replace(/[^a-zA-Z0-9]/g, '_');
  var panel = document.getElementById(safeId);
  if (!panel) {
    panel = document.createElement('div');
    panel.id = safeId;
    panel.className = 'logs-stream show';
    var reposContent = document.getElementById('repos-content');
    reposContent.insertBefore(panel, reposContent.firstChild);
  }
  panel.textContent = 'Connectant...\n';
  _logsWs = new WebSocket('ws://' + location.host + '/ws/logs/' + encodeURIComponent(repo));
  _logsWs.onmessage = function(e) {
    var d = JSON.parse(e.data);
    if (d.type === 'init') {
      panel.textContent = d.lines.join('\n') + '\n';
    } else if (d.type === 'line') {
      panel.textContent += d.text + '\n';
      panel.scrollTop = panel.scrollHeight;
    }
  };
  _logsWs.onclose = function() {
    panel.textContent += '\n--- logs desconnectats ---';
  };
}

function disconnectLogsWS() {
  if (_logsWs) { _logsWs.close(); _logsWs = null; }
}

"""

INDEX_HTML = (
    '<!doctype html>\n<html lang="ca">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<title>Bartolo Control Center</title>\n<style>\n'
    + _CSS +
    '\n</style>\n</head>\n<body>\n'
    '<div id="global-loading-bar"></div>\n'
    '<div id="sys-info" data-hostname="HOST" data-python="PY" data-start-time="TIME" hidden></div>\n'
    + _HTML_BODY +
    '\n<div id="toast-container"></div>\n<script>\n'
    + _JS +
    '\n</script>\n</body>\n</html>'
)


def render_index() -> str:
    import socket
    import sys
    import time as _time
    _hostname = socket.gethostname()
    _python_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    _start = int(_time.time())
    html = INDEX_HTML
    html = html.replace('data-hostname="HOST"', f'data-hostname="{_hostname}"')
    html = html.replace('data-python="PY"', f'data-python="{_python_ver}"')
    html = html.replace('data-start-time="TIME"', f'data-start-time="{_start}"')
    return html


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
