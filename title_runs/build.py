"""Build a worktree: configure once, then build incrementally in the same build directory, and the prx libraries."""

import re
import subprocess
import time
from pathlib import Path


class BuildError(RuntimeError):
    pass


def build(source, build_dir, cmake_args, log_path, commit):
    source, build_dir = Path(source), Path(build_dir)
    started = time.monotonic()
    steps = []
    if not (build_dir / "CMakeCache.txt").exists():
        steps.append(["cmake", "-S", str(source), "-B", str(build_dir), *cmake_args])
    else:
        steps.append(["cmake", "-S", str(source), "-B", str(build_dir)])
    steps += [["cmake", "--build", str(build_dir), "--parallel"], ["cmake", "--build", str(build_dir), "--target", "libs", "--parallel"]]
    with open(log_path, "w") as log:
        for step in steps:
            log.write("$ " + " ".join(step) + "\n")
            log.flush()
            if subprocess.run(step, stdout=log, stderr=subprocess.STDOUT).returncode != 0:
                tail = Path(log_path).read_text(errors="replace").splitlines()[-15:]
                raise BuildError(f"{' '.join(step[:3])} failed:\n" + "\n".join(tail))
    (build_dir / "BUILT_FROM").write_text(f"{commit} title-runs\n")
    return {"seconds": round(time.monotonic() - started), "prx": len(list((build_dir / "core/libs/libs").glob("*.prx"))),
            "shader_cache_version": shader_cache_version(build_dir)}


def shader_cache_version(build_dir):
    generated = Path(build_dir) / "core/libs/prx/libSceAgcDriver/shader_recompiler_agc_driver_generated/ShaderCacheVersion.cpp"
    if not generated.exists():
        return ""
    found = re.search(r"SourceVersion = 0x([0-9a-f]+)", generated.read_text())
    return found.group(1) if found else ""
