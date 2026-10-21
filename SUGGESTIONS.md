# What this repository adds to #7264's title_run.py, and what could go back

`vendor/title_run/` is #7264 (LeandroLP23) at c2dce8dd3, unchanged. Where it lacked something for this service, the
addition is in our layer. These are the additions, each with where it lives here and whether it fits #7264. None
has been offered upstream; Charlie decides.

## Could go back to #7264

1. **Caches that outlive `prepare()`.** `prepare()` removes the work directory, and `run_title()` drops
   `ANYPS5_SHADER_CACHE_DIR` and `ANYPS5_NO_SHADER_CACHE` from the environment, so AnyPS5's cache is always
   `work/<ID>/shader_cache` (beside the executable) and the driver's is `work/<ID>/driver-cache`. Every invocation
   therefore starts cold, and run 2 is the only warm run. A `--cache-dir` option (both caches kept outside the work
   directory) would allow warm runs across invocations, for example before and after a change.
   Here: `protocol.py` sets `ANYPS5_SHADER_CACHE_DIR` and the driver cache paths to `state/caches/<ID>/<side>`.
2. **Per-title `app0` exclusions and seed files in titles.json.** GTA V's harness leaves the package's `fakelib`
   out of `app0`, and a title that needs entitlements, save data or settings (GTA V: `anyps5-entitlements.ini`,
   `_sd`, `_sd_mem`, which also select the Graphics Mode) needs them in the game directory before the first run.
   Two optional keys, `app0_skip` and `seed`, would cover both.
   Here: `game.prepare()`, after `title_run.prepare()`; the keys are in our config's `[titles.<ID>]`.
3. **A command prefix for `Session`.** `Session` starts `[executable]`. A `wrap` list (a titles.json key or a
   `--wrap` argument) would let a caller run the title under bubblewrap, a debugger or `script(1)` without a
   wrapper script.
   Here: `job.boot_and_classify()` writes `work/<ID>/sandboxed`, a shell script that runs bwrap, and passes it to
   `run_title()` as the executable.
4. **The environment the title gets.** `run_title()` passes the whole `os.environ` on, minus the two cache
   switches, so everything in the caller's environment reaches the title, tokens included. An allowlist (`PATH`,
   `LANG`, the display variables, then the title's `env`) would keep them out.
   Here: `job.title_environment()` narrows `os.environ` for the call.
5. **`app0` and the dump.** #7264 lists the hard links as a known limit. They share inodes with the dump, so a
   write through `app0` changes the dump. A copy with `copy_file_range` or a reflink where the file system has one
   would keep the speed without the link.
   Here: the sandbox binds `app0` and the dump read-only, so the title cannot write either.
6. **Real titles on Linux, and GTA V's run length.** #7264 says it was not tested with real titles on Linux, or
   on NVIDIA. On 2026-10-21, on Linux 7.2.8 (Arch, gcc 16.2.1) with an RTX 5060 Laptop GPU on NVIDIA 615.71.09,
   `discover()` and `prepare()` (unwrap, relink, layout) worked for GTA V (PPSA04263 01.010.002) on both sides of
   the #8104 job. `run_title()`, unchanged, then ran GTA V in our sandbox on that job's main build (d97361bd0),
   twice (cold, then warm):
   - at the default 60 s both runs were `stalled`: there was no 10 s summary after 20 s, so the last one was
     older than `STALL_SECONDS` (20). GTA V is still loading towards its title screen at 60 s;
   - at 240 s both were `rendering` (3,096 presents cold, 6,796 warm), and the last frame is the title screen.

   titles.json has no GTA V entry. One with `"seconds": 240` would give it a run that reaches the title screen.
   Here: the config's `boot_seconds` for a title, which falls back to titles.json's `seconds`.

## Ours only (outside #7264's scope)

- The poller, the follow and trust rules, the debounce, the jobs (`refs/pull/N/merge` against its base), the
  report and the poster.
- Routes as data, driven by frame states and pad input, and the harness's timed protocol (warm caches, one
  window, A B A B, counts or not counted).
- The sandbox itself.
