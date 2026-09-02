from __future__ import annotations

from testbed.traffic.profiles import TrafficProfile


def traffic_command(profile: TrafficProfile) -> list[str]:
    destination = profile.five_tuple.destination_ip
    port = str(profile.five_tuple.destination_port)
    common = [
        "iperf3",
        "-c",
        destination,
        "-p",
        port,
        "--bind-dev",
        profile.interface,
        "--cport",
        str(profile.five_tuple.source_port),
        "-t",
        "86400",
        "-i",
        "1",
        "--format",
        "m",
        "--forceflush",
    ]
    if profile.five_tuple.protocol == "tcp":
        common.extend(["-b", f"{profile.rate_mbps}M"])
    else:
        raise ValueError(f"iperf traffic does not support {profile.five_tuple.protocol}")
    return common


def ping_command(profile: TrafficProfile) -> list[str]:
    return [
        "ping",
        "-D",
        "-I",
        profile.interface,
        "-i",
        "0.2",
        profile.five_tuple.destination_ip,
    ]
