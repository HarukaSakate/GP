#ifndef TCP_METRICS_H
#define TCP_METRICS_H

#include <linux/types.h>

struct tcp_metrics_key {
    __u64 socket_cookie;
    __u32 family;
    __u32 local_ip4;
    __u32 remote_ip4;
    __u32 local_ip6[4];
    __u32 remote_ip6[4];
    __u32 local_port;
    __u32 remote_port;
};

struct tcp_metrics_value {
    __u64 timestamp_ns;
    __u64 bytes_acked;
    __u64 bytes_received;
    __u64 delivery_rate_bps;
    __u64 pacing_rate_bps;
    __u32 rtt_us;
    __u32 rtt_min_us;
    __u32 cwnd_packets;
    __u32 packets_out;
    __u32 total_retrans;
    __u32 segs_out;
    __u32 app_limited;
    __u32 state;
};

#endif
