#!/usr/bin/env python3
import os
import json
import time
import threading
import subprocess
import pty
import select
import fcntl
import termios
import struct
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit, disconnect

app = Flask(__name__)
app.config['SECRET_KEY'] = 'server'
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, ping_interval=25)

# Data structures
clients = {}          # sid -> {'name': str, 'metrics': dict}
terminal_sessions = {}  # sid -> {session_id: {'master_fd': fd, 'process': proc, ...}}

# ---------- Embedded HTML UI ----------
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BlackHat Remote Terminal</title>
    <!-- Bootstrap 5 -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <!-- Font Awesome -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <!-- xterm.js -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm/css/xterm.css">
    <script src="https://cdn.jsdelivr.net/npm/xterm/lib/xterm.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit/lib/xterm-addon-fit.js"></script>
    <!-- Socket.IO -->
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <!-- Chart.js -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #1e1e2f; color: #cdd6f4; font-family: 'Segoe UI', sans-serif; }
        .sidebar { background: #313244; min-height: 100vh; padding: 1rem; overflow-y: auto; }
        .client-card { background: #45475a; border-radius: 10px; padding: 0.8rem; margin-bottom: 0.8rem; cursor: pointer; transition: 0.2s; border-left: 4px solid #89b4fa; }
        .client-card:hover { background: #585b70; }
        .client-card.active { border-left-color: #a6e3a1; }
        .client-name { font-weight: bold; }
        .metric-badge { font-size: 0.7rem; background: #1e1e2f; padding: 0.2rem 0.6rem; border-radius: 20px; margin-right: 0.3rem; }
        .main-panel { padding: 1rem; }
        .terminal-panel { background: #0c0c1a; border-radius: 10px; overflow: hidden; height: 65vh; }
        #terminal-container { width: 100%; height: 100%; }
        .tab-bar { background: #313244; padding: 0.3rem 0.8rem; border-radius: 10px 10px 0 0; display: flex; flex-wrap: wrap; gap: 0.3rem; align-items: center; }
        .tab-btn { background: #45475a; border: none; color: #cdd6f4; padding: 0.2rem 1rem; border-radius: 20px; font-size: 0.8rem; transition: 0.2s; }
        .tab-btn.active { background: #89b4fa; color: #1e1e2f; }
        .tab-btn:hover { background: #585b70; }
        .tab-btn .close-tab { margin-left: 0.5rem; color: #f38ba8; cursor: pointer; }
        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px,1fr)); gap: 0.8rem; margin-bottom: 1rem; }
        .metric-card { background: #313244; border-radius: 10px; padding: 0.8rem; text-align: center; }
        .metric-title { font-size: 0.7rem; text-transform: uppercase; color: #6c7086; }
        .metric-value { font-size: 1.4rem; font-weight: bold; color: #a6e3a1; }
        .chart-container { height: 60px; margin-top: 0.3rem; }
        #no-client { color: #6c7086; text-align: center; padding: 3rem; }
        #new-terminal-btn { background: #89b4fa; color: #1e1e2f; border: none; border-radius: 20px; padding: 0.2rem 1rem; font-size: 0.8rem; }
        #new-terminal-btn:hover { background: #74c7ec; }
    </style>
</head>
<body>
<div class="container-fluid">
    <div class="row">
        <!-- Sidebar -->
        <div class="col-md-3 col-lg-2 sidebar" id="sidebar">
            <h5><i class="fas fa-terminal"></i> Clients</h5>
            <div id="client-list"></div>
        </div>
        <!-- Main -->
        <div class="col-md-9 col-lg-10 main-panel">
            <div id="no-client">
                <i class="fas fa-plug fa-3x"></i>
                <p class="mt-3">Select a client from the sidebar to start managing terminals.</p>
            </div>
            <div id="client-dashboard" style="display:none;">
                <!-- Metrics -->
                <div class="metrics-grid" id="metrics-grid"></div>
                <!-- Terminal Tabs -->
                <div class="terminal-panel">
                    <div class="tab-bar" id="tab-bar">
                        <button id="new-terminal-btn" class="tab-btn"><i class="fas fa-plus"></i> New Terminal</button>
                    </div>
                    <div id="terminal-container"></div>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
// ---------- Socket.IO connection ----------
const socket = io();

// ---------- State ----------
let currentClient = null;            // sid of selected client
let terminals = {};                 // { session_id: xterm.Terminal }
let terminalSessions = {};          // { session_id: true }
let metricsChart = null;

// ---------- UI Helpers ----------
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
                <span class="metric-badge"><i class="fas fa-hdd"></i> ${data.metrics?.disk_percent || '--'}%</span>
                <span class="metric-badge"><i class="fas fa-wifi"></i> ${data.metrics?.net_speed || '--'}</span>
            </div>
        `;
        card.addEventListener('click', () => selectClient(sid));
        container.appendChild(card);
    }
}

function selectClient(sid) {
    currentClient = sid;
    // Update sidebar highlights
    document.querySelectorAll('.client-card').forEach(c => c.classList.remove('active'));
    document.querySelector(`.client-card[data-sid="${sid}"]`)?.classList.add('active');
    // Show dashboard
    document.getElementById('no-client').style.display = 'none';
    document.getElementById('client-dashboard').style.display = 'block';
    // Clear existing terminals
    for (const [sessId, term] of Object.entries(terminals)) {
        term.dispose();
    }
    terminals = {};
    terminalSessions = {};
    document.getElementById('terminal-container').innerHTML = '';
    // Remove tabs except "New" button
    const tabBar = document.getElementById('tab-bar');
    while (tabBar.children.length > 1) tabBar.removeChild(tabBar.lastChild);
    // Request current metrics for this client
    socket.emit('request_metrics', sid);
    // Create initial terminal
    createNewTerminal();
}

function createNewTerminal() {
    if (!currentClient) return;
    socket.emit('new_terminal', currentClient, (sessionId) => {
        if (!sessionId) return;
        // Create tab
        const tabBar = document.getElementById('tab-bar');
        const tab = document.createElement('button');
        tab.className = 'tab-btn active';
        tab.dataset.session = sessionId;
        const termNum = Object.keys(terminals).length + 1;
        tab.innerHTML = `Terminal ${termNum} <span class="close-tab" data-session="${sessionId}">&times;</span>`;
        tabBar.appendChild(tab);
        // Create xterm
        const container = document.getElementById('terminal-container');
        const termDiv = document.createElement('div');
        termDiv.id = `term-${sessionId}`;
        termDiv.style.display = 'block';
        termDiv.style.height = '100%';
        container.appendChild(termDiv);
        const term = new Terminal({ cursorBlink: true, theme: { background: '#0c0c1a', foreground: '#cdd6f4' } });
        term.open(termDiv);
        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        fitAddon.fit();
        terminals[sessionId] = term;
        terminalSessions[sessionId] = true;
        // Handle resize
        term.onResize((size) => {
            socket.emit('terminal_resize', { sessionId, cols: size.cols, rows: size.rows });
        });
        // Handle input
        term.onData((data) => {
            socket.emit('terminal_input', { sessionId, data });
        });
        // Handle tab switching
        tab.addEventListener('click', (e) => {
            if (e.target.classList.contains('close-tab')) return;
            switchTerminal(sessionId);
        });
        // Handle tab close
        tab.querySelector('.close-tab').addEventListener('click', (e) => {
            e.stopPropagation();
            closeTerminal(sessionId);
        });
        // Switch to this new terminal
        switchTerminal(sessionId);
        // Fit again after a moment
        setTimeout(() => fitAddon.fit(), 100);
        // Listen for window resize
        const resizeObserver = new ResizeObserver(() => fitAddon.fit());
        resizeObserver.observe(termDiv);
    });
}

function switchTerminal(sessionId) {
    // Update tabs
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    const tab = document.querySelector(`.tab-btn[data-session="${sessionId}"]`);
    if (tab) tab.classList.add('active');
    // Show only the selected terminal
    document.querySelectorAll('#terminal-container > div').forEach(div => div.style.display = 'none');
    const target = document.getElementById(`term-${sessionId}`);
    if (target) target.style.display = 'block';
}

function closeTerminal(sessionId) {
    socket.emit('close_terminal', { sessionId });
    // Remove UI
    const tab = document.querySelector(`.tab-btn[data-session="${sessionId}"]`);
    if (tab) tab.remove();
    const div = document.getElementById(`term-${sessionId}`);
    if (div) div.remove();
    if (terminals[sessionId]) terminals[sessionId].dispose();
    delete terminals[sessionId];
    delete terminalSessions[sessionId];
    // If no terminals left, create a new one automatically
    if (Object.keys(terminals).length === 0) {
        createNewTerminal();
    } else {
        // Switch to first remaining
        const first = Object.keys(terminals)[0];
        switchTerminal(first);
    }
}

// ---------- Metrics charts ----------
function initMetricsChart(data) {
    if (metricsChart) {
        metricsChart.destroy();
    }
    const grid = document.getElementById('metrics-grid');
    const canvas = document.createElement('canvas');
    canvas.style.height = '100px';
    grid.appendChild(canvas);
    metricsChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: ['CPU', 'RAM', 'Disk'],
            datasets: [{
                label: 'Usage %',
                data: [data.cpu || 0, data.ram_percent || 0, data.disk_percent || 0],
                backgroundColor: ['#89b4fa', '#a6e3a1', '#f9e2af'],
                borderColor: ['#89b4fa', '#a6e3a1', '#f9e2af'],
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { y: { min: 0, max: 100, grid: { color: '#313244' } } }
        }
    });
}

function updateMetricsUI(metrics) {
    const grid = document.getElementById('metrics-grid');
    // Keep existing chart if present, else create
    if (!metricsChart) {
        initMetricsChart(metrics);
    } else {
        metricsChart.data.datasets[0].data = [metrics.cpu || 0, metrics.ram_percent || 0, metrics.disk_percent || 0];
        metricsChart.update();
    }
    // Update numeric values (add or update metric cards)
    const metricCards = grid.querySelectorAll('.metric-card');
    if (metricCards.length === 0) {
        grid.innerHTML = `
            <div class="metric-card"><div class="metric-title">CPU</div><div class="metric-value">${metrics.cpu || 0}%</div></div>
            <div class="metric-card"><div class="metric-title">RAM</div><div class="metric-value">${metrics.ram_percent || 0}%</div></div>
            <div class="metric-card"><div class="metric-title">Disk (SSD)</div><div class="metric-value">${metrics.disk_percent || 0}%</div></div>
            <div class="metric-card"><div class="metric-title">Network</div><div class="metric-value">${metrics.net_speed || '0 KB/s'}</div></div>
        `;
        // Re‑init chart after cards (we already have chart from init)
    } else {
        // Update existing cards
        const values = grid.querySelectorAll('.metric-value');
        if (values.length >= 4) {
            values[0].textContent = `${metrics.cpu || 0}%`;
            values[1].textContent = `${metrics.ram_percent || 0}%`;
            values[2].textContent = `${metrics.disk_percent || 0}%`;
            values[3].textContent = metrics.net_speed || '0 KB/s';
        }
    }
}

// ---------- Socket events ----------
socket.on('connect', () => {
    console.log('Connected to server');
});

socket.on('client_list', (data) => {
    renderClientList(data);
});

socket.on('metrics_update', (data) => {
    // data: { sid, metrics }
    if (currentClient === data.sid) {
        updateMetricsUI(data.metrics);
    }
});

socket.on('terminal_output', (data) => {
    // data: { sessionId, output }
    if (terminals[data.sessionId]) {
        terminals[data.sessionId].write(data.output);
    }
});

// ---------- UI: New terminal button ----------
document.getElementById('new-terminal-btn').addEventListener('click', createNewTerminal);

// ---------- Initial load ----------
socket.emit('get_clients');
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

# ---------- SocketIO Events ----------
@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")
    clients[request.sid] = {'name': request.sid[:8], 'metrics': {}}
    terminal_sessions[request.sid] = {}
    # Broadcast updated list
    emit('client_list', {sid: {'name': data['name'], 'metrics': data['metrics']} for sid, data in clients.items()}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")
    # Clean up any terminal processes
    for sess in terminal_sessions.get(request.sid, {}).values():
        if 'process' in sess:
            sess['process'].terminate()
    clients.pop(request.sid, None)
    terminal_sessions.pop(request.sid, None)
    emit('client_list', {sid: {'name': data['name'], 'metrics': data['metrics']} for sid, data in clients.items()}, broadcast=True)

@socketio.on('register_client')
def handle_register(data):
    name = data.get('name', request.sid[:8])
    clients[request.sid]['name'] = name
    emit('client_list', {sid: {'name': data['name'], 'metrics': data['metrics']} for sid, data in clients.items()}, broadcast=True)

@socketio.on('get_clients')
def handle_get_clients():
    emit('client_list', {sid: {'name': data['name'], 'metrics': data['metrics']} for sid, data in clients.items()})

@socketio.on('request_metrics')
def handle_request_metrics(sid):
    if sid in clients:
        emit('metrics_update', {'sid': sid, 'metrics': clients[sid]['metrics']})

@socketio.on('metrics')
def handle_metrics(data):
    clients[request.sid]['metrics'] = data.get('metrics', {})
    emit('client_list', {sid: {'name': data['name'], 'metrics': data['metrics']} for sid, data in clients.items()}, broadcast=True)
    emit('metrics_update', {'sid': request.sid, 'metrics': clients[request.sid]['metrics']}, broadcast=True)

@socketio.on('new_terminal')
def handle_new_terminal():
    # Generate a unique session ID
    session_id = f"term_{int(time.time())}_{request.sid[:4]}"
    # Tell the client to spawn a new shell
    emit('spawn_terminal', {'session_id': session_id}, room=request.sid)
    # Store placeholder on server side (for reference)
    terminal_sessions.setdefault(request.sid, {})[session_id] = {'created': True}
    return session_id  # send back to UI

@socketio.on('terminal_ready')
def handle_terminal_ready(data):
    # Client confirms terminal is ready – we can store more info if needed
    pass

@socketio.on('terminal_input')
def handle_terminal_input(data):
    # Forward input to client
    sid = request.sid
    session_id = data.get('sessionId')
    input_data = data.get('data')
    if sid in terminal_sessions and session_id in terminal_sessions[sid]:
        emit('terminal_input', {'session_id': session_id, 'data': input_data}, room=sid)

@socketio.on('terminal_resize')
def handle_terminal_resize(data):
    sid = request.sid
    session_id = data.get('sessionId')
    cols = data.get('cols')
    rows = data.get('rows')
    if sid in terminal_sessions and session_id in terminal_sessions[sid]:
        emit('terminal_resize', {'session_id': session_id, 'cols': cols, 'rows': rows}, room=sid)

@socketio.on('close_terminal')
def handle_close_terminal(data):
    sid = request.sid
    session_id = data.get('sessionId')
    if sid in terminal_sessions and session_id in terminal_sessions[sid]:
        emit('close_terminal', {'session_id': session_id}, room=sid)
        del terminal_sessions[sid][session_id]

@socketio.on('terminal_output')
def handle_terminal_output(data):
    # Broadcast terminal output to all UI clients (or we can target specific rooms)
    emit('terminal_output', {'sessionId': data['session_id'], 'output': data['output']}, broadcast=True)

@socketio.on('ping')
def handle_ping():
    emit('pong')

# ---------- Run server ----------
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
