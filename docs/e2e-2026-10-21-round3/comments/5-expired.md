<!-- anyps5-title-runs pr=8104 -->
### Title runs

Not queued.

**Approval of `69ac2e155` expired**: `8118a04e4` was pushed after it by @Celegans12 (2026-10-21 15:47 UTC) and is not checked. The App removed `title-test`; add it again to queue `8118a04e4`.

- PPSA04263: No difference on 2 of 3 RTX 5060 Laptop GPU · NVIDIA 615 · Linux machines, median -0.34 ms (-0.4 %).

| machine | GPU, driver, OS | title | outcome main / PR | p50 main → PR | verdict |
|---|---|---|---|---|---|
| laptop | NVIDIA GeForce RTX 5060 Laptop GPU, driver NVIDIA 615.71.09, Linux 7.2.8-zen1-2-zen | Grand Theft Auto V (PPSA04263) | rendering / rendering | 77.8 → 77.9 ms | no difference |
| laptop-2 | NVIDIA GeForce RTX 5060 Laptop GPU, driver NVIDIA 615.71.09, Linux 7.2.8-zen1-2-zen | Grand Theft Auto V (PPSA04263) | rendering / rendering | 78.0 → 77.6 ms | no difference (borderline) |
| synthetic | ? | Grand Theft Auto V (PPSA04263) | rendering / rendering | 77.8 → 76.4 ms | **faster** |

<details><summary>Per machine: the timed runs and summary lines</summary>

**laptop, PPSA04263**: main `d97361bd0` (A) against `69ac2e155` merged onto it (B), Story Mode, Resume Story: the loaded scene (the bank); sandbox bubblewrap.

| | main | this PR |
|---|---|---|
| p50 frame | 77.7, 77.8 ms | 77.7, 78.0 ms |
| p90 | 86.2, 88.2 ms | 88.4, 88.7 ms |
| p99 | 99.1, 105.4 ms | 108.7, 112.3 ms |
| GPU per present | 62.3, 62.8 ms | 62.9, 62.6 ms |

p50 +0.13 ms (+0.2 %); spread 0.30 ms; 1 % of main 0.78 ms, GPU +0.15 ms per present. A difference counts when it is larger than both.

```
{"commit":"d97361bd0df0","dirty":false,"env":{"APS5_DUMP_FRAMES":"93","APS5_DUMP_FRAMES_EVERY":"30","APS5_NO_PAD_INPUT":"1","APS5_PAD_INPUT_FILE":"<path>","APS5_TRACE_EVENTS":"4194304","APS5_TRACE_FRAMES":"3000:700"},"gpu":"NVIDIA GeForce RTX 5060 Laptop GPU","driver":"NVIDIA 615.71.09","os":"Linux 7.2.8-zen1-2-zen","cpu":"AMD Ryzen AI 9 465 w/ Radeon 880M","cpu_threads":20,"memory_mib":31391,"title_id":"PPSA04263","title":"Grand Theft Auto V","content_version":"01.010.002","resolution":"3840x2160","window":{"spec":"frames 3000:700","first_present":3000,"ms":54959.994},"presents":700,"frame_ms":{"p50":77.749,"p90":86.153,"p99":99.105,"max":110.927},"gpu_busy_ms_per_present":62.318,"worker_busy_pct":{"queue worker 0x0":3697.81},"top_phases_ms_per_frame":{"Driver.EndSubmission":2827.83,"Driver.Packet":73.288,"Graphics.Draw":56.874,"Graphics.Draw.draw_and_resource_release":53.675,"Driver.Packet.draw":46.877,"Driver.Draw":46.676,"VideoOut.Flip":25.199,"Driver.Present":25.174},"trace_dropped":false,"trace":"aps5-trace-d97361bd0df0-3.json.gz"}
{"commit":"d97361bd0df0","dirty":false,"env":{"APS5_DUMP_FRAMES":"93","APS5_DUMP_FRAMES_EVERY":"30","APS5_NO_PAD_INPUT":"1","APS5_PAD_INPUT_FILE":"<path>","APS5_TRACE_EVENTS":"4194304","APS5_TRACE_FRAMES":"3000:700"},"gpu":"NVIDIA GeForce RTX 5060 Laptop GPU","driver":"NVIDIA 615.71.09","os":"Linux 7.2.8-zen1-2-zen","cpu":"AMD Ryzen AI 9 465 w/ Radeon 880M","cpu_threads":20,"memory_mib":31391,"title_id":"PPSA04263","title":"Grand Theft Auto V","content_version":"01.010.002","resolution":"3840x2160","window":{"spec":"frames 3000:700","first_present":3000,"ms":55397.4},"presents":700,"frame_ms":{"p50":77.762,"p90":88.196,"p99":105.418,"max":114.752},"gpu_busy_ms_per_present":62.827,"worker_busy_pct":{"queue worker 0x0":3691.229},"top_phases_ms_per_frame":{"Driver.EndSubmission":2844.949,"Driver.Packet":74.091,"Graphics.Draw":57.691,"Graphics.Draw.draw_and_resource_release":54.482,"Driver.Packet.draw":47.081,"Driver.Draw":46.88,"VideoOut.Flip":25.648,"Driver.Present":25.631},"trace_dropped":false,"trace":"aps5-trace-d97361bd0df0-3.json.gz"}
{"commit":"f0a2a25b459f","dirty":false,"env":{"APS5_DUMP_FRAMES":"93","APS5_DUMP_FRAMES_EVERY":"30","APS5_NO_PAD_INPUT":"1","APS5_PAD_INPUT_FILE":"<path>","APS5_TRACE_EVENTS":"4194304","APS5_TRACE_FRAMES":"3000:700"},"gpu":"NVIDIA GeForce RTX 5060 Laptop GPU","driver":"NVIDIA 615.71.09","os":"Linux 7.2.8-zen1-2-zen","cpu":"AMD Ryzen AI 9 465 w/ Radeon 880M","cpu_threads":20,"memory_mib":31391,"title_id":"PPSA04263","title":"Grand Theft Auto V","content_version":"01.010.002","resolution":"3840x2160","window":{"spec":"frames 3000:700","first_present":3000,"ms":55437.92},"presents":700,"frame_ms":{"p50":77.733,"p90":88.43,"p99":108.73,"max":123.092},"gpu_busy_ms_per_present":62.855,"worker_busy_pct":{"queue worker 0x0":3688.867},"top_phases_ms_per_frame":{"Driver.EndSubmission":2845.08,"Driver.Packet":74.243,"Graphics.Draw":57.748,"Graphics.Draw.draw_and_resource_release":54.536,"Driver.Packet.draw":46.918,"Driver.Draw":46.714,"VideoOut.Flip":25.845,"Driver.Present":25.829},"trace_dropped":false,"trace":"aps5-trace-f0a2a25b459f-3.json.gz"}
{"commit":"f0a2a25b459f","dirty":false,"env":{"APS5_DUMP_FRAMES":"93","APS5_DUMP_FRAMES_EVERY":"30","APS5_NO_PAD_INPUT":"1","APS5_PAD_INPUT_FILE":"<path>","APS5_TRACE_EVENTS":"4194304","APS5_TRACE_FRAMES":"3000:700"},"gpu":"NVIDIA GeForce RTX 5060 Laptop GPU","driver":"NVIDIA 615.71.09","os":"Linux 7.2.8-zen1-2-zen","cpu":"AMD Ryzen AI 9 465 w/ Radeon 880M","cpu_threads":20,"memory_mib":31391,"title_id":"PPSA04263","title":"Grand Theft Auto V","content_version":"01.010.002","resolution":"3840x2160","window":{"spec":"frames 3000:700","first_present":3000,"ms":55956.277},"presents":700,"frame_ms":{"p50":78.035,"p90":88.693,"p99":112.335,"max":128.801},"gpu_busy_ms_per_present":62.588,"worker_busy_pct":{"queue worker 0x0":3709.193},"top_phases_ms_per_frame":{"Driver.EndSubmission":2887.975,"Driver.Packet":74.83,"Graphics.Draw":57.987,"Graphics.Draw.draw_and_resource_release":54.725,"Driver.Packet.draw":48.395,"Driver.Draw":48.189,"VideoOut.Flip":25.173,"Driver.Present":25.159},"trace_dropped":false,"trace":"aps5-trace-f0a2a25b459f-3.json.gz"}
```

**laptop-2, PPSA04263**: main `d97361bd0` (A) against `69ac2e155` merged onto it (B), Story Mode, Resume Story: the loaded scene (the bank); sandbox bubblewrap.

| | main | this PR |
|---|---|---|
| p50 frame | 78.0, 78.0 ms | 77.6, 77.7 ms |
| p90 | 88.3, 88.2 ms | 85.3, 85.7 ms |
| p99 | 107.2, 110.2 ms | 98.8, 102.6 ms |
| GPU per present | 62.9, 62.7 ms | 62.4, 62.3 ms |

p50 -0.34 ms (-0.4 %); spread 0.13 ms; 1 % of main 0.78 ms, GPU -0.44 ms per present. A difference counts when it is larger than both.

```
{"commit":"d97361bd0df0","dirty":false,"env":{"APS5_DUMP_FRAMES":"93","APS5_DUMP_FRAMES_EVERY":"30","APS5_NO_PAD_INPUT":"1","APS5_PAD_INPUT_FILE":"<path>","APS5_TRACE_EVENTS":"4194304","APS5_TRACE_FRAMES":"3000:700"},"gpu":"NVIDIA GeForce RTX 5060 Laptop GPU","driver":"NVIDIA 615.71.09","os":"Linux 7.2.8-zen1-2-zen","cpu":"AMD Ryzen AI 9 465 w/ Radeon 880M","cpu_threads":20,"memory_mib":31391,"title_id":"PPSA04263","title":"Grand Theft Auto V","content_version":"01.010.002","resolution":"3840x2160","window":{"spec":"frames 3000:700","first_present":3000,"ms":55542.261},"presents":700,"frame_ms":{"p50":77.979,"p90":88.26,"p99":107.223,"max":119.241},"gpu_busy_ms_per_present":62.895,"worker_busy_pct":{"queue worker 0x0":3717.786},"top_phases_ms_per_frame":{"Driver.EndSubmission":2873.21,"Driver.Packet":74.477,"Graphics.Draw":57.437,"Graphics.Draw.draw_and_resource_release":54.166,"Driver.Packet.draw":47.883,"Driver.Draw":47.684,"VideoOut.Flip":25.296,"Driver.Present":25.285},"trace_dropped":false,"trace":"aps5-trace-d97361bd0df0-3.json.gz"}
{"commit":"d97361bd0df0","dirty":false,"env":{"APS5_DUMP_FRAMES":"93","APS5_DUMP_FRAMES_EVERY":"30","APS5_NO_PAD_INPUT":"1","APS5_PAD_INPUT_FILE":"<path>","APS5_TRACE_EVENTS":"4194304","APS5_TRACE_FRAMES":"3000:700"},"gpu":"NVIDIA GeForce RTX 5060 Laptop GPU","driver":"NVIDIA 615.71.09","os":"Linux 7.2.8-zen1-2-zen","cpu":"AMD Ryzen AI 9 465 w/ Radeon 880M","cpu_threads":20,"memory_mib":31391,"title_id":"PPSA04263","title":"Grand Theft Auto V","content_version":"01.010.002","resolution":"3840x2160","window":{"spec":"frames 3000:700","first_present":3000,"ms":55693.86},"presents":700,"frame_ms":{"p50":77.997,"p90":88.186,"p99":110.193,"max":126.197},"gpu_busy_ms_per_present":62.679,"worker_busy_pct":{"queue worker 0x0":3722.5},"top_phases_ms_per_frame":{"Driver.EndSubmission":2884.947,"Driver.Packet":74.533,"Graphics.Draw":57.595,"Graphics.Draw.draw_and_resource_release":54.323,"Driver.Packet.draw":48.247,"Driver.Draw":48.045,"VideoOut.Flip":25.063,"Driver.Present":25.032},"trace_dropped":false,"trace":"aps5-trace-d97361bd0df0-3.json.gz"}
{"commit":"f0a2a25b459f","dirty":false,"env":{"APS5_DUMP_FRAMES":"93","APS5_DUMP_FRAMES_EVERY":"30","APS5_NO_PAD_INPUT":"1","APS5_PAD_INPUT_FILE":"<path>","APS5_TRACE_EVENTS":"4194304","APS5_TRACE_FRAMES":"3000:700"},"gpu":"NVIDIA GeForce RTX 5060 Laptop GPU","driver":"NVIDIA 615.71.09","os":"Linux 7.2.8-zen1-2-zen","cpu":"AMD Ryzen AI 9 465 w/ Radeon 880M","cpu_threads":20,"memory_mib":31391,"title_id":"PPSA04263","title":"Grand Theft Auto V","content_version":"01.010.002","resolution":"3840x2160","window":{"spec":"frames 3000:700","first_present":3000,"ms":54769.607},"presents":700,"frame_ms":{"p50":77.583,"p90":85.268,"p99":98.785,"max":111.766},"gpu_busy_ms_per_present":62.397,"worker_busy_pct":{"queue worker 0x0":3692.742},"top_phases_ms_per_frame":{"Driver.EndSubmission":2813.7,"Driver.Packet":73.419,"Graphics.Draw":56.803,"Graphics.Draw.draw_and_resource_release":53.649,"Driver.Packet.draw":46.919,"Driver.Draw":46.724,"VideoOut.Flip":25.402,"Driver.Present":25.382},"trace_dropped":false,"trace":"aps5-trace-f0a2a25b459f-3.json.gz"}
{"commit":"f0a2a25b459f","dirty":false,"env":{"APS5_DUMP_FRAMES":"93","APS5_DUMP_FRAMES_EVERY":"30","APS5_NO_PAD_INPUT":"1","APS5_PAD_INPUT_FILE":"<path>","APS5_TRACE_EVENTS":"4194304","APS5_TRACE_FRAMES":"3000:700"},"gpu":"NVIDIA GeForce RTX 5060 Laptop GPU","driver":"NVIDIA 615.71.09","os":"Linux 7.2.8-zen1-2-zen","cpu":"AMD Ryzen AI 9 465 w/ Radeon 880M","cpu_threads":20,"memory_mib":31391,"title_id":"PPSA04263","title":"Grand Theft Auto V","content_version":"01.010.002","resolution":"3840x2160","window":{"spec":"frames 3000:700","first_present":3000,"ms":55113.074},"presents":700,"frame_ms":{"p50":77.714,"p90":85.653,"p99":102.564,"max":133.117},"gpu_busy_ms_per_present":62.307,"worker_busy_pct":{"queue worker 0x0":3693.094},"top_phases_ms_per_frame":{"Driver.EndSubmission":2831.999,"Driver.Packet":73.481,"Graphics.Draw":57.146,"Graphics.Draw.draw_and_resource_release":53.886,"Driver.Packet.draw":47.499,"Driver.Draw":47.296,"VideoOut.Flip":25.194,"Driver.Present":25.178},"trace_dropped":false,"trace":"aps5-trace-f0a2a25b459f-3.json.gz"}
```

**synthetic, PPSA04263**: main `d97361bd0` (A) against `69ac2e155` merged onto it (B), SYNTHETIC: the laptop's run of 69ac2e155 today with the PR's p50 lowered by 1.5 ms; sandbox bubblewrap.

| | main | this PR |
|---|---|---|
| p50 frame | 77.7, 77.8 ms | 76.2, 76.5 ms |
| p90 | 86.2, 88.2 ms | 88.4, 88.7 ms |
| p99 | 99.1, 105.4 ms | 108.7, 112.3 ms |
| GPU per present | 62.3, 62.8 ms | 62.9, 62.6 ms |

p50 -1.37 ms (-1.8 %); spread 0.30 ms; 1 % of main 0.78 ms, GPU +0.15 ms per present. A difference counts when it is larger than both.

```
```

</details>

<sub>anyps5-title-runs: this comment is edited as machines report; a new comment is posted when an outcome or a verdict changes. What leaves a tester's machine: timings, summary lines and outcome classes; never game files.</sub>
