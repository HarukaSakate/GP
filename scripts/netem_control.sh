#!/bin/sh
set -eu

usage() {
    echo "usage: $0 apply IFACE RATE DELAY JITTER LOSS | clear IFACE" >&2
    exit 2
}

[ "$#" -ge 2 ] || usage
ACTION=$1
IFACE=$2

case "$IFACE" in
    ""|lo|*/*|*" "*) echo "unsafe interface: $IFACE" >&2; exit 2 ;;
esac

case "$ACTION" in
    apply)
        [ "$#" -eq 6 ] || usage
        RATE=$3
        DELAY=$4
        JITTER=$5
        LOSS=$6
        tc qdisc replace dev "$IFACE" root netem \
            rate "$RATE" delay "$DELAY" "$JITTER" loss "$LOSS"
        tc -s qdisc show dev "$IFACE"
        ;;
    clear)
        [ "$#" -eq 2 ] || usage
        tc qdisc del dev "$IFACE" root 2>/dev/null || true
        ;;
    *) usage ;;
esac
