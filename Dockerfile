ARG PYTHON_IMAGE=python:3.12-alpine@sha256:b64631e04e4920160c50fbe8d8df828f7f35f06f425cb44aa09bca53e708a35a
FROM ${PYTHON_IMAGE}
ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="netbird-notifier" \
      org.opencontainers.image.description="Pending-user email notifier for self-hosted NetBird" \
      org.opencontainers.image.source="https://github.com/andrewilliams876/netbird-notifier" \
      org.opencontainers.image.url="https://github.com/andrewilliams876/netbird-notifier" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apk add --no-cache --upgrade libuuid=2.42.3-r1 \
    && python -m pip uninstall --yes pip \
    && addgroup -g 10001 notifier \
    && adduser -D -H -u 10001 -G notifier -s /sbin/nologin notifier \
    && mkdir /data && chown 10001:10001 /data && chmod 700 /data
COPY notifier/ /app/notifier/
USER 10001:10001
ENTRYPOINT ["python", "-m", "notifier"]
