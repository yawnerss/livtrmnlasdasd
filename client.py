#!/usr/bin/env python3
import sys, subprocess, os, time, threading, select, struct, fcntl, termios, socket, traceback, platform

def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

try:
    import socketio
except ImportError:
    install("python-socketio")
    import socketio
try:
    import psutil
except ImportError:
    install("psutil")
    import psutil

SERVER_URL = "https://livtrmnlasdasd-ey03.onrender.com"   # your actual Render URL
CLIENT_NAME = socket.gethostname()
IS_WINDOWS = platform.system() == 'Windows'

sessions = {}
output_threads = {}
_net_prev = None
_net_prev_time = None

# --- Shell spawning ---
def _spawn_terminal(session_id, cols=80, rows=24):
    try:
        env = os.environ.copy()
        env['TERM'] = 'xterm-256color' if not IS_WINDOWS else ''
        if IS_WINDOWS:
            # Windows: use cmd.exe with pipes
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.Popen('cmd.exe', stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, startupinfo=startupinfo, env=env, bufsize=0)
            sessions[session_id] = {'process': proc, 'stdin': proc.stdin, 'stdout': proc.stdout,
                                    'pid': proc.pid, 'is_windows': True}
            proc.stdin.write(b'\r\n')
            proc.stdin.flush()
        else:
            import pty
            master_fd, slave_fd = pty.openpty()
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
            shell = '/bin/bash' if os.path.exists('/bin/bash') else '/bin/sh'
            proc = subprocess.Popen([shell, '-i'], stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                                    preexec_fn=os.setsid, close_fds=True, env=env)
            os.close(slave_fd)
            sessions[session_id] = {'process': proc, 'master_fd': master_fd, 'pid': proc.pid, 'is_windows': False}
            time.sleep(0.3)
            os.write(master_fd, b'\n')

        def read_output():
            sess = sessions[session_id]
            while session_id in sessions:
                try:
                    if sess['is_windows']:
                        chunk = sess['stdout'].read(4096)
                        if not chunk: break
                    else:
                        r, _, _ = select.select([sess['master_fd']], [], [], 0.1)
                        if sess['master_fd'] in r:
                            chunk = os.read(sess['master_fd'], 4096)
                        else:
                            continue
                    if chunk and sio.connected:
                        sio.emit('terminal_output', {'session_id': session_id, 'output': chunk.decode('utf-8', errors='replace')})
                    if sess['process'].poll() is not None:
                        break
                except:
                    break
            if session_id in sessions:
                try: sessions[session_id]['process'].terminate()
                except: pass
                sessions.pop(session_id, None)
                output_threads.pop(session_id, None)

        t = threading.Thread(target=read_output, daemon=True)
        t.start()
        output_threads[session_id] = t
        print(f"[SPAWN] {session_id}  PID={proc.pid}")
        return session_id
    except Exception as e:
        print(f"[SPAWN ERROR] {e}\n{traceback.format_exc()}")
        return None

def _close_terminal(session_id):
    sess = sessions.pop(session_id, None)
    if not sess: return
    try:
        sess['process'].terminate()
        time.sleep(0.1)
        if sess['process'].poll() is None: sess['process'].kill()
        if not sess.get('is_windows'): os.close(sess['master_fd'])
    except: pass
    output_threads.pop(session_id, None)

def _resize_terminal(session_id, cols, rows):
    sess = sessions.get(session_id)
    if not sess or sess.get('is_windows'): return
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(sess['master_fd'], termios.TIOCSWINSZ, winsize)
    except Exception as e:
        print(f"[RESIZE ERROR] {e}")

# --- Metrics ---
def get_network_speed():
    global _net_prev, _net_prev_time
    cur = psutil.net_io_counters()
    now = time.time()
    if _net_prev is None:
        _net_prev, _net_prev_time = cur, now
        return "0 B/s", "0 B/s"
    dt = now - _net_prev_time
    if dt == 0: return "0 B/s", "0 B/s"
    down = (cur.bytes_recv - _net_prev.bytes_recv) / dt
    up = (cur.bytes_sent - _net_prev.bytes_sent) / dt
    _net_prev, _net_prev_time = cur, now
    def fmt(b):
        if b >= 1e6: return f"{b/1e6:.1f} MB/s"
        if b >= 1e3: return f"{b/1e3:.1f} KB/s"
        return f"{b:.0f} B/s"
    return fmt(down), fmt(up)

def get_metrics():
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    down, up = get_network_speed()
    cpu_model = platform.processor() or "Unknown"
    if not IS_WINDOWS:
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line: cpu_model = line.split(":")[1].strip(); break
        except: pass
    return {
        'cpu': cpu, 'cpu_cores': psutil.cpu_count(logical=True), 'cpu_model': cpu_model,
        'ram_percent': ram.percent, 'total_ram': f"{ram.total/1e9:.1f} GB",
        'used_ram': f"{ram.used/1e9:.1f} GB", 'available_ram': f"{ram.available/1e9:.1f} GB",
        'disk_percent': disk.percent, 'disk_total': f"{disk.total/1e9:.1f} GB",
        'disk_used': f"{disk.used/1e9:.1f} GB",
        'net_speed': f"{down} ↓ {up} ↑", 'net_down': down, 'net_up': up
    }

def send_metrics():
    while True:
        if sio.connected:
            try: sio.emit('metrics', {'metrics': get_metrics()})
            except: pass
        time.sleep(2)

def keep_alive_ping():
    while True:
        time.sleep(30)
        if sio.connected:
            try: sio.emit('ping')
            except: pass

def list_processes():
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try: procs.append({'pid': p.info['pid'], 'name': p.info['name'],
                           'cpu_percent': p.info['cpu_percent'] or 0, 'mem_percent': p.info['memory_percent'] or 0})
        except: pass
    procs.sort(key=lambda x: x['cpu_percent'], reverse=True)
    return procs

def kill_process(pid):
    try: psutil.Process(pid).kill(); return True
    except: return False

# --- SocketIO ---
sio = socketio.Client(reconnection=True, reconnection_attempts=0)

@sio.event
def connect():
    print(f"[CONNECTED] to {SERVER_URL}")
    sio.emit('register_client', {'name': CLIENT_NAME})
    if sessions:
        for sid in sessions: sio.emit('terminal_ready', {'session_id': sid})
    if not hasattr(sio, '_bg_started'):
        sio._bg_started = True
        threading.Thread(target=send_metrics, daemon=True).start()
        threading.Thread(target=keep_alive_ping, daemon=True).start()

@sio.event
def disconnect():
    print("[DISCONNECTED]")

@sio.event
def spawn_terminal(data):
    sid = data.get('session_id')
    if sid and sid not in sessions:
        if _spawn_terminal(sid): sio.emit('terminal_ready', {'session_id': sid})
        else: sio.emit('terminal_error', {'session_id': sid, 'error': 'spawn failed'})

@sio.event
def terminal_input(data):
    sess = sessions.get(data.get('session_id'))
    if sess and data.get('data'):
        try:
            if sess.get('is_windows'):
                sess['stdin'].write(data['data'].encode())
                sess['stdin'].flush()
            else:
                os.write(sess['master_fd'], data['data'].encode())
        except: pass

@sio.event
def terminal_resize(data):
    _resize_terminal(data.get('session_id'), data.get('cols', 80), data.get('rows', 24))

@sio.event
def close_terminal(data):
    _close_terminal(data.get('session_id'))

@sio.event
def list_processes():
    if sio.connected:
        try: sio.emit('process_list', {'processes': list_processes()})
        except: sio.emit('process_list', {'processes': []})

@sio.event
def kill_process(data):
    pid = data.get('pid')
    if pid: kill_process(pid)

@sio.event
def ping():
    if sio.connected: sio.emit('pong')

if __name__ == '__main__':
    while True:
        try:
            print(f"[INFO] Connecting to {SERVER_URL} as '{CLIENT_NAME}'")
            sio.connect(SERVER_URL, wait_timeout=10)
            sio.wait()
        except KeyboardInterrupt:
            sio.disconnect(); sys.exit(0)
        except:
            traceback.print_exc()
            time.sleep(5)
