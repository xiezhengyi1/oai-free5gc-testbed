ARG TRAFFIC_BASE=mergedsystem/testbed-traffic:recovery-20261028
FROM ${TRAFFIC_BASE}
CMD ["python", "-m", "testbed.traffic.app_server"]
