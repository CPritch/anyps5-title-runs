"""Build a worktree: configure once, then build incrementally in the same build directory, and the prx libraries.

Each step runs in the build sandbox (sandbox.build_command): no network, the source tree, its git directory and any
existing path named in the CMake arguments (a prebuilt ffmpeg, say) read-only, only the build directory writable.
Everything from the network is fetched before (sources.py)."""

import os
import re
import subprocess
import time
from pathlib import Path

from . import sandbox


class BuildError(RuntimeError):
    pass


def argument_paths(cmake_args):
    """Existing absolute paths in -DNAME=PATH arguments, which the build reads."""
    paths = []
    for arg in cmake_args:
        if arg.startswith("-D") and "=" in arg:
            value = arg.split("=", 1)[1]
            if os.path.isabs(value) and os.path.exists(value):
                paths.append(value)
    return paths


def git_dir(source):
    """The git directory a worktree's .git file points to, and the repository's common directory: read-only in the
    sandbox, for the configure step's git calls."""
    dot_git = Path(source) / ".git"
    if dot_git.is_file():
        worktree_dir = Path(dot_git.read_text().split("gitdir:", 1)[1].strip())
        return [str(worktree_dir.parent.parent)]
    return [str(dot_git)] if dot_git.is_dir() else []


def steps(source, build_dir, cmake_args):
    out = []
    if not (Path(build_dir) / "CMakeCache.txt").exists():
        out.append(["cmake", "-S", str(source), "-B", str(build_dir), *cmake_args])
    else:
        out.append(["cmake", "-S", str(source), "-B", str(build_dir)])
    return out + [["cmake", "--build", str(build_dir), "--parallel"], ["cmake", "--build", str(build_dir), "--target", "libs", "--parallel"]]


def build(source, build_dir, cmake_args, log_path, commit, sandbox_mode="bwrap", plan=None):
    """plan: the steps to run (default: configure, build, libs)."""
    source, build_dir = Path(source), Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    read_only = [str(source), *git_dir(source), *argument_paths(cmake_args)]
    with open(log_path, "w") as log:
        log.write(f"sandbox: {sandbox_mode}; read-only: {', '.join(read_only)}; writable: {build_dir}\n")
        for step in plan or steps(source, build_dir, cmake_args):
            log.write("$ " + " ".join(step) + "\n")
            log.flush()
            argv = sandbox.build_command(sandbox_mode, step, build_dir, read_only=read_only, writable=[build_dir])
            if subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT).returncode != 0:
                tail = Path(log_path).read_text(errors="replace").splitlines()[-15:]
                raise BuildError(f"{' '.join(step[:3])} failed:\n" + "\n".join(tail))
    (build_dir / "BUILT_FROM").write_text(f"{commit} title-runs\n")
    return {"seconds": round(time.monotonic() - started), "prx": len(list((build_dir / "core/libs/libs").glob("*.prx"))),
            "shader_cache_version": shader_cache_version(build_dir), "sandbox": sandbox_mode}


def shader_cache_version(build_dir):
    generated = Path(build_dir) / "core/libs/prx/libSceAgcDriver/shader_recompiler_agc_driver_generated/ShaderCacheVersion.cpp"
    if not generated.exists():
        return ""
    found = re.search(r"SourceVersion = 0x([0-9a-f]+)", generated.read_text())
    return found.group(1) if found else ""
