ARG BASE=oai-free5gc-testbed/control:lifecycle-macstats-20261017
FROM ${BASE}
WORKDIR /opt/testbed
COPY testbed ./testbed
