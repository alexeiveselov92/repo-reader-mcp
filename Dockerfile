# The server's image (docs/running-in-a-container.md): the package with its locked dependencies and git, run as a user
# without rights, on a root filesystem that may be read-only. The configuration is mounted at /config, the mirrors kept
# in /data, /tmp writable.
#
#   docker build -t repo-reader-mcp .
#   docker run --read-only --tmpfs /tmp -v "$PWD/config:/config:ro" -v mirrors:/data -e GITHUB_TOKEN \
#     -e REPO_READER_MCP_TOKEN -p 8000:8000 repo-reader-mcp

FROM python:3.12-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-trixie
# git reads and fetches; it must be 2.44 or later, where a missing object is never fetched behind the server's back
# (GIT_NO_LAZY_FETCH). ssh for ssh:// and git@host:path addresses — it needs the user named in /etc/passwd. None of
# git's Perl scripts is used: Perl's modules and git's manual pages are taken out again (perl-base, which Debian can't
# do without, stays). An image built on this one that installs packages runs `apt-get install -f` first.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git openssh-client \
    && dpkg --compare-versions "$(git --version | cut -d' ' -f3)" ge 2.44 \
    && dpkg --purge --force-depends $(dpkg-query -W -f '${Package}\n' perl 'perl-modules-*' 'libperl5*' liberror-perl git-man) \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 reader \
    && useradd --uid 10001 --gid 10001 --home-dir /home/reader --no-create-home --shell /usr/sbin/nologin reader \
    && mkdir -p /config /data /home/reader \
    && chown 10001:10001 /data
COPY --from=build /app/.venv /app/.venv
# The mirrors go where the default `mirrors.folder` points when XDG_CACHE_HOME is set: /data/repo-reader-mcp.
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/reader \
    XDG_CACHE_HOME=/data REPO_READER_MCP_CONFIG=/config/config.yaml
USER 10001:10001
VOLUME /data
EXPOSE 8000
ENTRYPOINT ["repo-reader-mcp"]
CMD ["--http", "0.0.0.0:8000"]
