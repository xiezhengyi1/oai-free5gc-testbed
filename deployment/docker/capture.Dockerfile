FROM scratch
COPY rootfs/ /
ENTRYPOINT ["/usr/bin/tcpdump"]
