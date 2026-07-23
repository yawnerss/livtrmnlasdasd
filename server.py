#!/usr/bin/env python3
import os
import time
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-this-secret-key-in-production'
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, ping_interval=25)

clients = {}
terminal_sessions = {}
session_owners = {}
client_watchers = {}

HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remote Terminal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@4.18.0/css/xterm.css">
    <script src="https://cdn.jsdelivr.net/npm/xterm@4.18.0/lib/xterm.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.5.0/lib/xterm-addon-fit.js"></script>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        :root {
            --bg-primary: #0b0e14; --bg-secondary: #151a23; --bg-card: #1e2531;
            --accent: #5e9eff; --accent2: #50fa7b; --danger: #ff5555;
            --text: #e0e6f0; --text-muted: #8492a6; --border: #2a3343;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body { background: var(--bg-primary); color: var(--text); font-family: 'Segoe UI', sans-serif; display:flex; height:100vh; overflow:hidden; }
        .sidebar { width:240px; background:var(--bg-secondary); border-right:1px solid var(--border); padding:1rem; overflow-y:auto; }
        .sidebar h5 { color:var(--text-muted); text-transform:uppercase; font-size:0.75rem; margin-bottom:1rem; }
        .client-card { background:var(--bg-card); border-radius:12px; padding:0.8rem; margin-bottom:0.6rem; cursor:pointer; transition:all 0.2s; border-left:4px solid transparent; }
        .client-card:hover { border-color:var(--accent); }
        .client-card.active { border-color:var(--accent2); background:linear-gradient(135deg, rgba(80,250,123,0.05), rgba(94,158,255,0.05)); }
        .client-name { font-weight:600; }
        .metric-badge { font-size:0.7rem; background:rgba(0,0,0,0.3); padding:0.15rem 0.5rem; border-radius:20px; margin-right:0.3rem; display:inline-block; }
        .main-panel { flex:1; display:flex; flex-direction:column; overflow:hidden; }
        .dashboard-header { padding:1rem 1.5rem; border-bottom:1px solid var(--border); }
        .metrics-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap:0.8rem; }
        .metric-card { background:var(--bg-card); border-radius:12px; padding:1rem; display:flex; flex-direction:column; }
        .metric-header { display:flex; align-items:center; gap:0.5rem; margin-bottom:0.5rem; }
        .metric-title { font-size:0.7rem; text-transform:uppercase; color:var(--text-muted); }
        .metric-main { font-size:1.8rem; font-weight:700; }
        .metric-detail { font-size:0.75rem; color:var(--text-muted); margin-top:0.2rem; }
        .progress { height:6px; margin-top:0.5rem; background:rgba(255,255,255,0.05); border-radius:3px; overflow:hidden; }
        .progress-bar { height:100%; border-radius:3px; background:var(--accent); }
        .content-area { flex:1; display:flex; flex-direction:column; padding:0 1.5rem 1.5rem; overflow:hidden; }
        .tab-nav { display:flex; gap:0.5rem; margin-bottom:0.8rem; }
        .tab-btn { background:var(--bg-card); border:none; color:var(--text); padding:0.5rem 1.5rem; border-radius:20px; font-size:0.85rem; cursor:pointer; transition:0.2s; }
        .tab-btn.active { background:var(--accent); color:#0b0e14; }
        .tab-content { flex:1; overflow:hidden; display:none; }
        .tab-content.active { display:flex; flex-direction:column; }
        .terminal-panel { flex:1; background:#0a0e17; border-radius:12px; overflow:hidden; display:flex; flex-direction:column; }
        .terminal-tabs { display:flex; align-items:center; background:#151a23; padding:0.4rem; gap:0.3rem; }
        .term-tab { background:#1e2531; border:none; color:var(--text); padding:0.2rem 0.8rem; border-radius:6px; font-size:0.8rem; display:flex; align-items:center; gap:0.4rem; }
        .term-tab.active { background:var(--accent); color:#0b0e14; }
        .close-term { cursor:pointer; color:var(--danger); opacity:0.7; font-size:0.9rem; }
        .close-term:hover { opacity:1; }
        #terminal-container { flex:1; padding:0.5rem; }
        .fullscreen-btn { margin-left:auto; background:transparent; border:none; color:var(--text-muted); cursor:pointer; font-size:1rem; }
        .fullscreen-btn:hover { color:var(--text); }
        .process-panel { flex:1; overflow:auto; background:var(--bg-card); border-radius:12px; }
        .process-table { width:100%; border-collapse:collapse; }
        .process-table th, .process-table td { padding:0.5rem 1rem; text-align:left; border-bottom:1px solid var(--border); }
        .process-table th { background:rgba(0,0,0,0.3); font-size:0.75rem; text-transform:uppercase; }
        .kill-btn { background:var(--danger); border:none; color:white; padding:0.2rem 0.6rem; border-radius:4px; cursor:pointer; font-size:0.75rem; }
        .refresh-btn { background:var(--accent); border:none; color:#0b0e14; padding:0.2rem 1rem; border-radius:20px; font-size:0.8rem; cursor:pointer; margin:1rem; }
        #no-client { display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; color:var(--text-muted); }
    </style>
</head>
<body>
<div class="sidebar" id="sidebar">
    <h5><i class="fas fa-terminal"></i> Clients</h5>
    <div id="client-list"></div>
</div>
<div class="main-panel">
    <div id="no-client">
        <i class="fas fa-plug fa-3x"></i>
        <p class="mt-3">Select a client to start managing terminals.</p>
    </div>
    <div id="client-dashboard" style="display:none;">
        <div class="dashboard-header">
            <div class="metrics-grid" id="metrics-grid"></div>
        </div>
        <div class="content-area">
            <div class="tab-nav">
                <button class="tab-btn active" data-tab="terminal">Terminals</button>
                <button class="tab-btn" data-tab="processes">Processes</button>
            </div>
            <div class="tab-content active" id="tab-terminal">
                <div class="terminal-panel" id="terminal-panel">
                    <div class="terminal-tabs" id="term-tab-bar">
                        <button id="new-terminal-btn" class="term-tab"><i class="fas fa-plus"></i> New</button>
                        <button id="refresh-terminal-btn" class="term-tab" title="Restart current terminal"><i class="fas fa-sync-alt"></i> Refresh</button>
                        <button id="fullscreen-btn" class="fullscreen-btn" title="Fullscreen"><i class="fas fa-expand"></i></button>
                    </div>
                    <div id="terminal-container"></div>
                </div>
            </div>
            <div class="tab-content" id="tab-processes">
                <button id="refresh-processes-btn" class="refresh-btn"><i class="fas fa-sync-alt"></i> Refresh</button>
                <div class="process-panel">
                    <table class="process-table">
                        <thead><tr><th>PID</th><th>Name</th><th>CPU%</th><th>MEM%</th><th>Action</th></tr></thead>
                        <tbody id="process-tbody"><tr><td colspan="5" style="text-align:center; padding:2rem;">Click Refresh to load</td></tr></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
const socket = io();
let currentClient = null;
let terminals = {};
let terminalSessions = {};

function renderClientList(clients) {
    const container = document.getElementById('client-list');
    container.innerHTML = '';
    for (const [sid, data] of Object.entries(clients)) {
        const card = document.createElement('div');
        card.className = `client-card${sid === currentClient ? ' active' : ''}`;
        card.dataset.sid = sid;
        card.innerHTML = `<div class="client-name">${data.name || 'Unknown'}</div>
            <div>
                <span class="metric-badge"><i class="fas fa-microchip"></i> ${data.metrics?.cpu || '--'}%</span>
                <span class="metric-badge"><i class="fas fa-memory"></i> ${data.metrics?.ram_percent || '--'}%</span>
                <span class="metric-badge"><i class="fas fa-wifi"></i> ${data.metrics?.net_speed || '--'}</span>
            </div>`;
        card.addEventListener('click', () => selectClient(sid));
        container.appendChild(card);
    }
}

function selectClient(sid) {
    // If same client is already active, just show the existing terminal (do nothing destructive)
    if (sid === currentClient) {
        // If there are no terminals yet, create one
        if (Object.keys(terminals).length === 0) {
            createNewTerminal();
        } else {
            // Otherwise just switch to the first existing terminal
            switchTerminal(Object.keys(terminals)[0]);
        }
        return;
    }

    // Different client selected: clean up old terminals and prepare new dashboard
    currentClient = sid;
    document.querySelectorAll('.client-card').forEach(c => c.classList.remove('active'));
    document.querySelector(`.client-card[data-sid="${sid}"]`)?.classList.add('active');
    document.getElementById('no-client').style.display = 'none';
    document.getElementById('client-dashboard').style.display = 'block';
    // Dispose all existing terminals
    Object.values(terminals).forEach(t => t.dispose());
    terminals = {};
    terminalSessions = {};
    document.getElementById('terminal-container').innerHTML = '';
    const tabBar = document.getElementById('term-tab-bar');
    while (tabBar.children.length > 3) tabBar.removeChild(tabBar.lastChild); // keep New, Refresh, Fullscreen
    document.getElementById('process-tbody').innerHTML = '<tr><td colspan="5" style="text-align:center; padding:2rem;">Click Refresh to load</td></tr>';
    switchMainTab('terminal');
    document.querySelectorAll('.tab-btn[data-tab="terminal"]')[0].classList.add('active');
    socket.emit('request_metrics', sid);
    createNewTerminal();
}

function switchMainTab(tabName) {
    document.querySelectorAll('.tab-btn[data-tab]').forEach(b => b.classList.remove('active'));
    document.querySelector(`.tab-btn[data-tab="${tabName}"]`)?.classList.add('active');
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`tab-${tabName}`).classList.add('active');
}

document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
        switchMainTab(btn.dataset.tab);
        if (btn.dataset.tab === 'processes' && currentClient) socket.emit('get_processes', currentClient);
    });
});

const fullscreenBtn = document.getElementById('fullscreen-btn');
const terminalPanel = document.getElementById('terminal-panel');
fullscreenBtn.addEventListener('click', () => {
    if (!document.fullscreenElement) terminalPanel.requestFullscreen();
    else document.exitFullscreen();
});
document.addEventListener('fullscreenchange', () => {
    const icon = fullscreenBtn.querySelector('i');
    icon.classList.toggle('fa-expand', !document.fullscreenElement);
    icon.classList.toggle('fa-compress', !!document.fullscreenElement);
    Object.values(terminals).forEach(t => t._addon?.fit());
});

function createNewTerminal() {
    if (!currentClient) return;
    socket.emit('new_terminal', currentClient, (sessionId) => {
        if (!sessionId) { console.error("No session ID"); return; }
        const tabBar = document.getElementById('term-tab-bar');
        const tab = document.createElement('button');
        tab.className = 'term-tab';
        tab.dataset.session = sessionId;
        tab.innerHTML = `Term ${Object.keys(terminals).length + 1} <span class="close-term" data-session="${sessionId}">×</span>`;
        tab.addEventListener('click', (e) => { if (!e.target.classList.contains('close-term')) switchTerminal(sessionId); });
        tab.querySelector('.close-term').addEventListener('click', (e) => { e.stopPropagation(); closeTerminal(sessionId); });
        const refreshBtn = document.getElementById('refresh-terminal-btn');
        tabBar.insertBefore(tab, refreshBtn);

        const termDiv = document.createElement('div');
        termDiv.id = `term-${sessionId}`;
        termDiv.style.display = 'none';
        termDiv.style.height = '100%';
        document.getElementById('terminal-container').appendChild(termDiv);

        const term = new Terminal({ cursorBlink: true, theme: { background: '#0a0e17', foreground: '#e0e6f0' } });
        term.open(termDiv);
        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term._addon = fitAddon;
        fitAddon.fit();
        terminals[sessionId] = term;
        terminalSessions[sessionId] = true;

        term.onResize(size => socket.emit('terminal_resize', { sessionId, cols: size.cols, rows: size.rows }));
        term.onData(data => socket.emit('terminal_input', { sessionId, data }));

        switchTerminal(sessionId);
        new ResizeObserver(() => fitAddon.fit()).observe(termDiv);
        setTimeout(() => fitAddon.fit(), 100);
    });
}

function switchTerminal(sessionId) {
    document.querySelectorAll('.term-tab').forEach(b => b.classList.remove('active'));
    document.querySelector(`.term-tab[data-session="${sessionId}"]`)?.classList.add('active');
    document.querySelectorAll('#terminal-container > div').forEach(d => d.style.display = 'none');
    const target = document.getElementById(`term-${sessionId}`);
    if (target) target.style.display = 'block';
}

function closeTerminal(sessionId) {
    socket.emit('close_terminal', { sessionId });
    document.querySelector(`.term-tab[data-session="${sessionId}"]`)?.remove();
    document.getElementById(`term-${sessionId}`)?.remove();
    terminals[sessionId]?.dispose();
    delete terminals[sessionId];
    delete terminalSessions[sessionId];
    if (Object.keys(terminals).length === 0) createNewTerminal();
    else switchTerminal(Object.keys(terminals)[0]);
}

// Refresh button: restart the active terminal
document.getElementById('refresh-terminal-btn').addEventListener('click', () => {
    const activeTab = document.querySelector('.term-tab.active');
    if (activeTab) {
        const sessionId = activeTab.dataset.session;
        closeTerminal(sessionId);  // this will spawn a new one
    } else if (currentClient) {
        createNewTerminal();
    }
});

document.getElementById('new-terminal-btn').addEventListener('click', createNewTerminal);

function updateMetricsUI(metrics) {
    const grid = document.getElementById('metrics-grid');
    grid.innerHTML = `
        <div class="metric-card">
            <div class="metric-header"><i class="fas fa-microchip"></i><span class="metric-title">CPU</span></div>
            <div class="metric-main">${metrics.cpu || 0}%</div>
            <div class="metric-detail">${metrics.cpu_model || 'Unknown'} (${metrics.cpu_cores || 'N/A'} cores)</div>
            <div class="progress"><div class="progress-bar" style="width:${metrics.cpu || 0}%"></div></div>
        </div>
        <div class="metric-card">
            <div class="metric-header"><i class="fas fa-memory"></i><span class="metric-title">RAM</span></div>
            <div class="metric-main">${metrics.ram_percent || 0}%</div>
            <div class="metric-detail">${metrics.used_ram || '0'} / ${metrics.total_ram || 'N/A'}</div>
            <div class="progress"><div class="progress-bar" style="width:${metrics.ram_percent || 0}%; background:#50fa7b;"></div></div>
        </div>
        <div class="metric-card">
            <div class="metric-header"><i class="fas fa-hdd"></i><span class="metric-title">Disk</span></div>
            <div class="metric-main">${metrics.disk_percent || 0}%</div>
            <div class="metric-detail">${metrics.disk_used || '0'} / ${metrics.disk_total || 'N/A'}</div>
            <div class="progress"><div class="progress-bar" style="width:${metrics.disk_percent || 0}%; background:#f1fa8c;"></div></div>
        </div>
        <div class="metric-card">
            <div class="metric-header"><i class="fas fa-wifi"></i><span class="metric-title">Network</span></div>
            <div class="metric-main">↓ ${metrics.net_down || '0'}</div>
            <div class="metric-detail">↑ ${metrics.net_up || '0'}</div>
        </div>`;
}

function renderProcessTable(procs) {
    const tbody = document.getElementById('process-tbody');
    if (!procs?.length) { tbody.innerHTML = '<tr><td colspan="5">No processes</td></tr>'; return; }
    tbody.innerHTML = procs.map(p => `<tr>
        <td>${p.pid}</td><td>${p.name}</td><td>${p.cpu_percent ?? 0}%</td><td>${p.mem_percent ?? 0}%</td>
        <td><button class="kill-btn" data-pid="${p.pid}">Kill</button></td>
    </tr>`).join('');
    document.querySelectorAll('.kill-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const pid = btn.dataset.pid;
            if (currentClient) socket.emit('kill_process', { target_sid: currentClient, pid: parseInt(pid) });
            btn.textContent = 'Killed'; btn.disabled = true;
            setTimeout(() => { btn.textContent = 'Kill'; btn.disabled = false; }, 2000);
        });
    });
}

document.getElementById('refresh-processes-btn')?.addEventListener('click', () => {
    if (currentClient) socket.emit('get_processes', currentClient);
});

socket.on('connect', () => console.log('Connected'));
socket.on('client_list', renderClientList);
socket.on('metrics_update', data => { if (currentClient === data.sid) updateMetricsUI(data.metrics); });
socket.on('terminal_output', data => { terminals[data.sessionId]?.write(data.output); });
socket.on('process_list', data => { if (data.target_sid === currentClient) renderProcessTable(data.processes); });
socket.emit('get_clients');
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

# Helper
def broadcast_client_list():
    emit('client_list', {
        sid: {'name': info['name'], 'metrics': info['metrics']}
        for sid, info in clients.items()
    }, broadcast=True)

# SocketIO events (exactly as before)
@socketio.on('connect')
def handle_connect(auth=None):
    print(f"[+] Connected: {request.sid}")
    clients[request.sid] = {'name': request.sid[:8], 'metrics': {}}
    terminal_sessions[request.sid] = {}
    broadcast_client_list()

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    dead = [s for s, owner in session_owners.items() if owner == sid]
    for s in dead:
        del session_owners[s]
    client_watchers.pop(sid, None)
    for client_sid in list(client_watchers):
        if client_watchers[client_sid] == sid:
            del client_watchers[client_sid]
    clients.pop(sid, None)
    terminal_sessions.pop(sid, None)
    broadcast_client_list()

@socketio.on('register_client')
def handle_register(data):
    name = data.get('name', request.sid[:8])
    if request.sid in clients:
        clients[request.sid]['name'] = name
    broadcast_client_list()

@socketio.on('get_clients')
def handle_get_clients():
    emit('client_list', {
        sid: {'name': info['name'], 'metrics': info['metrics']}
        for sid, info in clients.items()
    })

@socketio.on('request_metrics')
def handle_request_metrics(target_sid):
    if target_sid in clients:
        emit('metrics_update', {'sid': target_sid, 'metrics': clients[target_sid]['metrics']})

@socketio.on('metrics')
def handle_metrics(data):
    if request.sid not in clients:
        return
    clients[request.sid]['metrics'] = data.get('metrics', {})
    browser_sid = client_watchers.get(request.sid)
    if browser_sid:
        emit('metrics_update', {'sid': request.sid, 'metrics': clients[request.sid]['metrics']}, room=browser_sid)
    broadcast_client_list()

@socketio.on('new_terminal')
def handle_new_terminal(target_sid):
    browser_sid = request.sid
    session_id = f"term_{int(time.time())}_{target_sid[:4]}"
    client_watchers[target_sid] = browser_sid
    session_owners[session_id] = target_sid
    terminal_sessions.setdefault(target_sid, {})[session_id] = {'created': True}
    emit('spawn_terminal', {'session_id': session_id}, room=target_sid)
    return session_id

@socketio.on('terminal_ready')
def handle_terminal_ready(data):
    pass

@socketio.on('terminal_input')
def handle_terminal_input(data):
    session_id = data.get('sessionId')
    target_sid = session_owners.get(session_id)
    if target_sid:
        emit('terminal_input', {'session_id': session_id, 'data': data.get('data')}, room=target_sid)

@socketio.on('terminal_resize')
def handle_terminal_resize(data):
    session_id = data.get('sessionId')
    target_sid = session_owners.get(session_id)
    if target_sid:
        emit('terminal_resize', {'session_id': session_id, 'cols': data.get('cols'), 'rows': data.get('rows')}, room=target_sid)

@socketio.on('close_terminal')
def handle_close_terminal(data):
    session_id = data.get('sessionId')
    target_sid = session_owners.get(session_id)
    if target_sid:
        emit('close_terminal', {'session_id': session_id}, room=target_sid)
        terminal_sessions.get(target_sid, {}).pop(session_id, None)
        session_owners.pop(session_id, None)

@socketio.on('terminal_output')
def handle_terminal_output(data):
    browser_sid = client_watchers.get(request.sid)
    if browser_sid:
        emit('terminal_output', {'sessionId': data.get('session_id'), 'output': data.get('output', '')}, room=browser_sid)

@socketio.on('get_processes')
def handle_get_processes(target_sid):
    if target_sid in clients:
        emit('list_processes', {}, room=target_sid)

@socketio.on('process_list')
def handle_process_list(data):
    browser_sid = client_watchers.get(request.sid)
    if browser_sid:
        emit('process_list', {'target_sid': request.sid, 'processes': data.get('processes', [])}, room=browser_sid)

@socketio.on('kill_process')
def handle_kill_process(data):
    target_sid = data.get('target_sid')
    pid = data.get('pid')
    if target_sid and pid is not None:
        emit('kill_process', {'pid': pid}, room=target_sid)

@socketio.on('ping')
def handle_ping():
    emit('pong')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
