#!/usr/bin/env python3
"""ps-usage-map-win: local server that samples per-process resource usage on Windows
(via psutil) and serves a treemap/heatmap web UI."""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
INTERVAL = 2  # seconds between samples
PORT = int(os.environ.get("PORT", "8765"))
MAX_LIST = 40

_lock = threading.Lock()
_snapshot = {"time": 0, "processes": [], "system": {}}

# --- per-process sockets (psutil.net_connections): listening ports and connections ---
_sockets = {}   # pid -> {"sockets": n, "listen": [...], "conns": [...]}
_sock_lock = threading.Lock()


def addr(a):
    return f"{a.ip}:{a.port}" if a else ""


def sample_sockets():
    out = {}
    for c in psutil.net_connections(kind="inet"):
        if not c.pid:
            continue
        proto = "TCP" if c.type == 1 else "UDP"  # SOCK_STREAM == 1
        d = out.setdefault(c.pid, {"sockets": 0, "listen": [], "conns": []})
        d["sockets"] += 1
        if c.raddr:
            item = f"{proto} {addr(c.laddr)}->{addr(c.raddr)} {c.status}".rstrip()
            if proto == "UDP":
                item = f"{proto} {addr(c.laddr)}->{addr(c.raddr)}"
            if item not in d["conns"]:
                d["conns"].append(item)
        elif c.laddr and (proto == "UDP" or c.status == psutil.CONN_LISTEN):
            item = f"{proto} {addr(c.laddr)}"
            if item not in d["listen"]:
                d["listen"].append(item)
    for d in out.values():
        d["listen"] = sorted(d["listen"])[:MAX_LIST]
        d["conns"] = d["conns"][:MAX_LIST]
    return out


def socket_sampler():
    while True:
        try:
            data = sample_sockets()
            with _sock_lock:
                _sockets.clear()
                _sockets.update(data)
        except Exception:
            pass
        time.sleep(INTERVAL)


# --- main sampler ---
_procs = {}       # pid -> (create_time, psutil.Process) so cpu_percent keeps its baseline
_disk_prev = {}   # pid -> (read_bytes, write_bytes, time)


def disk_rate(pid, io, now):
    """Return (read B/s, write B/s) since previous sample, or (0, 0)."""
    rd, wr = io.read_bytes, io.write_bytes
    prev = _disk_prev.get(pid)
    _disk_prev[pid] = (rd, wr, now)
    if not prev or now <= prev[2] or rd < prev[0] or wr < prev[1]:
        return 0.0, 0.0
    dt = now - prev[2]
    return (rd - prev[0]) / dt, (wr - prev[1]) / dt


def app_name(name):
    return name[:-4] if name.lower().endswith(".exe") else name


def sample():
    now = time.time()
    with _sock_lock:
        socks = dict(_sockets)
    rows, live = [], set()
    for p in psutil.process_iter():
        pid = p.pid
        if pid == 0:  # System Idle Process: not a real consumer
            continue
        try:
            ct = p.create_time()
            cached = _procs.get(pid)
            if cached and cached[0] == ct:
                p = cached[1]
            else:
                p.cpu_percent(None)  # prime baseline
                _procs[pid] = (ct, p)
                cached = None
            with p.oneshot():
                name = p.name()
                cpu = p.cpu_percent(None) if cached else 0.0
                mem = p.memory_info().rss
                state = p.status()
                try:
                    user = p.username().split("\\")[-1]
                except (psutil.AccessDenied, psutil.Error):
                    user = "?"
                try:
                    path = p.exe()
                except (psutil.AccessDenied, psutil.Error):
                    path = ""
                try:
                    dr, dw = disk_rate(pid, p.io_counters(), now)
                except (psutil.AccessDenied, psutil.Error, AttributeError):
                    dr, dw = 0.0, 0.0
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied:
            continue
        live.add(pid)
        sk = socks.get(pid, {})
        rows.append({
            "pid": pid, "command": name, "name": name, "app": app_name(name),
            "path": path, "cpu": cpu, "mem": float(mem), "state": state, "user": user,
            "disk_read": dr, "disk_write": dw,
            "sockets": sk.get("sockets", 0), "listen": sk.get("listen", []), "conns": sk.get("conns", []),
        })
    for d in (_procs, _disk_prev):
        for pid in [k for k in d if k not in live]:
            del d[pid]
    vm = psutil.virtual_memory()
    system = {
        "CPU usage": f"{psutil.cpu_percent(None):.1f}% ({psutil.cpu_count()} logical cores)",
        "PhysMem": f"{vm.used / 2**30:.1f}G used, {vm.available / 2**30:.1f}G available of {vm.total / 2**30:.1f}G",
    }
    return {"time": now, "processes": rows, "system": system}


def sampler():
    psutil.cpu_percent(None)
    sample()  # prime CPU baselines; first sample's CPU is not a delta
    while True:
        time.sleep(INTERVAL)
        snap = sample()
        with _lock:
            _snapshot.update(snap)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/processes"):
            with _lock:
                body = json.dumps(_snapshot).encode()
            self._send(body, "application/json")
        elif self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self._send(f.read(), "text/html; charset=utf-8")
        else:
            self.send_error(404)


if __name__ == "__main__":
    threading.Thread(target=sampler, daemon=True).start()
    threading.Thread(target=socket_sampler, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"ps-usage-map-win running at http://127.0.0.1:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
