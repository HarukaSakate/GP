# Implementation status

## Milestone 1: measurement-path hardening

Completed:

- Read the congestion-control algorithm from each observed socket with
  `TCP_CONGESTION`; `--cc` is now an explicit test override.
- Add `connection_id`, `pacing_rate_bps`, and `app_limited` to the collector-neutral
  WebSocket schema.
- Suppress historical retransmission and byte counters on the first sample.
- Use the actual interval between samples for the acknowledged-byte rate fallback.
- Reset browser-side TCP baselines when the observed connection changes.
- Require meaningful absolute RTT growth and three consecutive samples before a
  guardrail action.
- Prevent reuse of one TCP sample for multiple downshifts and extend the cooldown.
- Add unit tests and a standard-library integration probe.
- Add a Docker/Compose environment and health check.

## Verification performed

- Python unit tests: eight passed (collector normalization, eBPF decoding, and
  eBPF session/socket selection).
- Inline player JavaScript: syntax validation passed with Node.js.
- Docker image: built successfully.
- Compose service: healthy; HTTP player request returned 200.
- Integration probe: WebSocket handshake succeeded and a real Linux `TCP_INFO`
  sample was received with `cc=cubic`, a non-empty connection ID, RTT, CWND,
  delivery rate, pacing rate, and application-limited state.

## Milestone 3: browser integration and network automation

Completed:

- Added `--collector tcp_info|ebpf`; the pinned eBPF map now feeds the existing
  WebSocket session registry and selects the newest DASH socket by client IP and
  HTTP server port.
- Propagate kernel sample age to the browser and reject stale samples there.
- Replaced direct representation changes with a dash.js 5.1.1
  `qualitySwitchRules` custom rule while retaining Throughput or BOLA as baseline.
- Migrated the baseline selector to dash.js 5 rule activation settings.
- Added guarded `tc/netem` apply/clear tooling, JSON profiles, repetition runner,
  per-run logs/metadata, signal cleanup, and a `NET_ADMIN` Docker environment.

Verification performed:

- Eight Python unit tests passed.
- eBPF sockops map -> reader -> session selection -> WebSocket integration passed
  in the Docker Desktop Linux VM.
- `tc/netem` rate, delay, jitter, and loss were applied and removed successfully
  in a capability-limited Docker container.
- Player JavaScript syntax and experiment matrix dry-run passed.

## Remaining milestones

1. Run the CUBIC/BBR x Throughput/BOLA repeated experiment matrix.
2. Aggregate QoE and confidence intervals.
3. Measure collector CPU, memory, traffic, and observation-to-browser latency.

## Milestone 2: eBPF sockops collector

Completed:

- Added an architecture-aware eBPF build for arm64 and x86_64.
- Added a `BPF_PROG_TYPE_SOCK_OPS` program attached to a cgroup.
- Track IPv4/IPv6 endpoints and socket cookies as connection identity.
- Collect smoothed/minimum RTT, CWND, packets in flight, retransmissions,
  segment counts, acknowledged/received bytes, and a delivery-rate estimate.
- Remove map entries when TCP connections close.
- Added a pinned-map reader that converts bpftool output into the same
  `tcp_metrics` JSON schema used by the browser.
- Added decoder and retransmission-delta unit tests.

Verification performed in the Docker Desktop Linux VM:

- clang eBPF compilation passed on arm64 with warnings treated as errors.
- libbpf skeleton generation passed.
- kernel verifier accepted the program.
- cgroup sockops attach and detach passed.
- local TCP traffic generated two live map entries.
- pinned map entries were decoded into collector-neutral JSON successfully.
- decoded entries were delivered as `tcp_metrics` through the real WebSocket API.
