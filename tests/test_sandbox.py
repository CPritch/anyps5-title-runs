"""The sandbox's command line and its seccomp filter: the filter run on made-up system calls by a small classic-BPF
interpreter, and run for real in bwrap; the GPU's device nodes; one display socket; IPC and a new session."""

import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401

from title_runs import sandbox

X86_64, I386 = 0xC000003E, 0x40000003
ALLOW, KILL, EPERM, ENOSYS = 0x7FFF0000, 0x80000000, 0x00050001, 0x00050026


def decide(nr, arch=X86_64, arg0=0):
    """Run the filter (classic BPF: ld abs, jeq, jset, ret) on struct seccomp_data {nr, arch, ip, args[6]}."""
    data = struct.pack("<iIQ6Q", nr, arch, 0, arg0, 0, 0, 0, 0, 0)
    program = [struct.unpack("HBBI", sandbox.seccomp_program()[i:i + 8]) for i in range(0, len(sandbox.seccomp_program()), 8)]
    pc, accumulator = 0, 0
    while True:
        code, jt, jf, k = program[pc]
        if code == 0x20:
            accumulator = struct.unpack_from("<I", data, k)[0]
        elif code == 0x15:
            pc += jt if accumulator == k else jf
        elif code == 0x45:
            pc += jt if accumulator & k else jf
        elif code == 0x06:
            return k
        else:
            raise AssertionError(f"unknown opcode {code:#x}")
        pc += 1


class Filter(unittest.TestCase):
    def test_what_it_refuses_and_lets_through(self):
        for name, nr in sandbox.REFUSED.items():
            self.assertEqual(decide(nr), EPERM, name)
        for name, nr in (("read", 0), ("mmap", 9), ("ioctl", 16), ("userfaultfd", 323), ("process_vm_readv", 310),
                         ("process_vm_writev", 311), ("memfd_create", 319), ("futex", 202), ("execve", 59)):
            self.assertEqual(decide(nr), ALLOW, name)

    def test_clone_and_other_architectures(self):
        self.assertEqual(decide(56, arg0=0x003D0F00), ALLOW)  # a thread: CLONE_VM|FS|FILES|SIGHAND|THREAD|SYSVSEM|SETTLS|...
        self.assertEqual(decide(56, arg0=0x01200011), ALLOW)  # fork, as glibc makes it
        for flag in (0x10000000, 0x20000000, 0x40000000, 0x00020000, 0x08000000):  # NEWUSER, NEWPID, NEWNET, NEWNS, NEWIPC
            self.assertEqual(decide(56, arg0=flag | 0x11), EPERM, hex(flag))
        self.assertEqual(decide(435), ENOSYS)  # clone3: libc falls back to clone
        self.assertEqual(decide(101 | 0x40000000), EPERM)  # x32
        self.assertEqual(decide(26, arch=I386), KILL)  # i386's 26 is ptrace

    @unittest.skipUnless(shutil.which("bwrap") and sandbox.seccomp_file(), "needs bwrap on x86_64")
    def test_in_bwrap(self):
        probe = ("import os, threading, subprocess\n"
                 "try:\n    os.unshare(os.CLONE_NEWUSER)\n    print('unshare: allowed')\n"
                 "except PermissionError:\n    print('unshare: refused')\n"
                 "t = threading.Thread(target=print, args=('thread: ok',)); t.start(); t.join()\n"
                 "print('child:', subprocess.run(['true']).returncode)\n")
        out = subprocess.run(sandbox.build_command("bwrap", ["python3", "-I", "-c", probe], "/tmp"), capture_output=True, text=True)
        self.assertEqual(out.stdout.split("\n")[:3], ["unshare: refused", "thread: ok", "child: 0"], out.stderr)


class CommandLine(unittest.TestCase):
    def test_namespaces_session_and_the_filter(self):
        argv = sandbox.command("bwrap", ["game"], "/work")
        if sandbox.seccomp_file():
            self.assertEqual(argv[:4], ["sh", "-c", 'exec "$@" 9<"$0"', sandbox.seccomp_file()])
            self.assertEqual(argv[-4:], ["--seccomp", "9", "--", "game"])
            self.assertEqual(Path(sandbox.seccomp_file()).read_bytes(), sandbox.seccomp_program())
        for flag in ("--die-with-parent", "--new-session", "--unshare-net", "--unshare-pid", "--unshare-ipc"):
            self.assertIn(flag, argv)

    def test_the_gpu_as_vulkan_needs_it(self):
        nodes = {"/dev/dri/renderD*": ["/dev/dri/renderD128"], "/dev/nvidia[0-9]*": ["/dev/nvidia0"], "/dev/nvidiactl": ["/dev/nvidiactl"],
                 "/dev/nvidia-modeset": ["/dev/nvidia-modeset"]}
        with mock.patch("glob.glob", side_effect=lambda pattern: nodes.get(pattern, [])), mock.patch("shutil.which", return_value="/usr/bin/bwrap"):
            argv = sandbox.command("bwrap", ["game"], "/work")
            build = sandbox.build_command("bwrap", ["cmake"], "/work")
        bound = [argv[i + 1] for i, a in enumerate(argv) if a == "--dev-bind"]
        self.assertEqual(bound, ["/dev/dri/renderD128", "/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-modeset"])
        self.assertNotIn("--dev-bind", build)

    def test_one_display_socket(self):
        runtime = Path(tempfile.mkdtemp())
        (runtime / "wayland-1").touch()
        x11 = "/tmp/.X11-unix/X0"
        env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":0"}
        exists = lambda path: path == x11 or os.path.lexists(path)
        with mock.patch.dict(os.environ, env, clear=False), mock.patch("os.path.exists", side_effect=exists):
            os.environ.pop("TITLE_RUNS_GAME_DISPLAY", None)
            self.assertEqual(sandbox.display_binds(), [str(runtime / "wayland-1")])  # Wayland: no X11 socket
            os.environ["TITLE_RUNS_GAME_DISPLAY"] = "x11"  # shown inside the app's window
            self.assertEqual(sandbox.display_binds()[:1], [x11])
            os.environ.pop("TITLE_RUNS_GAME_DISPLAY")


if __name__ == "__main__":
    unittest.main()
