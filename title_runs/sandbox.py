"""Run a title, or a build, in a bubblewrap sandbox.

Inside, for both: the system directories read-only (/usr, /etc, /sys and the /lib, /bin symlinks), a fresh /proc and
/dev, an empty /tmp, /home and /run, no network (its own network namespace), its own PID namespace, and nothing else of
the user's session.

- command(): a title. Also the GPU's device nodes (/dev/dri, /dev/nvidia*) and the display sockets (Wayland and X11).
  The dump and the layout of the title (app0, libs, the relinked executable) are read-only; only the run's private
  directories are writable: the game directory's own files, the shader caches and the run directory.
- build_command(): a build. No GPU and no display. The source tree, its git directory and prebuilt dependencies are
  read-only, the build directory writable. Everything the build needs from the network (the PR's commit, main,
  submodule pins) is fetched before it starts, outside the sandbox; a build step that tries the network fails.

mode "none" runs the same command without the sandbox; it is only used when the tester sets it explicitly, and every
report then says so.
"""

import glob
import os
import shutil
from pathlib import Path

SYSTEM_RO = ("/usr", "/etc", "/sys", "/opt")
SYMLINKS = {"/lib": "usr/lib", "/lib64": "usr/lib", "/bin": "usr/bin", "/sbin": "usr/bin"}
DEVICES = ("/dev/dri", "/dev/nvidiactl", "/dev/nvidia-modeset", "/dev/nvidia-uvm", "/dev/nvidia-uvm-tools", "/dev/nvidia-caps")


class SandboxError(RuntimeError):
    pass


def game_display():
    """"x11" when the app shows the game inside its own window (ui/gameview.py needs an X11 window: the app sets
    TITLE_RUNS_GAME_DISPLAY), else "native" (Wayland where there is one)."""
    return "x11" if os.environ.get("TITLE_RUNS_GAME_DISPLAY") == "x11" else "native"


def display_binds():
    binds = []
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    wayland = os.environ.get("WAYLAND_DISPLAY")
    if runtime and wayland and os.path.exists(os.path.join(runtime, wayland)) and game_display() != "x11":
        binds.append(os.path.join(runtime, wayland))
    display = os.environ.get("DISPLAY", "")
    if display.startswith(":"):
        socket = f"/tmp/.X11-unix/X{display[1:].split('.')[0]}"
        if os.path.exists(socket):
            binds.append(socket)
    authority = os.environ.get("XAUTHORITY")
    if authority and os.path.exists(authority):
        binds.append(authority)
    return binds


def command(mode, argv, cwd, read_only=(), writable=(), env=None):
    """The command line that runs a title (argv) in cwd: bwrap ... -- argv, or argv itself for mode none."""
    return _command(mode, argv, cwd, read_only, writable, env, gpu=True)


def build_command(mode, argv, cwd, read_only=(), writable=(), env=None):
    """The command line that runs a build step (argv) in cwd, without network, GPU or display."""
    return _command(mode, argv, cwd, read_only, writable, env, gpu=False)


def _command(mode, argv, cwd, read_only, writable, env, gpu):
    if mode == "none":
        return list(argv)
    if mode != "bwrap":
        raise SandboxError(f"unknown sandbox mode {mode}")
    if not shutil.which("bwrap"):
        raise SandboxError("bwrap is not installed (bubblewrap); install it or set sandbox.mode = \"none\" explicitly")
    args = ["bwrap", "--die-with-parent", "--new-session", "--unshare-net", "--unshare-pid", "--unshare-uts", "--unshare-cgroup-try"]
    for path in SYSTEM_RO:
        if os.path.exists(path):
            args += ["--ro-bind", path, path]
    for link, target in SYMLINKS.items():
        if os.path.islink(link):
            args += ["--symlink", os.readlink(link), link]
        elif os.path.isdir(link):
            args += ["--ro-bind", link, link]
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/home", "--tmpfs", "/run", "--dir", "/tmp/home"]
    if gpu:
        for device in DEVICES:
            if os.path.exists(device):
                args += ["--dev-bind", device, device]
        for device in sorted(glob.glob("/dev/nvidia[0-9]*")):
            args += ["--dev-bind", device, device]
        for path in display_binds():
            args += ["--ro-bind", path, path]
    for path in writable:
        args += ["--bind", str(path), str(path)]
    for path in read_only:
        args += ["--ro-bind", str(path), str(path)]
    args += ["--setenv", "HOME", "/tmp/home", "--chdir", str(cwd)]
    for key, value in (env or {}).items():
        args += ["--setenv", key, str(value)]
    return args + ["--", *argv]
