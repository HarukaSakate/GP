#!/bin/bash
IFACE=enp2s0
echo ¨Start bandwith oscillation: 1Mbps <-> 3Mbps¨

while true
do 
    echo ¨1Mbps¨
    sudo tc qdisc replace dev $IFACE root netem rate 1mbit

    sleep 1

    echo ¨3Mbps¨
    sudo tc qdisc replace dev $IFACE root netem rate 3mbit 

    sleep 1

done