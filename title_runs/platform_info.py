"""What the client asks of the machine: GPU, driver and OS; dumps in a folder; mains power; idle time; whether a game or
a fullscreen program runs. Linux and Windows implementations side by side, so the UI code calls only these.

Windows paths are written but not yet run on a Windows machine (DESIGN.md: Linux and Windows from the start).
"""

import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

WINDOWS = platform.system() == "Windows"


def _run(*argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def gpu():
    """(name, driver) of the first GPU, as well as the machine can tell."""
    if shutil.which("nvidia-smi"):
        line = _run("nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader").splitlines()
        if line:
            name, driver = [part.strip() for part in line[0].split(",", 1)]
            return name, f"NVIDIA {driver}"
    if WINDOWS:
        out = _run("powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -First 1 Name,DriverVersion | ConvertTo-Json")
        try:
            data = json.loads(out)
            return data.get("Name", "unknown GPU"), data.get("DriverVersion", "")
        except json.JSONDecodeError:
            return "unknown GPU", ""
    for line in _run("lspci", "-mm").splitlines():
        fields = re.findall(r'"([^"]*)"', line)
        if len(fields) >= 3 and ("VGA" in fields[0] or "3D" in fields[0] or "Display" in fields[0]):
            mesa = re.search(r"Mesa ([0-9.]+)", _run("glxinfo", "-B"))
            return f"{fields[1]} {fields[2]}", f"Mesa {mesa.group(1)}" if mesa else ""
    return "unknown GPU", ""


def os_name():
    if WINDOWS:
        return f"Windows {platform.release()} ({platform.version()})"
    return f"{platform.system()} {platform.release()}"


def machine_id():
    """A stable name for this computer, whatever the tester calls the machine: the warm-up records key on it, since
    the caches belong to the computer (a hash of /etc/machine-id, or Windows' MachineGuid; the host name otherwise)."""
    import hashlib
    raw = ""
    if WINDOWS:
        out = _run("reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid")
        found = re.search(r"MachineGuid\s+REG_SZ\s+(\S+)", out)
        raw = found.group(1) if found else ""
    else:
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                raw = Path(path).read_text().strip()
            except OSError:
                continue
            if raw:
                break
    raw = raw or platform.node()
    return "host-" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def machine_info():
    name, driver = gpu()
    system = os_name()
    return {"gpu": name, "driver": driver, "os": system}


def search_folder(text):
    """The folder a tester gave: typed, pasted with spaces around it, or pasted from a file manager as a file:// link.
    Nothing given means the home folder."""
    import urllib.parse
    text = (text or "").strip().strip('"').strip("'")
    if text.startswith("file://"):
        text = urllib.parse.unquote(urllib.parse.urlparse(text).path)
    return Path(text).expanduser() if text else Path.home()


def find_dumps(folder, depth=3, skip=()):
    """Extracted packages under folder (eboot.bin and sce_sys/param.json): [{"title_id", "name", "version", "path"}].
    skip: folders not to look in (the client's own state, whose game folders are copies). One entry per title and
    version: the first found."""
    found = []
    folder = search_folder(folder) if not isinstance(folder, Path) else folder
    skip = {Path(s).expanduser().resolve() for s in skip}
    if not folder.is_dir():
        return found
    stack = [(folder, 0)]
    while stack:
        path, level = stack.pop()
        if path.resolve() in skip:
            continue
        param = path / "sce_sys" / "param.json"
        if (path / "eboot.bin").is_file() and param.is_file():
            try:
                data = json.loads(param.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            names = data.get("localizedParameters", {})
            language = names.get("defaultLanguage", "en-US")
            name = names.get(language, {}).get("titleName") or data.get("titleId", "?")
            entry = {"title_id": data.get("titleId", "?"), "name": name, "version": data.get("contentVersion", "?"), "path": str(path)}
            if not any(f["title_id"] == entry["title_id"] and f["version"] == entry["version"] for f in found):
                found.append(entry)
            continue
        if level < depth:
            try:
                children = sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith("."))
            except OSError:
                continue
            stack += [(child, level + 1) for child in reversed(children)]
    return sorted(found, key=lambda d: d["title_id"])


def on_mains():
    """True on mains power, False on battery, None when the machine does not say."""
    if WINDOWS:
        class Status(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte), ("BatteryLifePercent", ctypes.c_byte),
                        ("SystemStatusFlag", ctypes.c_byte), ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
        status = Status()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return {0: False, 1: True}.get(status.ACLineStatus)
        return None
    supplies = Path("/sys/class/power_supply")
    mains = [p for p in supplies.glob("*") if (p / "type").exists() and (p / "type").read_text().strip() == "Mains"] if supplies.exists() else []
    if not mains:
        return None
    return any((p / "online").read_text().strip() == "1" for p in mains)


def idle_seconds():
    """Seconds since the last keyboard or mouse input, or None when unknown."""
    if WINDOWS:
        class LastInput(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]
        info = LastInput(ctypes.sizeof(LastInput), 0)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000
        return None
    session = os.environ.get("XDG_SESSION_ID")
    out = _run("loginctl", "show-session", *([session] if session else []), "-p", "IdleHint", "-p", "IdleSinceHintMonotonic")
    values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if values.get("IdleHint") != "yes":
        return 0.0 if values else None
    since = int(values.get("IdleSinceHintMonotonic", "0") or 0)
    if not since:
        return None
    uptime = float(Path("/proc/uptime").read_text().split()[0])
    return max(0.0, uptime - since / 1e6)


def running(names):
    """The process names among names that are running now."""
    names = {n.lower() for n in names}
    if WINDOWS:
        out = _run("tasklist", "/fo", "csv", "/nh")
        return sorted({line.split(",")[0].strip('"').lower() for line in out.splitlines()} & names)
    found = set()
    for status in Path("/proc").glob("[0-9]*/comm"):
        try:
            found.add(status.read_text().strip().lower())
        except OSError:
            continue
    return sorted(found & names)


IDLE_SETTERS = ("swayidle", "hypridle", "gnome-session-b", "gnome-shell", "ksmserver", "plasmashell", "xfce4-power-man", "xss-lock")


def idle_detection():
    """(True, how) when this machine can tell that it is idle, else (False, why): the walkthrough's "When it may run"
    page. Linux: logind's IdleHint, which only a desktop or an idle daemon sets."""
    if WINDOWS:
        return True, "Windows reports the last keyboard or mouse input"
    out = _run("loginctl", "show-session", *([os.environ["XDG_SESSION_ID"]] if os.environ.get("XDG_SESSION_ID") else []),
               "-p", "IdleHint", "-p", "IdleSinceHint")
    values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if values.get("IdleHint") == "yes" or values.get("IdleSinceHint", "0") not in ("", "0"):
        return True, "logind reports idle time (IdleHint has been set on this session)"
    setters = running(IDLE_SETTERS)
    desktop = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "this desktop"
    if setters:
        return True, f"{', '.join(setters)} tells logind when the computer is idle"
    return False, (f"{desktop} does not tell logind when the computer is idle: no idle daemon runs and logind's IdleHint "
                   f"has never been set on this session")


def fullscreen():
    """True while a fullscreen program has the screen (Hyprland, X11, Windows); False when not, or when it cannot tell."""
    if WINDOWS:
        state = ctypes.c_int(0)
        try:
            if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
                return state.value in (2, 3, 4)  # busy, a Direct3D fullscreen program, presentation mode
        except (AttributeError, OSError):
            return False
        return False
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        try:
            window = json.loads(_run("hyprctl", "activewindow", "-j") or "{}")
        except json.JSONDecodeError:
            return False
        return bool(window.get("fullscreen"))
    if os.environ.get("DISPLAY") and shutil.which("xprop"):
        active = re.search(r"0x[0-9a-f]+", _run("xprop", "-root", "_NET_ACTIVE_WINDOW"))
        return bool(active) and "_NET_WM_STATE_FULLSCREEN" in _run("xprop", "-id", active.group(0), "_NET_WM_STATE")
    return False


def fullscreen_detection():
    if WINDOWS:
        return True, "Windows reports fullscreen programs"
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        return True, "Hyprland reports whether the active window is fullscreen"
    if os.environ.get("DISPLAY") and shutil.which("xprop"):
        return True, "the X11 window manager reports fullscreen windows"
    return False, "this desktop does not report fullscreen windows to other programs"


def stop_children(grace=3.0):
    """End every process this one started, and theirs (a build, a game in its sandbox): SIGTERM, then SIGKILL after
    grace seconds. Returns how many there were. Linux reads the process tree from /proc; on Windows, taskkill /T."""
    import signal
    import time
    me = os.getpid()
    if WINDOWS:
        out = _run("wmic", "process", "where", f"ParentProcessId={me}", "get", "ProcessId")
        pids = [int(x) for x in out.split() if x.isdigit()]
        for pid in pids:
            _run("taskkill", "/T", "/F", "/PID", str(pid))
        return len(pids)
    children = {}
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = stat.read_text().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        children.setdefault(int(fields[1]), []).append(int(stat.parent.name))
    pids, todo = [], [me]
    while todo:
        for child in children.get(todo.pop(), []):
            pids.append(child)
            todo.append(child)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(Path(f"/proc/{pid}").exists() for pid in pids):
        time.sleep(0.1)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return len(pids)
