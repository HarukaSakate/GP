# TCP Metrics WebSocket Protocol

`web/player.html` が受け取る TCP 補助信号の最小仕様をここで固定する。

## 目的

- モックサーバと実サーバで同じ JSON 形式を使う
- プレイヤ側の入力境界を明確にする
- `TCP_INFO` 版と eBPF 版で同じメッセージ形式に正規化する

## 接続

- Transport: WebSocket
- Default URL: `ws://<server>:8765`
- Client first message:

```json
{
  "type": "hello",
  "session_id": "exp-001",
  "client_ip": "203.178.128.214"
}
```

- Server may reply:

```json
{
  "type": "hello_ack",
  "session_id": "exp-001",
  "scenario": "oscillate",
  "cc": "cubic"
}
```

プレイヤは `hello_ack` を必須とはしない。ABR 判定に使うのは `type == "tcp_metrics"` のみ。

## `tcp_metrics` schema

```json
{
  "type": "tcp_metrics",
  "version": 1,
  "session_id": "exp-001",
  "timestamp_ms": 1784356800123,
  "freshness_ms": 84,
  "transport": "tcp",
  "cc": "cubic",
  "rtt_us": 38200,
  "rtt_min_us": 24100,
  "cwnd_packets": 28,
  "cwnd_bytes": 40544,
  "packets_out": 20,
  "retransmissions_delta": 1,
  "retransmission_rate": 0.018,
  "rto_events_delta": 0,
  "delivery_rate_bps": 1450000
}
```

## Required fields

| field | type | note |
| --- | --- | --- |
| `type` | string | must be `tcp_metrics` |
| `version` | integer | protocol version |
| `session_id` | string | playback session identifier |
| `timestamp_ms` | integer | producer-side unix epoch milliseconds |
| `cc` | string | `cubic` or `bbr` |
| `rtt_us` | integer | smoothed RTT in microseconds |
| `rtt_min_us` | integer | minimum RTT in microseconds |
| `retransmissions_delta` | integer | retransmissions since previous sample |
| `retransmission_rate` | number | optional normalized loss signal |
| `delivery_rate_bps` | integer | delivery rate in bits per second |

## Optional fields

| field | type | note |
| --- | --- | --- |
| `freshness_ms` | integer | producer-side sample age |
| `transport` | string | default `tcp` |
| `cwnd_packets` | integer | informational |
| `cwnd_bytes` | integer | informational |
| `packets_out` | integer | informational |
| `rto_events_delta` | integer | informational |

## Normalization rules

- `rtt_us` and `rtt_min_us` must be positive integers
- `retransmissions_delta` must be reset to `0` on counter wrap or socket change
- `delivery_rate_bps` should be `0` if unavailable, not omitted
- `cc` must be lower-case
- `session_id` must be the identifier received in `hello`, if known

## Player-side interpretation

- stale if local receive age exceeds `tcpMaxAgeMs`
- congested for `cubic` if `rtt_us / rtt_min_us > 1.5` or `retransmissions_delta > 0`
- congested for `bbr` if RTT inflation persists and delivery rate falls near current bitrate
- missing or stale signal must fall back to baseline ABR without forcing a quality change

## Mapping from collectors

### `TCP_INFO` collector

- `tcpi_rtt` -> `rtt_us`
- running minimum of `tcpi_rtt` -> `rtt_min_us`
- delta of `tcpi_total_retrans` -> `retransmissions_delta`
- delta/rate derived from retrans count -> `retransmission_rate`
- derived send rate or app estimate -> `delivery_rate_bps`

### eBPF collector

- `srtt_us >> 3` -> `rtt_us`
- `rtt_min_us` -> `rtt_min_us`
- delta of `total_retrans` -> `retransmissions_delta`
- controller-derived ratio -> `retransmission_rate`
- controller-derived delivery estimate -> `delivery_rate_bps`

## Mock server

Local mock server:

```bash
python3 scripts/mock_tcp_signal_server.py --host 0.0.0.0 --port 8765 --scenario oscillate --cc cubic
```

Available scenarios:

- `steady`
- `congested`
- `oscillate`
- `bbr_probe`

## TCP_INFO scaffold server

Local scaffold server:

```bash
python3 scripts/tcp_info_signal_server.py \
  --host 0.0.0.0 \
  --http-port 8000 \
  --ws-port 8765 \
  --serve-dir /home/l0gic/abr-pretest \
  --poll-ms 500 \
  --cc cubic
```

This scaffold is intended for:

- local `dash.js` player integration
- JSON schema validation against the real collector path
- single-client experiments where session mapping by client IP is acceptable

Current limitations:

- session mapping is `client_ip` based only
- `delivery_rate_bps` falls back to an acked-bytes delta estimate when kernel delivery rate is unavailable
- this is a Python scaffold, not a production collector
