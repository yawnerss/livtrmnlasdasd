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
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, viewport-fit=cover">
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
            --sidebar-width: 260px;
            --sidebar-min: 180px;
            --sidebar-max: 450px;
            --resize-handle: 6px;
            --mobile-break: 768px;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body { background: var(--bg-primary); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; display:flex; height:100dvh; overflow:hidden; }

        .sidebar {
            width: var(--sidebar-width); min-width: var(--sidebar-min); max-width: var(--sidebar-max);
            background: var(--bg-secondary); border-right: 1px solid var(--border);
            display: flex; flex-direction: column; position: relative; z-index: 20;
            transition: transform 0.3s ease;
        }
        .sidebar-header {
            padding: 1rem; border-bottom: 1px solid var(--border);
            display: flex; align-items: center; justify-content: space-between;
        }
        .sidebar-header h5 { color: var(--text-muted); text-transform: uppercase; font-size: 0.75rem; margin:0; }
        .sidebar-list { flex:1; overflow-y: auto; padding: 0.5rem; }
        .client-card {
            background: var(--bg-card); border-radius: 12px; padding: 0.8rem; margin-bottom: 0.6rem;
            cursor: pointer; transition: all 0.2s; border-left: 4px solid transparent;
            display: flex; flex-direction: column; gap: 0.3rem;
        }
        .client-card:hover { border-color: var(--accent); }
        .client-card.active { border-color: var(--accent2); background: linear-gradient(135deg, rgba(80,250,123,0.05), rgba(94,158,255,0.05)); }
        .client-name { font-weight: 600; }
        .metric-badge { font-size: 0.7rem; background: rgba(0,0,0,0.3); padding: 0.15rem 0.5rem; border-radius: 20px; margin-right: 0.3rem; display: inline-block; }
        .resize-handle {
            position: absolute; top:0; right: calc(-1 * var(--resize-handle));
            width: var(--resize-handle); height: 100%; cursor: col-resize;
            background: transparent; z-index: 30;
        }
        .resize-handle:hover, .resize-handle.active { background: var(--accent); opacity: 0.3; }

        .main-panel { flex:1; display:flex; flex-direction:column; overflow:hidden; min-width:0; }
        .dashboard-header { padding: 1rem 1.5rem; border-bottom: 1px solid var(--border); }
        .metrics-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr)); gap:0.8rem; }
        .metric-card {
            background: var(--bg-card); border-radius: 12px; padding: 1rem;
            display: flex; flex-direction: column; position: relative;
        }
        .metric-card.hidden { display: none; }
        .metric-header { display:flex; align-items:center; gap:0.5rem; margin-bottom:0.5rem; }
        .metric-title { font-size: 0.7rem; text-transform: uppercase; color: var(--text-muted); }
        .metric-main { font-size: 1.8rem; font-weight: 700; }
        .metric-detail { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.2rem; }
        .progress { height:6px; margin-top:0.5rem; background:rgba(255,255,255,0.05); border-radius:3px; overflow:hidden; }
        .progress-bar { height:100%; border-radius:3px; background:var(--accent); }
        .hide-metric { position: absolute; top: 0.5rem; right: 0.5rem; background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 0.8rem; opacity: 0.5; }
        .hide-metric:hover { opacity: 1; }
        .content-area { flex:1; display:flex; flex-direction:column; padding:0 1.5rem 1.5rem; overflow:hidden; min-height:0; }
        .tab-nav { display:flex; gap:0.5rem; margin-bottom:0.8rem; flex-wrap: wrap; align-items: center; }
        .tab-btn {
            background: var(--bg-card); border: none; color: var(--text); padding: 0.5rem 1.5rem;
            border-radius: 20px; font-size: 0.85rem; cursor: pointer; transition: 0.2s;
            white-space: nowrap;
        }
        .tab-btn.active { background: var(--accent); color: #0b0e14; }
        .tab-content { flex:1; overflow:hidden; display:none; min-height:0; }
        .tab-content.active { display:flex; flex-direction:column; }
        .terminal-panel {
            flex:1; background: #0a0e17; border-radius: 12px; overflow:hidden;
            display:flex; flex-direction:column; min-height:0;
        }
        .terminal-tabs {
            display:flex; align-items:center; background: #151a23; padding:0.4rem; gap:0.3rem;
            flex-wrap: wrap;
        }
        .term-tab {
            background: #1e2531; border: none; color: var(--text); padding: 0.2rem 0.8rem;
            border-radius: 6px; font-size: 0.8rem; display: flex; align-items: center; gap: 0.4rem;
            cursor: pointer;
        }
        .term-tab.active { background: var(--accent); color: #0b0e14; }
        .close-term { cursor:pointer; color: var(--danger); opacity:0.7; font-size:0.9rem; }
        .close-term:hover { opacity:1; }
        /* FIX: container uses flex:1 and non-absolute children */
        #terminal-container { flex:1; padding:0.5rem; min-height:0; overflow:hidden; position:relative; }
        #terminal-container > div { display:none; width:100%; height:100%; }
        #terminal-container > div.active { display:block; }
        .fullscreen-btn { margin-left:auto; background:transparent; border:none; color:var(--text-muted); cursor:pointer; font-size:1rem; }
        .fullscreen-btn:hover { color: var(--text); }
        .process-panel { flex:1; overflow:auto; background:var(--bg-card); border-radius:12px; }
        .process-table { width:100%; border-collapse:collapse; }
        .process-table th, .process-table td { padding:0.5rem 1rem; text-align:left; border-bottom:1px solid var(--border); }
        .process-table th { background:rgba(0,0,0,0.3); font-size:0.75rem; text-transform:uppercase; }
        .kill-btn { background:var(--danger); border:none; color:white; padding:0.2rem 0.6rem; border-radius:4px; cursor:pointer; font-size:0.75rem; }
        .refresh-btn { background:var(--accent); border:none; color:#0b0e14; padding:0.2rem 1rem; border-radius:20px; font-size:0.8rem; cursor:pointer; margin:1rem; }
        #no-client { display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; color:var(--text-muted); }

        .command-fab {
            position: fixed; bottom: 24px; right: 24px; width: 48px; height: 48px;
            border-radius: 50%; background: var(--accent); color: #0b0e14;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.2rem; box-shadow: 0 4px 12px rgba(0,0,0,0.4);
            cursor: pointer; z-index: 50; border: none;
            transition: transform 0.2s;
        }
        .command-fab:active { transform: scale(0.9); }
        .command-drawer {
            position: fixed; bottom: 80px; right: 24px; width: 280px; max-height: 60vh;
            background: var(--bg-card); border-radius: 16px; padding: 1rem;
            box-shadow: 0 8px 24px rgba(0,0,0,0.6); z-index: 49;
            display: none; flex-direction: column; overflow-y: auto;
        }
        .command-drawer.open { display: flex; }
        .command-drawer h6 { margin-bottom: 0.8rem; color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase; }
        .command-item {
            display: flex; justify-content: space-between; align-items: center;
            padding: 0.4rem 0; border-bottom: 1px solid var(--border);
            font-size: 0.85rem;
        }
        .command-item button { background: transparent; border: none; color: var(--accent); cursor: pointer; font-size: 0.8rem; }
        .add-command { margin-top: 0.8rem; display: flex; gap: 0.4rem; }
        .add-command input { flex:1; background: #0a0e17; border:1px solid var(--border); color: var(--text); padding:0.4rem; border-radius:6px; font-size:0.8rem; }
        .add-command button { background: var(--accent); border:none; color:#0b0e14; border-radius:6px; padding:0.4rem 0.8rem; font-size:0.8rem; }

        .font-size-slider {
            display: flex; align-items: center; gap: 0.5rem; margin-left: 0.5rem;
            font-size: 0.8rem; color: var(--text-muted);
        }
        .font-size-slider input { width: 70px; }

        .toast-container {
            position: fixed; top: 16px; right: 16px; z-index: 100;
            display: flex; flex-direction: column; gap: 0.5rem;
        }
        .toast {
            background: var(--accent2); color: #0b0e14; padding: 0.7rem 1.2rem;
            border-radius: 8px; font-weight: 500; font-size: 0.9rem;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            animation: fadeIn 0.3s ease;
        }
        @keyframes fadeIn { from { opacity:0; transform:translateX(20px); } to { opacity:1; transform:translateX(0); } }

        @media (max-width: 768px) {
            .sidebar {
                position: fixed; top:0; left:0; bottom:0; width: 280px;
                transform: translateX(-100%);
                box-shadow: 4px 0 12px rgba(0,0,0,0.5);
            }
            .sidebar.open { transform: translateX(0); }
            .resize-handle { display: none; }
            .main-panel { width: 100%; }
            .dashboard-header { padding: 0.8rem; }
            .metrics-grid { grid-template-columns: 1fr; }
            .content-area { padding: 0 0.8rem 0.8rem; }
            .term-tab, .tab-btn { padding: 0.5rem 1rem; font-size: 0.9rem; }
            .mobile-menu-btn {
                display: flex !important; align-items: center; justify-content: center;
                width: 40px; height: 40px; background: var(--bg-card); border-radius: 8px;
                border: none; color: var(--text); font-size: 1.2rem; margin-right: 0.5rem;
            }
        }
        @media (min-width: 769px) { .mobile-menu-btn { display: none; } }
    </style>
</head>
<body>
<div class="sidebar" id="sidebar">
    <div class="sidebar-header">
        <h5><i class="fas fa-terminal"></i> Clients</h5>
        <button class="mobile-menu-btn" id="close-sidebar-btn" style="display:none;"><i class="fas fa-times"></i></button>
    </div>
    <div class="sidebar-list" id="client-list"></div>
    <div class="resize-handle" id="resize-handle"></div>
</div>
<div class="main-panel">
    <div id="no-client">
        <i class="fas fa-plug fa-3x"></i>
        <p class="mt-3">Select a client to start managing terminals.</p>
    </div>
    <div id="client-dashboard" style="display:none; width:100%;">
        <div class="dashboard-header" id="dashboard-header">
            <div style="display:flex; align-items:center; margin-bottom:0.5rem;">
                <button class="mobile-menu-btn" id="open-sidebar-btn"><i class="fas fa-bars"></i></button>
                <span style="font-weight:600; font-size:1.1rem;">Client Dashboard</span>
            </div>
            <div class="metrics-grid" id="metrics-grid"></div>
        </div>
        <div class="content-area">
            <div class="tab-nav">
                <button class="tab-btn active" data-tab="terminal">Terminals</button>
                <button class="tab-btn" data-tab="processes">Processes</button>
                <div class="font-size-slider" title="Terminal font size">
                    <i class="fas fa-text-height"></i>
                    <input type="range" id="font-size-slider" min="10" max="24" value="14" step="1">
                </div>
            </div>
            <div class="tab-content active" id="tab-terminal">
                <div class="terminal-panel" id="terminal-panel">
                    <div class="terminal-tabs" id="term-tab-bar">
                        <button id="new-terminal-btn" class="term-tab"><i class="fas fa-plus"></i> New</button>
                        <button id="refresh-terminal-btn" class="term-tab" title="Restart current terminal"><i class="fas fa-sync-alt"></i> Refresh</button>
                        <button id="clear-terminal-btn" class="term-tab" title="Clear current terminal"><i class="fas fa-eraser"></i> Clear</button>
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

<button class="command-fab" id="command-fab" title="Quick Commands"><i class="fas fa-terminal"></i></button>
<div class="command-drawer" id="command-drawer">
    <h6><i class="fas fa-history"></i> History</h6>
    <div id="command-history"></div>
    <h6 style="margin-top:1rem;"><i class="fas fa-star"></i> Saved</h6>
    <div id="saved-commands"></div>
    <div class="add-command">
        <input type="text" id="new-command-input" placeholder="Add command...">
        <button id="add-command-btn"><i class="fas fa-plus"></i></button>
    </div>
</div>

<div class="toast-container" id="toast-container"></div>

<script>
const socket = io();
let currentClient = null;
const clientTerminals = {}; // per client: { terminals, sessions, activeSessionId, tabCounter }
let savedCommands = JSON.parse(localStorage.getItem('savedCommands') || '[]');
let commandHistory = JSON.parse(localStorage.getItem('commandHistory') || '[]');
let defaultFontSize = parseInt(localStorage.getItem('terminalFontSize') || '14');
document.getElementById('font-size-slider').value = defaultFontSize;

// ----- Sidebar resize -----
const sidebar = document.getElementById('sidebar');
const handle = document.getElementById('resize-handle');
const root = document.documentElement;
let savedWidth = localStorage.getItem('sidebarWidth');
if (savedWidth) root.style.setProperty('--sidebar-width', savedWidth + 'px');
let isResizing = false;
handle.addEventListener('mousedown', (e) => { isResizing = true; handle.classList.add('active'); e.preventDefault(); });
document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;
    const newWidth = Math.min(Math.max(e.clientX, 180), 450);
    root.style.setProperty('--sidebar-width', newWidth + 'px');
    localStorage.setItem('sidebarWidth', newWidth);
    fitAllTerminals();
});
document.addEventListener('mouseup', () => { isResizing = false; handle.classList.remove('active'); });

// Mobile drawer
const openBtn = document.getElementById('open-sidebar-btn');
const closeBtn = document.getElementById('close-sidebar-btn');
openBtn?.addEventListener('click', () => sidebar.classList.add('open'));
closeBtn?.addEventListener('click', () => sidebar.classList.remove('open'));
document.getElementById('client-list').addEventListener('click', (e) => {
    if (window.innerWidth <= 768 && e.target.closest('.client-card')) sidebar.classList.remove('open');
});

function showToast(msg) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function fitAllTerminals() {
    Object.values(clientTerminals).forEach(client => {
        Object.values(client.terminals).forEach(term => term._addon?.fit());
    });
}

// ----- Client list rendering -----
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
    if (sid === currentClient) {
        const data = clientTerminals[sid];
        if (data && Object.keys(data.terminals).length > 0) {
            const activeSession = data.activeSessionId || Object.keys(data.terminals)[0];
            switchTerminal(activeSession);
        } else {
            createNewTerminal();
        }
        return;
    }

    // Hide all terminal divs of previous client
    if (currentClient && clientTerminals[currentClient]) {
        Object.keys(clientTerminals[currentClient].terminals).forEach(sid => {
            const div = document.getElementById(`term-${sid}`);
            if (div) div.classList.remove('active');
        });
    }

    currentClient = sid;
    document.querySelectorAll('.client-card').forEach(c => c.classList.remove('active'));
    document.querySelector(`.client-card[data-sid="${sid}"]`)?.classList.add('active');
    document.getElementById('no-client').style.display = 'none';
    document.getElementById('client-dashboard').style.display = 'block';

    if (!clientTerminals[sid]) {
        clientTerminals[sid] = { terminals: {}, sessions: {}, activeSessionId: null, tabCounter: 0 };
    }

    rebuildTabBar(sid);
    const data = clientTerminals[sid];
    if (Object.keys(data.terminals).length === 0) {
        createNewTerminal();
    } else {
        const activeSession = data.activeSessionId || Object.keys(data.terminals)[0];
        switchTerminal(activeSession);
    }

    socket.emit('request_metrics', sid);
    switchMainTab('terminal');
}

function rebuildTabBar(clientSid) {
    const tabBar = document.getElementById('term-tab-bar');
    while (tabBar.children.length > 4) {
        tabBar.removeChild(tabBar.lastChild);
    }
    const data = clientTerminals[clientSid];
    if (!data) return;
    const refreshBtn = document.getElementById('refresh-terminal-btn');
    Object.keys(data.terminals).forEach(sessionId => {
        const tab = document.createElement('button');
        tab.className = `term-tab${sessionId === data.activeSessionId ? ' active' : ''}`;
        tab.dataset.session = sessionId;
        const termNum = data.sessions[sessionId]?.num || '?';
        tab.innerHTML = `Term ${termNum} <span class="close-term" data-session="${sessionId}">×</span>`;
        tab.addEventListener('click', (e) => {
            if (!e.target.classList.contains('close-term')) switchTerminal(sessionId);
        });
        tab.querySelector('.close-term').addEventListener('click', (e) => {
            e.stopPropagation();
            closeTerminal(sessionId);
        });
        tabBar.insertBefore(tab, refreshBtn);
    });
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

// ----- Terminal management -----
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
    fitAllTerminals();
});

function applyFontSize(size) {
    Object.values(clientTerminals).forEach(client => {
        Object.values(client.terminals).forEach(term => {
            term.options.fontSize = size;
            term._addon?.fit();
        });
    });
}
document.getElementById('font-size-slider').addEventListener('input', (e) => {
    const size = parseInt(e.target.value);
    localStorage.setItem('terminalFontSize', size);
    defaultFontSize = size;
    applyFontSize(size);
});

function createNewTerminal() {
    if (!currentClient) return;
    socket.emit('new_terminal', currentClient, (sessionId) => {
        if (!sessionId) return;
        const data = clientTerminals[currentClient];
        data.tabCounter++;
        const termNum = data.tabCounter;
        data.sessions[sessionId] = { num: termNum };

        const termDiv = document.createElement('div');
        termDiv.id = `term-${sessionId}`;
        termDiv.className = 'active';
        document.getElementById('terminal-container').appendChild(termDiv);

        const term = new Terminal({
            cursorBlink: true,
            fontSize: defaultFontSize,
            theme: { background: '#0a0e17', foreground: '#e0e6f0' }
        });
        term.open(termDiv);
        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term._addon = fitAddon;
        fitAddon.fit();
        data.terminals[sessionId] = term;

        term.onResize(size => socket.emit('terminal_resize', { sessionId, cols: size.cols, rows: size.rows }));
        term.onData(data => socket.emit('terminal_input', { sessionId, data }));

        rebuildTabBar(currentClient);
        switchTerminal(sessionId);
        new ResizeObserver(() => fitAddon.fit()).observe(termDiv);
        setTimeout(() => fitAddon.fit(), 100);
    });
}

function switchTerminal(sessionId) {
    if (!currentClient) return;
    const data = clientTerminals[currentClient];
    document.querySelectorAll('#terminal-container > div').forEach(d => d.classList.remove('active'));
    const target = document.getElementById(`term-${sessionId}`);
    if (target) target.classList.add('active');
    data.activeSessionId = sessionId;
    document.querySelectorAll('.term-tab').forEach(b => b.classList.remove('active'));
    document.querySelector(`.term-tab[data-session="${sessionId}"]`)?.classList.add('active');
    // Fit the newly visible terminal
    const term = data.terminals[sessionId];
    if (term) setTimeout(() => term._addon?.fit(), 50);
}

function closeTerminal(sessionId) {
    if (!currentClient) return;
    const data = clientTerminals[currentClient];
    socket.emit('close_terminal', { sessionId });
    const term = data.terminals[sessionId];
    if (term) {
        term.dispose();
        delete data.terminals[sessionId];
    }
    delete data.sessions[sessionId];
    document.getElementById(`term-${sessionId}`)?.remove();
    if (data.activeSessionId === sessionId) {
        data.activeSessionId = Object.keys(data.terminals)[0] || null;
    }
    rebuildTabBar(currentClient);
    if (Object.keys(data.terminals).length === 0) {
        createNewTerminal();
    } else if (data.activeSessionId) {
        switchTerminal(data.activeSessionId);
    }
}

document.getElementById('refresh-terminal-btn').addEventListener('click', () => {
    const activeSession = clientTerminals[currentClient]?.activeSessionId;
    if (activeSession) closeTerminal(activeSession);
    else if (currentClient) createNewTerminal();
});

document.getElementById('clear-terminal-btn').addEventListener('click', () => {
    const activeSession = clientTerminals[currentClient]?.activeSessionId;
    if (activeSession && clientTerminals[currentClient]?.terminals[activeSession]) {
        clientTerminals[currentClient].terminals[activeSession].clear();
    }
});

document.getElementById('new-terminal-btn').addEventListener('click', createNewTerminal);

// ----- Quick commands (FAB & drawer) -----
const fab = document.getElementById('command-fab');
const drawer = document.getElementById('command-drawer');
fab.addEventListener('click', () => drawer.classList.toggle('open'));

function renderCommandUI() {
    const historyDiv = document.getElementById('command-history');
    historyDiv.innerHTML = commandHistory.slice(-10).reverse().map(cmd =>
        `<div class="command-item">
            <span>${escapeHtml(cmd)}</span>
            <button data-cmd="${escapeHtml(cmd)}" class="send-cmd"><i class="fas fa-paper-plane"></i></button>
        </div>`
    ).join('') || '<div class="text-muted small">No recent commands</div>';

    const savedDiv = document.getElementById('saved-commands');
    savedDiv.innerHTML = savedCommands.map((cmd, idx) =>
        `<div class="command-item">
            <span>${escapeHtml(cmd)}</span>
            <div>
                <button data-cmd="${escapeHtml(cmd)}" class="send-cmd"><i class="fas fa-play"></i></button>
                <button data-idx="${idx}" class="delete-cmd" style="color:var(--danger);"><i class="fas fa-trash"></i></button>
            </div>
        </div>`
    ).join('') || '<div class="text-muted small">No saved commands</div>';
}

function escapeHtml(text) {
    return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function sendCommandToActiveTerminal(cmd) {
    const activeSession = clientTerminals[currentClient]?.activeSessionId;
    if (activeSession && clientTerminals[currentClient]?.terminals[activeSession]) {
        clientTerminals[currentClient].terminals[activeSession].paste(cmd + '\n');
        if (!commandHistory.includes(cmd)) {
            commandHistory.push(cmd);
            if (commandHistory.length > 50) commandHistory.shift();
            localStorage.setItem('commandHistory', JSON.stringify(commandHistory));
            renderCommandUI();
        }
    }
}

document.getElementById('command-drawer').addEventListener('click', (e) => {
    const sendBtn = e.target.closest('.send-cmd');
    const delBtn = e.target.closest('.delete-cmd');
    if (sendBtn) {
        sendCommandToActiveTerminal(sendBtn.dataset.cmd);
    }
    if (delBtn) {
        const idx = parseInt(delBtn.dataset.idx);
        savedCommands.splice(idx, 1);
        localStorage.setItem('savedCommands', JSON.stringify(savedCommands));
        renderCommandUI();
    }
});

document.getElementById('add-command-btn').addEventListener('click', () => {
    const input = document.getElementById('new-command-input');
    const cmd = input.value.trim();
    if (cmd) {
        savedCommands.push(cmd);
        localStorage.setItem('savedCommands', JSON.stringify(savedCommands));
        input.value = '';
        renderCommandUI();
    }
});

// ----- Metrics & processes -----
function updateMetricsUI(metrics) {
    const grid = document.getElementById('metrics-grid');
    if (!grid) return;
    const hidden = JSON.parse(localStorage.getItem('hiddenMetrics') || '[]');
    grid.innerHTML = `
        <div class="metric-card" data-metric="cpu" ${hidden.includes('cpu') ? 'style="display:none"' : ''}>
            <button class="hide-metric" data-metric="cpu"><i class="fas fa-eye-slash"></i></button>
            <div class="metric-header"><i class="fas fa-microchip"></i><span class="metric-title">CPU</span></div>
            <div class="metric-main">${metrics.cpu || 0}%</div>
            <div class="metric-detail">${metrics.cpu_model || 'Unknown'} (${metrics.cpu_cores || 'N/A'} cores)</div>
            <div class="progress"><div class="progress-bar" style="width:${metrics.cpu || 0}%"></div></div>
        </div>
        <div class="metric-card" data-metric="ram" ${hidden.includes('ram') ? 'style="display:none"' : ''}>
            <button class="hide-metric" data-metric="ram"><i class="fas fa-eye-slash"></i></button>
            <div class="metric-header"><i class="fas fa-memory"></i><span class="metric-title">RAM</span></div>
            <div class="metric-main">${metrics.ram_percent || 0}%</div>
            <div class="metric-detail">${metrics.used_ram || '0'} / ${metrics.total_ram || 'N/A'}</div>
            <div class="progress"><div class="progress-bar" style="width:${metrics.ram_percent || 0}%; background:#50fa7b;"></div></div>
        </div>
        <div class="metric-card" data-metric="disk" ${hidden.includes('disk') ? 'style="display:none"' : ''}>
            <button class="hide-metric" data-metric="disk"><i class="fas fa-eye-slash"></i></button>
            <div class="metric-header"><i class="fas fa-hdd"></i><span class="metric-title">Disk</span></div>
            <div class="metric-main">${metrics.disk_percent || 0}%</div>
            <div class="metric-detail">${metrics.disk_used || '0'} / ${metrics.disk_total || 'N/A'}</div>
            <div class="progress"><div class="progress-bar" style="width:${metrics.disk_percent || 0}%; background:#f1fa8c;"></div></div>
        </div>
        <div class="metric-card" data-metric="net" ${hidden.includes('net') ? 'style="display:none"' : ''}>
            <button class="hide-metric" data-metric="net"><i class="fas fa-eye-slash"></i></button>
            <div class="metric-header"><i class="fas fa-wifi"></i><span class="metric-title">Network</span></div>
            <div class="metric-main">↓ ${metrics.net_down || '0'}</div>
            <div class="metric-detail">↑ ${metrics.net_up || '0'}</div>
        </div>`;
    document.querySelectorAll('.hide-metric').forEach(btn => {
        btn.addEventListener('click', () => {
            const metric = btn.dataset.metric;
            const card = btn.closest('.metric-card');
            card.style.display = 'none';
            let hidden = JSON.parse(localStorage.getItem('hiddenMetrics') || '[]');
            if (!hidden.includes(metric)) hidden.push(metric);
            localStorage.setItem('hiddenMetrics', JSON.stringify(hidden));
        });
    });
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

// ----- Socket events -----
socket.on('connect', () => console.log('Connected'));
socket.on('client_list', renderClientList);
socket.on('client_connected', data => showToast(`${data.name} connected`));
socket.on('client_disconnected', data => showToast(`${data.name} disconnected`));

socket.on('metrics_update', data => {
    if (currentClient === data.sid) updateMetricsUI(data.metrics);
});
socket.on('terminal_output', data => {
    for (const clientSid in clientTerminals) {
        if (clientTerminals[clientSid].terminals[data.sessionId]) {
            clientTerminals[clientSid].terminals[data.sessionId].write(data.output);
            break;
        }
    }
});
socket.on('process_list', data => {
    if (data.target_sid === currentClient) renderProcessTable(data.processes);
});

socket.emit('get_clients');
renderCommandUI();
applyFontSize(defaultFontSize);
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

def broadcast_client_list():
    emit('client_list', {
        sid: {'name': info['name'], 'metrics': info['metrics']}
        for sid, info in clients.items()
    }, broadcast=True)

@socketio.on('connect')
def handle_connect(auth=None):
    print(f"[+] Connected: {request.sid}")
    name = request.sid[:8]
    clients[request.sid] = {'name': name, 'metrics': {}}
    terminal_sessions[request.sid] = {}
    broadcast_client_list()
    emit('client_connected', {'name': name}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    dead = [s for s, owner in session_owners.items() if owner == sid]
    for s in dead:
        del session_owners[s]
    name = clients[sid]['name'] if sid in clients else 'Unknown'
    clients.pop(sid, None)
    terminal_sessions.pop(sid, None)
    broadcast_client_list()
    emit('client_disconnected', {'name': name}, broadcast=True)

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
    for browser_sid, target in client_watchers.items():
        if target == request.sid:
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
    target_sid = request.sid
    browser_sid = client_watchers.get(target_sid)
    if browser_sid:
        emit('terminal_output', {'sessionId': data.get('session_id'), 'output': data.get('output', '')}, room=browser_sid)

@socketio.on('get_processes')
def handle_get_processes(target_sid):
    if target_sid in clients:
        emit('list_processes', {}, room=target_sid)

@socketio.on('process_list')
def handle_process_list(data):
    target_sid = request.sid
    browser_sid = client_watchers.get(target_sid)
    if browser_sid:
        emit('process_list', {'target_sid': target_sid, 'processes': data.get('processes', [])}, room=browser_sid)

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
