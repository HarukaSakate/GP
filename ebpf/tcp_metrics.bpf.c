// SPDX-License-Identifier: GPL-2.0
#include <linux/bpf.h>
#include <linux/in.h>
#include <linux/in6.h>
#include <bpf/bpf_endian.h>
#include <bpf/bpf_helpers.h>

#include "tcp_metrics.h"

#define TCP_METRICS_AF_INET 2
#define TCP_METRICS_AF_INET6 10

struct {
    __uint(type, BPF_MAP_TYPE_LRU_HASH);
    __uint(max_entries, 4096);
    __type(key, struct tcp_metrics_key);
    __type(value, struct tcp_metrics_value);
} tcp_metrics SEC(".maps");

static __always_inline void fill_key(struct bpf_sock_ops *ctx, struct tcp_metrics_key *key)
{
    key->socket_cookie = bpf_get_socket_cookie(ctx);
    key->family = ctx->family;
    key->local_port = ctx->local_port;
    key->remote_port = bpf_ntohl(ctx->remote_port);

    if (ctx->family == TCP_METRICS_AF_INET) {
        key->local_ip4 = ctx->local_ip4;
        key->remote_ip4 = ctx->remote_ip4;
    } else if (ctx->family == TCP_METRICS_AF_INET6) {
        __builtin_memcpy(key->local_ip6, ctx->local_ip6, sizeof(key->local_ip6));
        __builtin_memcpy(key->remote_ip6, ctx->remote_ip6, sizeof(key->remote_ip6));
    }
}

static __always_inline void update_metrics(struct bpf_sock_ops *ctx)
{
    struct tcp_metrics_key key = {};
    struct tcp_metrics_value value = {};
    __u64 delivered_bytes;

    fill_key(ctx, &key);
    value.timestamp_ns = bpf_ktime_get_ns();
    value.bytes_acked = ctx->bytes_acked;
    value.bytes_received = ctx->bytes_received;
    value.rtt_us = ctx->srtt_us >> 3;
    value.rtt_min_us = ctx->rtt_min;
    value.cwnd_packets = ctx->snd_cwnd;
    value.packets_out = ctx->packets_out;
    value.total_retrans = ctx->total_retrans;
    value.segs_out = ctx->segs_out;
    value.app_limited = ctx->rate_delivered == 0;
    value.state = ctx->state;

    if (ctx->rate_interval_us > 0 && ctx->mss_cache > 0) {
        delivered_bytes = (__u64)ctx->rate_delivered * ctx->mss_cache;
        value.delivery_rate_bps = delivered_bytes * 8000000ULL / ctx->rate_interval_us;
    }

    bpf_map_update_elem(&tcp_metrics, &key, &value, BPF_ANY);
}

SEC("sockops")
int tcp_metrics_sockops(struct bpf_sock_ops *ctx)
{
    struct tcp_metrics_key key = {};
    int flags;

    if (ctx->family != TCP_METRICS_AF_INET && ctx->family != TCP_METRICS_AF_INET6)
        return 1;

    switch (ctx->op) {
    case BPF_SOCK_OPS_ACTIVE_ESTABLISHED_CB:
    case BPF_SOCK_OPS_PASSIVE_ESTABLISHED_CB:
        flags = BPF_SOCK_OPS_RTT_CB_FLAG |
                BPF_SOCK_OPS_RETRANS_CB_FLAG |
                BPF_SOCK_OPS_STATE_CB_FLAG;
        bpf_sock_ops_cb_flags_set(ctx, flags);
        update_metrics(ctx);
        break;
    case BPF_SOCK_OPS_RTT_CB:
    case BPF_SOCK_OPS_RETRANS_CB:
        update_metrics(ctx);
        break;
    case BPF_SOCK_OPS_STATE_CB:
        if (ctx->args[1] == BPF_TCP_CLOSE) {
            fill_key(ctx, &key);
            bpf_map_delete_elem(&tcp_metrics, &key);
        } else {
            update_metrics(ctx);
        }
        break;
    default:
        break;
    }

    return 1;
}

char LICENSE[] SEC("license") = "GPL";
