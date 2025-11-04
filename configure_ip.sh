#!/bin/bash

ip addr
ip addr flush dev enp0s5
ip addr add 192.168.33.31/24 dev enp0s5
ip link set enp0s5 up
