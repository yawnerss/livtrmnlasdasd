#!/usr/bin/env python3
import os
import time
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-this-secret-key-in-production'

# Default threading mode – no extra dependencies needed
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, ping_interval=25)

clients = {}
terminal_sessions = {}
session_owners = {}
client_watchers = {}

HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BlackHat Remote • Modern Terminal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm/css/xterm.css">
    <script src="https://cdn.jsdelivr.net/npm/xterm/lib/xterm.js"></script>
    <!-- Pinned version that exposes global FitAddon -->
    <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.5.0/lib/xterm-addon-fit.js"></script>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-primary: #0b0e14;
            --bg-secondary: #151a23;
            --bg-card: #1e2531;
            --accent: #5e9eff;
            --accent2: #50fa7b;
            --danger: #ff5555;
            --text: #e0e6f0;
            --text-muted: #8492a6;
            --border: #2a3343;
            --sidebar-width: 240px;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: var(--bg-primary);
            color: var(--text);
            font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
            display: flex;
            height: 100vh;
            overflow: hidden;
        }
        .sidebar {
            width: var(--sidebar-width);
            background: var(--bg-secondary);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            padding: 1rem;
            overflow-y: auto;
        }
        .sidebar h5 {
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 0.75rem;
            margin-bottom: 1rem;
        }
        .client-card {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 0.8rem;
            margin-bottom: 0.6rem;
            cursor: pointer;
            transition: all 0.2s ease;
            border: 1px solid transparent;
        }
        .client-card:hover {
            border-color: var(--accent);
            box-shadow: 0 4px 15px rgba(94,158,255,0.08);
        }
        .client-card.active {
            border-color: var(--accent2);
            background: linear-gradient(135deg, rgba(80,250,123,0.05) 0%, rgba(94,158,255,0.05) 100%);
        }
        .client-name {
            font-weight: 600;
            margin-bottom: 0.4rem;
        }
        .metric-badge {
            font-size: 0.7rem;
            background: rgba(0,0,0,0.3);
            padding: 0.15rem 0.5rem;
            border-radius: 20px;
            margin-right: 0.3rem;
            display: inline-block;
            margin-bottom: 0.2rem;
        }
        .main-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .dashboard-header {
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--border);
        }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px,1fr));
            gap: 0.8rem;
        }
        .metric-card {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 1rem;
            display: flex;
            flex-direction: column;
        }
        .metric-header {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
        }
        .metric-icon {
            font-size: 1.2rem;
            width: 28px;
            text-align: center;
        }
        .metric-title {
            font-size: 0.7rem;
            text-transform: uppercase;
            color: var(--text-muted);
            letter-spacing: 0.5px;
        }
        .metric-main {
            font-size: 1.8rem;
            font-weight: 700;
            line-height: 1.2;
        }
        .metric-detail {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 0.2rem;
        }
        .progress {
            height: 6px;
            margin-top: 0.5rem;
            background: rgba(255,255,255,0.05);
            border-radius: 3px;
            overflow: hidden;
        }
        .progress-bar {
            height: 100%;
            border-radius: 3px;
            background: var(--accent);
        }
        .content-area {
            flex: 1;
            display: flex;
            flex-direction: column;
            padding: 0 1.5rem 1.5rem;
            overflow: hidden;
        }
        .tab-nav {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 0.8rem;
        }
        .tab-btn {
            background: var(--bg-card);
            border: none;
            color: var(--text);
            padding: 0.5rem 1.5rem;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }
        .tab-btn.active {
            background: var(--accent);
            color: #0b0e14;
        }
        .tab-btn:hover:not(.active) {
            background: #2a3343;
        }
        .tab-content {
            flex: 1;
            overflow: hidden;
            display: none;
        }
        .tab-content.active {
            display: flex;
            flex-direction: column;
        }
        .terminal-panel {
            flex: 1;
            background: #0a0e17;
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        .terminal-tabs {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            background: #151a23;
            padding: 0.4rem;
            gap: 0.3rem;
        }
        .term-tab {
            background: #1e2531;
            border: none;
            color: var(--text);
            padding: 0.2rem 0.8rem;
            border-radius: 6px;
            font-size: 0.8rem;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }
        .term-tab.active {
            background: var(--accent);
            color: #0b0e14;
        }
        .close-term {
            cursor: pointer;
            color: var(--danger);
            opacity: 0.7;
            font-size: 0.9rem;
        }
        .close-term:hover { opacity: 1; }
        #terminal-container {
            flex: 1;
            padding: 0.5rem;
        }
        .fullscreen-btn {
            margin-left: auto;
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            font-size: 1rem;
            padding: 0.3rem 0.6rem;
            border-radius: 6px;
            transition: 0.2s;
        }
        .fullscreen-btn:hover {
            background: rgba(255,255,255,0.1);
            color: var(--text);
        }
        .process-panel {
            flex: 1;
            overflow: auto;
            background: var(--bg-card);
            border-radius: 12px;
        }
        .process-table {
            width: 100%;
            border-collapse: collapse;
            color: var(--text);
        }
        .process-table th, .process-table td {
            padding: 0.5rem 1rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }
        .process-table th {
            background: rgba(0,0,0,0.3);
            font-size: 0.75rem;
            text-transform: uppercase;
            color: var(--text-muted);
        }
        .process-table tr:hover {
            background: rgba(94,158,255,0.05);
        }
        .kill-btn {
            background: var(--danger);
            border: none;
            color: white;
            padding: 0.2rem 0.6rem;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.75rem;
        }
        .kill-btn:hover {
            background: #cc4444;
        }
        .refresh-btn {
            background: var(--accent);
            border: none;
            color: #0b0e14;
            padding: 0.2rem 1rem;
            border-radius: 20px;
            font-size: 0.8rem;
            cursor: pointer;
            margin-bottom: 1rem;
        }
        #no-client {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--text-muted);
        }
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
            <p class="mt-3">Select a client to manage terminals & processes.</p>
        </div>
        <div id="client-dashboard" style="display: none;">
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
                            <button id="fullscreen-btn" class="fullscreen-btn" title="Toggle fullscreen">
                                <i class="fas fa-expand"></i>
                            </button>
                        </div>
                        <div id="terminal-container"></div>
                    </div>
                </div>
                <div class="tab-content" id="tab-processes">
                    <div style="padding: 1rem;">
                        <button id="refresh-processes-btn" class="refresh-btn"><i class="fas fa-sync-alt"></i> Refresh</button>
                    </div>
                    <div class="process-panel">
                        <table class="process-table">
                            <thead><tr><th>PID</th><th>Name</th><th>CPU%</th><th>MEM%</th><th>Action</th></tr></thead>
                            <tbody id="process-tbody">
                                <tr><td colspan="5" style="text-align:center; padding:2rem;">Click Refresh to load processes</td></tr>
                            </tbody>
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
let currentTermTab = null;

function renderClientList(clients) {
    const container = document.getElementById('client-list');
    container.innerHTML = '';
    for (const [sid, data] of Object.entries(clients)) {
        const card = document.createElement('div');
        card.className = `client-card${sid === currentClient ? ' active' : ''}`;
        card.dataset.sid = sid;
        card.innerHTML = `
            <div class="client-name">${data.name || 'Unknown'}</div>
            <div>
                <span class="metric-badge"><i class="fas fa-microchip"></i> ${data.metrics?.cpu || '--'}%</span>
                <span class="metric-badge"><i class="fas fa-memory"></i> ${data.metrics?.ram_percent || '--'}%</span>
                <span class="metric-badge"><i class="fas fa-wifi"></i> ${data.metrics?.net_speed || '--'}</span>
            </div>
        `;
        card.addEventListener('click', () => selectClient(sid));
        container.appendChild(card);
    }
}

function selectClient(sid) {
    currentClient = sid;
    document.querySelectorAll('.client-card').forEach(c => c.classList.remove('active'));
    document.querySelector(`.client-card[data-sid="${sid}"]`)?.classList.add('active');
    document.getElementById('no-client').style.display = 'none';
    document.getElementById('client-dashboard').style.display = 'block';
    for (const [sessId, term] of Object.entries(terminals)) term.dispose();
    terminals = {};
    terminalSessions = {};
    document.getElementById('terminal-container').innerHTML = '';
    const tabBar = document.getElementById('term-tab-bar');
    while (tabBar.children.length > 2) tabBar.removeChild(tabBar.lastChild);
    currentTermTab = null;
    document.getElementById('process-tbody').innerHTML = '<tr><td colspan="5" style="text-align:center; padding:2rem;">Click Refresh to load processes</td></tr>';
    switchMainTab('terminal');
    document.querySelectorAll('.tab-btn[data-tab="terminal"]')[0].classList.add('active');
    socket.emit('request_metrics', sid);
    createNewTerminal();
}

function switchMainTab(tabName) {
    document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => btn.classList.remove('active'));
    document.querySelector(`.tab-btn[data-tab="${tabName}"]`)?.classList.add('active');
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.getElementById(`tab-${tabName}`).classList.add('active');
}

document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
        switchMainTab(btn.dataset.tab);
        if (btn.dataset.tab === 'processes' && currentClient) {
            socket.emit('get_processes', currentClient);
        }
    });
});

const fullscreenBtn = document.getElementById('fullscreen-btn');
const terminalPanel = document.getElementById('terminal-panel');

function toggleFullscreen() {
    if (!document.fullscreenElement) {
        terminalPanel.requestFullscreen().catch(err => console.warn('Fullscreen request failed:', err));
    } else {
        document.exitFullscreen();
    }
}

fullscreenBtn.addEventListener('click', toggleFullscreen);

document.addEventListener('fullscreenchange', () => {
    const icon = fullscreenBtn.querySelector('i');
    if (document.fullscreenElement) {
        icon.classList.remove('fa-expand');
        icon.classList.add('fa-compress');
    } else {
        icon.classList.remove('fa-compress');
        icon.classList.add('fa-expand');
    }
    Object.values(terminals).forEach(term => {
        if (term && term._addon) term._addon.fit();
    });
});

function createNewTerminal() {
    if (!currentClient) return;
    socket.emit('new_terminal', currentClient, (sessionId) => {
        if (!sessionId) return;
        const tabBar = document.getElementById('term-tab-bar');
        const tab = document.createElement('button');
        tab.className = 'term-tab';
        tab.dataset.session = sessionId;
        const termNum = Object.keys(terminals).length + 1;
        tab.innerHTML = `Term ${termNum} <span class="close-term" data-session="${sessionId}">×</span>`;
        tab.addEventListener('click', (e) => {
            if (e.target.classList.contains('close-term')) return;
            switchTerminal(sessionId);
        });
        tab.querySelector('.close-term').addEventListener('click', (e) => {
            e.stopPropagation();
            closeTerminal(sessionId);
        });
        tabBar.insertBefore(tab, fullscreenBtn);
        const container = document.getElementById('terminal-container');
        const termDiv = document.createElement('div');
        termDiv.id = `term-${sessionId}`;
        termDiv.style.display = 'none';
        termDiv.style.height = '100%';
        container.appendChild(termDiv);
        const term = new Terminal({
            cursorBlink: true,
            theme: { background: '#0a0e17', foreground: '#e0e6f0' }
        });
        term.open(termDiv);
        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term._addon = fitAddon;
        fitAddon.fit();
        terminals[sessionId] = term;
        terminalSessions[sessionId] = true;
        term.onResize((size) => {
            socket.emit('terminal_resize', { sessionId, cols: size.cols, rows: size.rows });
        });
        term.onData((data) => {
            socket.emit('terminal_input', { sessionId, data });
        });
        switchTerminal(sessionId);
        setTimeout(() => fitAddon.fit(), 100);
        const resizeObserver = new ResizeObserver(() => fitAddon.fit());
        resizeObserver.observe(termDiv);
    });
}

function switchTerminal(sessionId) {
    document.querySelectorAll('.term-tab').forEach(btn => btn.classList.remove('active'));
    const tab = document.querySelector(`.term-tab[data-session="${sessionId}"]`);
    if (tab) tab.classList.add('active');
    document.querySelectorAll('#terminal-container > div').forEach(div => div.style.display = 'none');
    const target = document.getElementById(`term-${sessionId}`);
    if (target) target.style.display = 'block';
    currentTermTab = sessionId;
}

function closeTerminal(sessionId) {
    socket.emit('close_terminal', { sessionId });
    const tab = document.querySelector(`.term-tab[data-session="${sessionId}"]`);
    if (tab) tab.remove();
    const div = document.getElementById(`term-${sessionId}`);
    if (div) div.remove();
    if (terminals[sessionId]) terminals[sessionId].dispose();
    delete terminals[sessionId];
    delete terminalSessions[sessionId];
    if (Object.keys(terminals).length === 0) createNewTerminal();
    else switchTerminal(Object.keys(terminals)[0]);
}

document.getElementById('new-terminal-btn').addEventListener('click', createNewTerminal);

function updateMetricsUI(metrics) {
    const grid = document.getElementById('metrics-grid');
    const cpuCores = metrics.cpu_cores || 'N/A';
    const cpuModel = metrics.cpu_model || 'Unknown';
    const totalRam = metrics.total_ram || 'N/A';
    const usedRam = metrics.used_ram || '0';
    const availRam = metrics.available_ram || '0';
    const ramPercent = metrics.ram_percent || 0;
    const netDown = metrics.net_down || '0 B/s';
    const netUp = metrics.net_up || '0 B/s';
    const diskTotal = metrics.disk_total || 'N/A';
    const diskUsed = metrics.disk_used || '0';
    const diskPercent = metrics.disk_percent || 0;
    grid.innerHTML = `
        <div class="metric-card">
            <div class="metric-header"><span class="metric-icon"><i class="fas fa-microchip"></i></span><span class="metric-title">CPU</span></div>
            <div class="metric-main">${metrics.cpu || 0}%</div>
            <div class="metric-detail">${cpuModel} (${cpuCores} cores)</div>
            <div class="progress"><div class="progress-bar" style="width:${metrics.cpu || 0}%"></div></div>
        </div>
        <div class="metric-card">
            <div class="metric-header"><span class="metric-icon"><i class="fas fa-memory"></i></span><span class="metric-title">RAM</span></div>
            <div class="metric-main">${ramPercent}%</div>
            <div class="metric-detail">${usedRam} / ${totalRam} (free: ${availRam})</div>
            <div class="progress"><div class="progress-bar" style="width:${ramPercent}%; background: #50fa7b;"></div></div>
        </div>
        <div class="metric-card">
            <div class="metric-header"><span class="metric-icon"><i class="fas fa-hdd"></i></span><span class="metric-title">Disk</span></div>
            <div class="metric-main">${diskPercent}%</div>
            <div class="metric-detail">${diskUsed} / ${diskTotal}</div>
            <div class="progress"><div class="progress-bar" style="width:${diskPercent}%; background: #f1fa8c;"></div></div>
        </div>
        <div class="metric-card">
            <div class="metric-header"><span class="metric-icon"><i class="fas fa-wifi"></i></span><span class="metric-title">Network</span></div>
            <div class="metric-main">↓ ${netDown}</div>
            <div class="metric-detail">↑ ${netUp}</div>
        </div>
    `;
}

function renderProcessTable(processes) {
    const tbody = document.getElementById('process-tbody');
    if (!processes || processes.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:2rem;">No processes received</td></tr>';
        return;
    }
    tbody.innerHTML = processes.map(p => `
        <tr>
            <td>${p.pid}</td>
            <td>${p.name}</td>
            <td>${p.cpu_percent ?? '0'}%</td>
            <td>${p.mem_percent ?? '0'}%</td>
            <td><button class="kill-btn" data-pid="${p.pid}">Kill</button></td>
        </tr>
    `).join('');
    document.querySelectorAll('.kill-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const pid = e.target.dataset.pid;
            if (currentClient && pid) {
                socket.emit('kill_process', { target_sid: currentClient, pid: parseInt(pid) });
                btn.textContent = 'Killed';
                btn.disabled = true;
                setTimeout(() => {
                    btn.textContent = 'Kill';
                    btn.disabled = false;
                }, 2000);
            }
        });
    });
}

document.getElementById('refresh-processes-btn')?.addEventListener('click', () => {
    if (currentClient) socket.emit('get_processes', currentClient);
});

socket.on('connect', () => console.log('Connected'));
socket.on('client_list', (data) => renderClientList(data));
socket.on('metrics_update', (data) => {
    if (currentClient === data.sid) updateMetricsUI(data.metrics);
});
socket.on('terminal_output', (data) => {
    if (terminals[data.sessionId]) terminals[data.sessionId].write(data.output);
});
socket.on('process_list', (data) => {
    if (data.target_sid === currentClient) renderProcessTable(data.processes);
});
socket.emit('get_clients');
</script>
</body>
</html>
"""

# ---------- Helpers ----------
def broadcast_client_list():
    emit('client_list', {
        sid: {'name': info['name'], 'metrics': info['metrics']}
        for sid, info in clients.items()
    }, broadcast=True)

# ---------- SocketIO Events ----------
@socketio.on('connect')
def handle_connect(auth=None):
    print(f"[+] Connected: {request.sid}")
    clients[request.sid] = {'name': request.sid[:8], 'metrics': {}}
    terminal_sessions[request.sid] = {}
    broadcast_client_list()

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f"[-] Disconnected: {sid}")
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
        emit('metrics_update', {
            'sid': request.sid,
            'metrics': clients[request.sid]['metrics']
        }, room=browser_sid)
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
        emit('terminal_input', {
            'session_id': session_id,
            'data': data.get('data')
        }, room=target_sid)

@socketio.on('terminal_resize')
def handle_terminal_resize(data):
    session_id = data.get('sessionId')
    target_sid = session_owners.get(session_id)
    if target_sid:
        emit('terminal_resize', {
            'session_id': session_id,
            'cols': data.get('cols'),
            'rows': data.get('rows')
        }, room=target_sid)

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
        emit('terminal_output', {
            'sessionId': data.get('session_id'),
            'output': data.get('output', '')
        }, room=browser_sid)

@socketio.on('get_processes')
def handle_get_processes(target_sid):
    if target_sid in clients:
        emit('list_processes', {}, room=target_sid)

@socketio.on('process_list')
def handle_process_list(data):
    browser_sid = client_watchers.get(request.sid)
    if browser_sid:
        emit('process_list', {
            'target_sid': request.sid,
            'processes': data.get('processes', [])
        }, room=browser_sid)

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
    # Default threading mode uses Werkzeug, but for Render we allow unsafe Werkzeug
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
