#!/usr/bin/env python3
import sys
import subprocess
import importlib

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

import os, time, threading, pty, select, struct, fcntl, termios, socket, traceback

SERVER_URL = "https://livtrmnlasdasd.onrender.com"
CLIENT_NAME = socket.gethostname()

sessions = {}
output_threads = {}

def spawn_terminal(session_id, cols=80, rows=24):
    try:
        master_fd, slave_fd = pty.openpty()
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

        env = os.environ.copy()
        env['TERM'] = 'xterm-256color'
        env['PS1'] = '\\[\\033[01;32m\\]\\u@\\h\\[\\033[00m\\]:\\[\\033[01;34m\\]\\w\\[\\033[00m\\]\\$ '

        # Choose shell
        shell = '/bin/bash'
        if not os.path.exists(shell):
            shell = '/bin/sh'
            print(f"[WARN] /bin/bash not found, using {shell}")

        process = subprocess.Popen(
            [shell, '-i'],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=os.setsid,
            close_fds=True,
            env=env
        )
        sessions[session_id] = {
            'process': process,
            'master_fd': master_fd,
            'slave_fd': slave_fd,
            'pid': process.pid
        }

        # Force a newline to trigger prompt
        time.sleep(0.5)
        os.write(master_fd, b'\n')

        def read_output():
            while session_id in sessions:
                try:
                    r, _, _ = select.select([master_fd], [], [], 0.1)
                    if master_fd in r:
                        data = os.read(master_fd, 1024)
                        if data:
                            print(f"[READ] {len(data)} bytes from {session_id}")
                            if sio.connected:
                                sio.emit('terminal_output', {
                                    'session_id': session_id,
                                    'output': data.decode('utf-8', errors='replace')
                                })
                        else:
                            break
                except Exception as e:
                    print(f"[READ ERROR] {e}")
                    break
            if session_id in sessions:
                sessions[session_id]['process'].terminate()
                del sessions[session_id]
                print(f"[CLEANUP] {session_id} removed")

        thread = threading.Thread(target=read_output, daemon=True)
        thread.start()
        output_threads[session_id] = thread
        print(f"[SPAWN] {session_id} PID {process.pid} shell={shell}")
        return session_id
    except Exception as e:
        print(f"[SPAWN ERROR] {e}\n{traceback.format_exc()}")
        return None

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

def get_metrics():
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net = psutil.net_io_counters()
    net_speed = f"{net.bytes_sent//1024} KB/s ↑ {net.bytes_recv//1024} KB/s ↓"
    return {'cpu': cpu, 'ram_percent': ram.percent, 'disk_percent': disk.percent, 'net_speed': net_speed}

def send_metrics():
    while True:
        try:
            if sio.connected:
                sio.emit('metrics', {'metrics': get_metrics()})
            else:
                time.sleep(1)
        except Exception as e:
            print(f"Metrics error: {e}")
        time.sleep(2)

sio = socketio.Client(reconnection=True, reconnection_attempts=0)

@sio.event
def connect():
    print("Connected to server")
    sio.emit('register_client', {'name': CLIENT_NAME})
    if not hasattr(sio, '_metrics_thread_started'):
        sio._metrics_thread_started = True
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
    result = spawn_terminal(session_id)
    if result:
        sio.emit('terminal_ready', {'session_id': session_id})
    else:
        # Send error to server (so UI can show it)
        sio.emit('terminal_error', {'session_id': session_id, 'error': 'Failed to spawn shell'})

@sio.event
def terminal_input(data):
    session_id = data.get('session_id')
    input_data = data.get('data')
    if session_id in sessions:
        try:
            os.write(sessions[session_id]['master_fd'], input_data.encode())
        except Exception as e:
            print(f"Write error: {e}")

@sio.event
def terminal_resize(data):
    resize_terminal(data.get('session_id'), data.get('cols'), data.get('rows'))

@sio.event
def close_terminal(data):
    close_terminal(data.get('session_id'))

@sio.event
def ping():
    if sio.connected:
        sio.emit('pong')

if __name__ == '__main__':
    try:
        sio.connect(SERVER_URL, wait_timeout=10)
        print("Client running. Press Ctrl+C to exit.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting...")
        sio.disconnect()
        sys.exit(0)
    except Exception as e:
        print(f"Connection error: {e}\n{traceback.format_exc()}")
        sys.exit(1)
