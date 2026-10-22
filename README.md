# ps-usage-map-win

Windows port of [ps-usage-map](../ps-usage-map): a treemap + heatmap view of per-process resource usage (a Task Manager alternative).

- Size and color can each be switched between CPU, Memory, Disk Read/Write, Sockets
- Tooltip shows listening ports and TCP/UDP connections per process
- Group by app (executable name), filter by name, pause/resume (Space)
- Python server using `psutil` + the same single-page Canvas frontend

## Run

```powershell
pip install -r requirements.txt
python server.py            # http://127.0.0.1:8765
$env:PORT=9000; python server.py  # custom port
```

Requires Windows and Python 3.8+. Run from an elevated terminal to see disk I/O, paths and sockets of other users' / system processes.

## Differences from the macOS version

| macOS | Windows |
|-------|---------|
| `top` / `ps` | `psutil` |
| Energy impact column | dropped (no per-process equivalent) |
| Net In/Out via `nettop` | dropped (needs ETW; not available per process via psutil) |
| Disk I/O via `proc_pid_rusage` | `psutil` I/O counters (includes all I/O, not only disk) |
| Sockets via `lsof` | `psutil.net_connections` |
| Group by `.app` bundle | Group by executable name |
| Memory = `top` MEM | Working set (RSS) |
