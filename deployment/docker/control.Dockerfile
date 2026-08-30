FROM docker:28.5.2-cli AS docker-cli

FROM python:3.12-slim-bookworm
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
WORKDIR /opt/testbed
COPY pyproject.toml README.md ./
COPY testbed ./testbed
RUN pip install --no-cache-dir .
CMD ["python", "-m", "testbed.cli", "--help"]
