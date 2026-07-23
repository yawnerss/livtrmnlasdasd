#!/usr/bin/env python3
import sys
import subprocess

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
import platform

SERVER_URL = "https://live-terminal-ricardo-cum.onrender.com"
CLIENT_NAME = socket.gethostname()

sessions = {}        # session_id -> {'process', 'master_fd', 'pid'}
output_threads = {}  # session_id -> Thread

# ---------- PTY helpers ----------
def _spawn_terminal(session_id, cols=80, rows=24):
    """Spawn a PTY-backed shell and start streaming its output."""
    try:
        master_fd, slave_fd = pty.openpty()

        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

        env = os.environ.copy()
        env['TERM'] = 'xterm-256color'
        env['PS1'] = '\\[\\033[01;32m\\]\\u@\\h\\[\\033[00m\\]:\\[\\033[01;34m\\]\\w\\[\\033[00m\\]\\$ '

        shell = '/bin/bash' if os.path.exists('/bin/bash') else '/bin/sh'

        process = subprocess.Popen(
            [shell, '-i'],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=os.setsid,
            close_fds=True,
            env=env
        )

        os.close(slave_fd)  # important: close slave in parent

        sessions[session_id] = {
            'process': process,
            'master_fd': master_fd,
            'pid': process.pid,
        }

        time.sleep(0.3)
        os.write(master_fd, b'\n')

        def read_output():
            while session_id in sessions:
                try:
                    r, _, _ = select.select([master_fd], [], [], 0.1)
                    if master_fd in r:
                        try:
                            chunk = os.read(master_fd, 4096)
                        except OSError:
                            break
                        if chunk:
                            if sio.connected:
                                sio.emit('terminal_output', {
                                    'session_id': session_id,
                                    'output': chunk.decode('utf-8', errors='replace')
                                })
                        else:
                            break
                    if session_id in sessions and sessions[session_id]['process'].poll() is not None:
                        break
                except Exception as e:
                    print(f"[READ ERROR] {session_id}: {e}")
                    break
            # Cleanup only if the process died – do NOT remove on disconnect
            if session_id in sessions:
                try:
                    sessions[session_id]['process'].terminate()
                except Exception:
                    pass
                sessions.pop(session_id, None)
                output_threads.pop(session_id, None)
                print(f"[CLEANUP] {session_id} removed (process died)")

        t = threading.Thread(target=read_output, daemon=True)
        t.start()
        output_threads[session_id] = t
        print(f"[SPAWN] {session_id}  PID={process.pid}  shell={shell}")
        return session_id

    except Exception as e:
        print(f"[SPAWN ERROR] {e}\n{traceback.format_exc()}")
        return None


def _close_terminal(session_id):
    """Terminate and clean up a PTY session (called only on explicit close)."""
    sess = sessions.pop(session_id, None)
    if not sess:
        return
    try:
        sess['process'].terminate()
        time.sleep(0.1)
        if sess['process'].poll() is None:
            sess['process'].kill()
        os.close(sess['master_fd'])
    except Exception as e:
        print(f"[CLOSE ERROR] {session_id}: {e}")
    output_threads.pop(session_id, None)
    print(f"[CLOSED] {session_id}")


def _resize_terminal(session_id, cols, rows):
    sess = sessions.get(session_id)
    if not sess:
        return
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(sess['master_fd'], termios.TIOCSWINSZ, winsize)
    except Exception as e:
        print(f"[RESIZE ERROR] {session_id}: {e}")


# ---------- Enhanced Metrics ----------
_net_prev = None
_net_prev_time = None

def get_network_speed():
    """Calculate download/upload speeds in MB/s or KB/s since last call."""
    global _net_prev, _net_prev_time
    current = psutil.net_io_counters()
    now = time.time()
    if _net_prev is None or _net_prev_time is None:
        _net_prev = current
        _net_prev_time = now
        return "0 B/s", "0 B/s"
    dt = now - _net_prev_time
    if dt == 0:
        return "0 B/s", "0 B/s"
    down_bytes = current.bytes_recv - _net_prev.bytes_recv
    up_bytes = current.bytes_sent - _net_prev.bytes_sent
    _net_prev = current
    _net_prev_time = now

    def fmt(b):
        if b >= 1024*1024:
            return f"{b/(1024*1024):.1f} MB/s"
        elif b >= 1024:
            return f"{b/1024:.1f} KB/s"
        else:
            return f"{b:.0f} B/s"
    return fmt(down_bytes), fmt(up_bytes)

def get_cpu_model():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "model name" in line:
                    return line.split(":")[1].strip()
    except:
        pass
    return platform.processor() or "Unknown"

def get_metrics():
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    down_speed, up_speed = get_network_speed()

    cpu_cores = psutil.cpu_count(logical=True)
    cpu_model = get_cpu_model()
    total_ram = f"{ram.total / (1024**3):.1f} GB"
    used_ram = f"{ram.used / (1024**3):.1f} GB"
    available_ram = f"{ram.available / (1024**3):.1f} GB"
    disk_total = f"{disk.total / (1024**3):.1f} GB"
    disk_used = f"{disk.used / (1024**3):.1f} GB"

    return {
        'cpu': cpu,
        'cpu_cores': cpu_cores,
        'cpu_model': cpu_model,
        'ram_percent': ram.percent,
        'total_ram': total_ram,
        'used_ram': used_ram,
        'available_ram': available_ram,
        'disk_percent': disk.percent,
        'disk_total': disk_total,
        'disk_used': disk_used,
        'net_speed': f"{down_speed} ↓ {up_speed} ↑",  # for sidebar badge
        'net_down': down_speed,
        'net_up': up_speed,
    }

def send_metrics():
    while True:
        try:
            if sio.connected:
                sio.emit('metrics', {'metrics': get_metrics()})
        except Exception as e:
            print(f"[METRICS ERROR] {e}")
        time.sleep(2)

def keep_alive_ping():
    """Send a ping every 30 seconds to keep the connection alive."""
    while True:
        time.sleep(30)
        if sio.connected:
            try:
                sio.emit('ping')
            except Exception:
                pass

# ---------- Process Management ----------
def list_processes():
    """Return a list of running processes with PID, name, CPU%, MEM%."""
    procs = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            info = proc.info
            procs.append({
                'pid': info['pid'],
                'name': info['name'],
                'cpu_percent': info['cpu_percent'] or 0.0,
                'mem_percent': info['memory_percent'] or 0.0,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    # Sort by CPU usage descending
    procs.sort(key=lambda x: x['cpu_percent'], reverse=True)
    return procs

def kill_process(pid):
    try:
        p = psutil.Process(pid)
        p.kill()
        print(f"[KILL] Process {pid} killed")
        return True
    except Exception as e:
        print(f"[KILL ERROR] PID {pid}: {e}")
        return False


# ---------- Socket.IO ----------
sio = socketio.Client(reconnection=True, reconnection_attempts=0)

@sio.event
def connect():
    print(f"[CONNECTED] to {SERVER_URL}")
    sio.emit('register_client', {'name': CLIENT_NAME})

    # Re‑attach any existing sessions so the server knows they are still alive
    if sessions:
        print(f"[REATTACH] sending {len(sessions)} active sessions")
        for sid in list(sessions.keys()):
            sio.emit('terminal_ready', {'session_id': sid})

    # Start background threads once
    if not hasattr(sio, '_background_started'):
        sio._background_started = True
        threading.Thread(target=send_metrics, daemon=True).start()
        threading.Thread(target=keep_alive_ping, daemon=True).start()


@sio.event
def disconnect():
    print("[DISCONNECTED] from server")
    # DO NOT close terminals – keep them alive for when we reconnect


@sio.event
def spawn_terminal(data):
    session_id = data.get('session_id')
    if not session_id or session_id in sessions:
        return
    result = _spawn_terminal(session_id)
    if result:
        sio.emit('terminal_ready', {'session_id': session_id})
    else:
        sio.emit('terminal_error', {'session_id': session_id, 'error': 'Failed to spawn shell'})


@sio.event
def terminal_input(data):
    session_id = data.get('session_id')
    input_data = data.get('data')
    sess = sessions.get(session_id)
    if sess and input_data:
        try:
            os.write(sess['master_fd'], input_data.encode())
        except Exception as e:
            print(f"[WRITE ERROR] {session_id}: {e}")


@sio.event
def terminal_resize(data):
    _resize_terminal(data.get('session_id'), data.get('cols', 80), data.get('rows', 24))


@sio.event
def close_terminal(data):
    _close_terminal(data.get('session_id'))


# ---------- NEW: Process Events ----------
@sio.event
def list_processes():
    """Server requests process list."""
    if sio.connected:
        try:
            procs = list_processes()
            sio.emit('process_list', {'processes': procs})
        except Exception as e:
            print(f"[PROC LIST ERROR] {e}")
            sio.emit('process_list', {'processes': []})


@sio.event
def kill_process(data):
    """Server requests to kill a specific PID."""
    pid = data.get('pid')
    if pid is not None:
        success = kill_process(pid)
        # Optionally send back a status (not required, but useful)
        # sio.emit('process_killed', {'pid': pid, 'success': success})


@sio.event
def ping():
    if sio.connected:
        sio.emit('pong')


# ---------- Entry point ----------
if __name__ == '__main__':
    while True:
        try:
            print(f"[INFO] Connecting to {SERVER_URL} as '{CLIENT_NAME}'")
            sio.connect(SERVER_URL, wait_timeout=10)
            print("[INFO] Client running. Press Ctrl+C to exit.")
            sio.wait()
            print("[INFO] Connection lost – reconnecting...")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n[INFO] Exiting...")
            sio.disconnect()
            sys.exit(0)
        except Exception as e:
            print(f"[ERROR] {e}\n{traceback.format_exc()}")
            time.sleep(5)
