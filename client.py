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

SERVER_URL = "server url"
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


def get_metrics():
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net = psutil.net_io_counters()
    net_speed = f"{net.bytes_sent // 1024} KB/s ↑ {net.bytes_recv // 1024} KB/s ↓"
    return {
        'cpu': cpu,
        'ram_percent': ram.percent,
        'disk_percent': disk.percent,
        'net_speed': net_speed,
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
                sio.emit('ping')  # or 'pong' – server should respond accordingly
            except Exception:
                pass


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
            sio.emit('terminal_ready', {'session_id': sid})  # tell server they exist

    # Start background threads once
    if not hasattr(sio, '_background_started'):
        sio._background_started = True
        threading.Thread(target=send_metrics, daemon=True).start()
        threading.Thread(target=keep_alive_ping, daemon=True).start()


@sio.event
def disconnect():
    print("[DISCONNECTED] from server")
    # DO NOT close terminals – keep them alive for when we reconnect
    # for sid in list(sessions.keys()):
    #     _close_terminal(sid)   # <-- REMOVED


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


@sio.event
def ping():
    if sio.connected:
        sio.emit('pong')


# ---------- Entry point ----------
if __name__ == '__main__':
    # Keep trying to connect forever, even if the server is down initially
    while True:
        try:
            print(f"[INFO] Connecting to {SERVER_URL} as '{CLIENT_NAME}'")
            sio.connect(SERVER_URL, wait_timeout=10)
            print("[INFO] Client running. Press Ctrl+C to exit.")
            sio.wait()  # blocks until disconnect
            print("[INFO] Connection lost – reconnecting...")
            time.sleep(5)  # wait a bit before retry
        except KeyboardInterrupt:
            print("\n[INFO] Exiting...")
            sio.disconnect()
            sys.exit(0)
        except Exception as e:
            print(f"[ERROR] {e}\n{traceback.format_exc()}")
            time.sleep(5)  # wait before retry
