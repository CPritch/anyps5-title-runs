"""Run a title, or a build, in a bubblewrap sandbox.

Inside, for both: the system directories read-only (/usr, /etc, /sys and the /lib, /bin symlinks), a fresh /proc and
/dev, an empty /tmp, /home and /run, no network (its own network namespace), its own PID and IPC namespaces, a new
session (so it can't type into the terminal that started it), and nothing else of the user's session. A seccomp filter
(SECCOMP, x86_64) refuses the system calls a game or a build has no use for and that the kernel's escapes go through:
new namespaces, ptrace, bpf, io_uring, perf events, keyrings, mounts and kernel modules.

- command(): a title. Also the GPU, as little of it as Vulkan needs (render nodes, not the card nodes that set display
  modes; on NVIDIA nvidia0, nvidiactl and nvidia-modeset, not the CUDA and profiling ones), and one display socket:
  Wayland's where the game is shown on Wayland, else X11's. The dump and the layout of the title (app0, libs, the
  relinked executable) are read-only; only the run's private directories are writable: the game directory's own files,
  the shader caches and the run directory.
- build_command(): a build. No GPU and no display. The source tree, its git directory and prebuilt dependencies are
  read-only, the build directory writable. Everything the build needs from the network (the PR's commit, main,
  submodule pins) is fetched before it starts, outside the sandbox; a build step that tries the network fails.

mode "none" runs the same command without the sandbox; it is only used when the tester sets it explicitly, and every
report then says so.
"""

import atexit
import glob
import os
import platform
import shutil
import struct
import tempfile

SYSTEM_RO = ("/usr", "/etc", "/sys", "/opt")
SYMLINKS = {"/lib": "usr/lib", "/lib64": "usr/lib", "/bin": "usr/bin", "/sbin": "usr/bin"}
# The GPU as Vulkan needs it (vulkaninfo in the sandbox, 2026-10-23, NVIDIA 615 and RADV): the render nodes, and
# NVIDIA's device, control and modeset nodes. Not /dev/dri/card* (display modes), nvidia-uvm (CUDA), nvidia-uvm-tools
# (profiling) or nvidia-caps.
DEVICES = ("/dev/dri/renderD*", "/dev/nvidia[0-9]*", "/dev/nvidiactl", "/dev/nvidia-modeset")

# x86_64 system calls refused with EPERM (asm/unistd_64.h): kernel modules and kexec, reboot, swap, mounts and the new
# mount API, chroot, ptrace and other processes' memory and files (kcmp, pidfd_getfd), bpf, perf events, keyrings,
# new namespaces (unshare, setns; clone with a namespace flag, below), accounting and quotas, file handles (the classic
# container escape), I/O privilege, the kernel log, vhangup, io_uring, fanotify, uselib and nfsservctl. AnyPS5 calls
# none of them; it does use userfaultfd and process_vm_readv/writev on itself, which stay allowed.
REFUSED = {"kexec_load": 246, "kexec_file_load": 320, "init_module": 175, "finit_module": 313, "delete_module": 176,
           "reboot": 169, "swapon": 167, "swapoff": 168, "mount": 165, "umount2": 166, "pivot_root": 155, "chroot": 161,
           "fsopen": 430, "fsconfig": 431, "fsmount": 432, "fspick": 433, "move_mount": 429, "open_tree": 428,
           "mount_setattr": 442, "ptrace": 101, "kcmp": 312, "pidfd_getfd": 438, "bpf": 321, "perf_event_open": 298,
           "keyctl": 250, "add_key": 248, "request_key": 249, "unshare": 272, "setns": 308, "acct": 163, "quotactl": 179,
           "quotactl_fd": 443, "lookup_dcookie": 212, "open_by_handle_at": 304, "name_to_handle_at": 303, "iopl": 172,
           "ioperm": 173, "syslog": 103, "vhangup": 153, "io_uring_setup": 425, "io_uring_enter": 426,
           "io_uring_register": 427, "fanotify_init": 300, "uselib": 134, "nfsservctl": 180}
CLONE, CLONE3 = 56, 435
CLONE_NAMESPACES = 0x7E020000  # CLONE_NEWNS, NEWCGROUP, NEWUTS, NEWIPC, NEWUSER, NEWPID, NEWNET (linux/sched.h)
AUDIT_ARCH_X86_64 = 0xC000003E
EPERM, ENOSYS = 1, 38
SECCOMP_FD = 9  # the descriptor bwrap reads the filter from (--seccomp)


class SandboxError(RuntimeError):
    pass


def seccomp_program():
    """The filter as classic BPF over struct seccomp_data (nr at 0, arch at 4, args[0] at 16): another architecture's
    calls (32-bit ones, whose numbers differ) kill the process, x32's and REFUSED get EPERM, clone with a namespace flag
    gets EPERM, and clone3 gets ENOSYS (its flags are behind a pointer the filter can't read), so libc uses clone."""
    def op(code, k, jt=0, jf=0):
        return struct.pack("HBBI", code, jt, jf, k)
    load, jeq, jset, ret = 0x20, 0x15, 0x45, 0x06
    allow, kill, errno = 0x7FFF0000, 0x80000000, 0x00050000
    out = [op(load, 4), op(jeq, AUDIT_ARCH_X86_64, 1, 0), op(ret, kill), op(load, 0), op(jset, 0x40000000, 0, 1), op(ret, errno | EPERM)]
    for nr in sorted(set(REFUSED.values())):
        out += [op(jeq, nr, 0, 1), op(ret, errno | EPERM)]
    out += [op(jeq, CLONE3, 0, 1), op(ret, errno | ENOSYS), op(jeq, CLONE, 0, 3), op(load, 16), op(jset, CLONE_NAMESPACES, 0, 1),
            op(ret, errno | EPERM), op(ret, allow)]
    return b"".join(out)


_filter = []


def seccomp_file():
    """The filter in a file of this process's (removed when it ends), or None where there is none (not x86_64)."""
    if platform.machine() != "x86_64":
        return None
    if not _filter:
        handle, path = tempfile.mkstemp(prefix="title-runs-seccomp-", suffix=".bpf")
        with os.fdopen(handle, "wb") as out:
            out.write(seccomp_program())
        atexit.register(lambda: os.path.exists(path) and os.unlink(path))
        _filter.append(path)
    return _filter[0]


def show_game_in_window(on):
    """The window's setting: the game in it (an X11 window, game_display "x11") or in its own window ("native")."""
    os.environ["TITLE_RUNS_GAME_DISPLAY"] = "x11" if on else "native"


def game_display():
    """"x11" when the app shows the game inside its own window (ui/gameview.py needs an X11 window: the app sets
    TITLE_RUNS_GAME_DISPLAY), else "native" (Wayland where there is one)."""
    return "x11" if os.environ.get("TITLE_RUNS_GAME_DISPLAY") == "x11" else "native"


def wayland_socket():
    """The Wayland socket the game is shown through, or None: when the app shows it inside its window, or there is no
    Wayland, it is X11's."""
    runtime, wayland = os.environ.get("XDG_RUNTIME_DIR"), os.environ.get("WAYLAND_DISPLAY")
    if runtime and wayland and os.path.exists(os.path.join(runtime, wayland)) and game_display() != "x11":
        return os.path.join(runtime, wayland)
    return None


def display_binds():
    """One display's socket: Wayland's when there is one for the game (wayland_socket), else X11's and its authority.
    Without the X11 socket a game on Wayland can't read or type into the user's other X11 windows."""
    if wayland_socket():
        return [wayland_socket()]
    binds = []
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
    args = ["bwrap", "--die-with-parent", "--new-session", "--unshare-net", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
            "--unshare-cgroup-try"]
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
        for pattern in DEVICES:
            for device in sorted(glob.glob(pattern)):
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
    seccomp = seccomp_file()
    if seccomp:
        # A shell opens the filter on SECCOMP_FD for bwrap, so whoever runs the command needn't pass a descriptor.
        return ["sh", "-c", f'exec "$@" {SECCOMP_FD}<"$0"', seccomp, *args, "--seccomp", str(SECCOMP_FD), "--", *argv]
    return args + ["--", *argv]
