<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Overview

This library implements ZMQ-based radio driver

# Architecture

The radio simulates RX/TX pairs between different processes over network or on the same machine
as ZMQ REQ/REP socket pairs. All the antennas have to be configured and connected before the
simulation can start.

# Limitations

You cannot reconnect a device once the simulation has started. The simulation has to be restarted
from scratch in order to add devices or restart a process.

# Requirements

Depends on zmq library being installed in the system. On ubuntu: `libzmq3-dev`, on RHEL/Fedora: `zeromq-devel`

# Usage

## Simple 1-to-1 antenna mapping

Add `--device.name oai_zmqdevif` to load the library in UE / gNB process. Add `--zmq.[0].tx_channels <channels>` and
`--zmq.[0].rx_channels <channels>` to define ZMQ REQ/REP pairs.

On the opposite side, load the library like specified above but invert the `rx` and `tx` channels. This way all
antennas of UE will be directly mapped to all antennas of the gNB.

### Example:

```
sudo ./nr-uesoftmodem -r 106 --numerology 1 --band 78 -C 3619200000 --device.name oai_zmqdevif --zmq.[0].tx_channels tcp://127.0.0.1:4557 --zmq.[0].rx_channels tcp://127.0.0.1:4556 --ssb 516
```

```
sudo ./nr-softmodem -O ../targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.usrpb210.conf --gNBs.[0].min_rxtxtime 6 --device.name oai_zmqdevif --zmq.[0].tx_channels tcp://127.0.0.1:4556 --zmq.[0].rx_channels tcp://127.0.0.1:4557
```
