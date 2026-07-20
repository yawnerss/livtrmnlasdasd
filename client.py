#!/usr/bin/env python3
import sys
import subprocess
import importlib

# ---------- Auto‑install missing modules ----------
def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    import socketio
except ImportError:
    print("Installing python-socketio...")
    install("python-socketio")
    import socketio

try:
    import psutil
except ImportError:
    print("Installing psutil...")
    install("psutil")
    import psutil

import os
import time
import threading
import pty
import select
import struct
import fcntl
import termios
import socket

# ---------- Configuration ----------
SERVER_URL = "https://livtrmnlasdasd.onrender.com"  # CHANGE THIS
CLIENT_NAME = socket.gethostname()

# ---------- Terminal session management ----------
sessions = {}  # session_id -> {'process': proc, 'master_fd': fd, 'slave_fd': fd}
output_threads = {}

def spawn_terminal(session_id, cols=80, rows=24):
    """Spawn a bash shell with PTY."""
    master_fd, slave_fd = pty.openpty()
    # Set window size
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    process = subprocess.Popen(
        ['/bin/bash', '-i'],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
        close_fds=True
    )
    sessions[session_id] = {
        'process': process,
        'master_fd': master_fd,
        'slave_fd': slave_fd,
        'pid': process.pid
    }
    # Start a thread to read output
    def read_output():
        while session_id in sessions:
            try:
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if master_fd in r:
                    data = os.read(master_fd, 1024)
                    if data:
                        sio.emit('terminal_output', {'session_id': session_id, 'output': data.decode('utf-8', errors='replace')})
                    else:
                        break
            except (OSError, ValueError):
                break
        # Clean up if process ended
        if session_id in sessions:
            sessions[session_id]['process'].terminate()
            del sessions[session_id]
    thread = threading.Thread(target=read_output, daemon=True)
    thread.start()
    output_threads[session_id] = thread
    return session_id

def close_terminal(session_id):
    if session_id in sessions:
        proc = sessions[session_id]['process']
        proc.terminate()
        time.sleep(0.1)
        if proc.poll() is None:
            proc.kill()
        os.close(sessions[session_id]['master_fd'])
        os.close(sessions[session_id]['slave_fd'])
        del sessions[session_id]
        if session_id in output_threads:
            del output_threads[session_id]

def resize_terminal(session_id, cols, rows):
    if session_id in sessions:
        master_fd = sessions[session_id]['master_fd']
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

# ---------- Metrics collection ----------
def get_metrics():
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net = psutil.net_io_counters()
    # Compute upload/download speeds (bytes per second over 1s interval)
    # We'll keep it simple: send current total bytes, UI can compute speed
    # For now, just send a formatted string
    net_speed = f"{net.bytes_sent//1024} KB/s ↑ {net.bytes_recv//1024} KB/s ↓"
    return {
        'cpu': cpu,
        'ram_percent': ram.percent,
        'disk_percent': disk.percent,
        'net_speed': net_speed
    }

def send_metrics():
    while True:
        try:
            metrics = get_metrics()
            sio.emit('metrics', {'metrics': metrics})
        except Exception as e:
            print(f"Metrics error: {e}")
        time.sleep(2)

# ---------- Socket.IO client ----------
sio = socketio.Client(reconnection=True, reconnection_attempts=0)

@sio.event
def connect():
    print("Connected to server")
    sio.emit('register_client', {'name': CLIENT_NAME})
    threading.Thread(target=send_metrics, daemon=True).start()

@sio.event
def disconnect():
    print("Disconnected from server")
    for sid in list(sessions.keys()):
        close_terminal(sid)

@sio.event
def spawn_terminal(data):
    session_id = data.get('session_id')
    if session_id in sessions:
        return
    spawn_terminal(session_id)
    sio.emit('terminal_ready', {'session_id': session_id})

@sio.event
def terminal_input(data):
    session_id = data.get('session_id')
    input_data = data.get('data')
    if session_id in sessions:
        master_fd = sessions[session_id]['master_fd']
        try:
            os.write(master_fd, input_data.encode())
        except Exception as e:
            print(f"Write error: {e}")

@sio.event
def terminal_resize(data):
    session_id = data.get('session_id')
    cols = data.get('cols')
    rows = data.get('rows')
    resize_terminal(session_id, cols, rows)

@sio.event
def close_terminal(data):
    session_id = data.get('session_id')
    close_terminal(session_id)

@sio.event
def ping():
    sio.emit('pong')

# ---------- Main ----------
if __name__ == '__main__':
    try:
        sio.connect(SERVER_URL)
        print("Client running. Press Ctrl+C to exit.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting...")
        sio.disconnect()
        sys.exit(0)
    except Exception as e:
        print(f"Connection error: {e}")
        sys.exit(1)
