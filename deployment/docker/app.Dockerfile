FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends iperf3 iproute2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/testbed
COPY pyproject.toml README.md ./
COPY testbed ./testbed
RUN pip install --no-cache-dir .
CMD ["python", "-m", "testbed.traffic.app_server"]

