# Running it in a container

The server's image serves over [Streamable HTTP](serving-over-http.md), the way a team, a gateway or an orchestrator
uses it. Its mirrors are kept on a volume, and its secrets come from the environment.

```text
ghcr.io/alexeiveselov92/repo-reader-mcp:<version>
```

Every release from 0.2.0 on is published for `linux/amd64` and `linux/arm64`. Each is tagged twice, with its version
(`0.2.0`) and with its commit (`sha-1a2b3c4`); there is no `latest`, so an upgrade is always a choice you make. The
image holds the package with its locked dependencies, git 2.47 (it must be 2.44 or later; see
[Safety](reference/safety.md#reading-never-reaches-the-network)) and an ssh client. It runs as user `reader` (`10001`),
without rights, and works on a read-only root filesystem.

## Run it

```bash
docker run --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  -v "$PWD/config:/config:ro" -v repo-mirrors:/data \
  -e GITHUB_TOKEN -e REPO_READER_MCP_TOKEN \
  -p 8000:8000 ghcr.io/alexeiveselov92/repo-reader-mcp:0.2.0
```

```yaml
# config/config.yaml
repositories:
  - github: acme/shop-*
    token_env: GITHUB_TOKEN           # a read-only token for the code host

http:
  token_env: REPO_READER_MCP_TOKEN    # every request carries `Authorization: Bearer <its value>`
```

The server answers at `/mcp` on port 8000 (`http://<host>:8000/mcp`). At start it lists the groups and makes the
mirrors, then brings them up to date every `mirrors.every_minutes`, as it does outside a container.

| Where | What |
|---|---|
| `/config` | The configuration, as `/config/config.yaml` (`REPO_READER_MCP_CONFIG` names it), and every file it names: guidance files, a git configuration. Mount it read-only. |
| `/data` | The mirrors (`/data/repo-reader-mcp`): the default [`mirrors.folder`](reference/configuration.md#mirrors) points here in the image. Keep it on a volume. A restart over a kept folder serves at once, while a fresh one must make every mirror again. |
| `/tmp` | Writable: git's messages pass through temporary files. |
| `/home/reader` | The home folder, read-only. Mount `.ssh` here for `ssh://` addresses ([below](#ssh)). |

Each secret the configuration names, a code host's token or the bearer token, is passed to the container by the
variable it names, never written into a file. If one isn't set, the server refuses to start and names the variable.

Arguments after the image replace the default command (`--http 0.0.0.0:8000`):

```bash
docker run --rm -v "$PWD/config:/config:ro" -e GITHUB_TOKEN -e REPO_READER_MCP_TOKEN \
  ghcr.io/alexeiveselov92/repo-reader-mcp:0.2.0 --check
docker run --rm -v "$PWD/config:/config:ro" -v repo-mirrors:/data -e GITHUB_TOKEN -e REPO_READER_MCP_TOKEN \
  ghcr.io/alexeiveselov92/repo-reader-mcp:0.2.0 --sync
```

Every variable the configuration names must be set for these too, the bearer token's included: the configuration is
checked whole before anything else happens.

## `/health`

`GET /health` answers without the token:

- `200 {"status": "ready"}` once the repositories can be read;
- `503 {"status": "syncing"}` while the first sync since start is under way.

The answer names no repository and reads nothing. The first round ends the wait whether every host answered or not,
and the next round tries again. A repository whose sync failed says so when an agent reads it. A group whose host
couldn't list it is named in `list_repos` with the host's error, and so are its repositories, which can't be read yet.
A restart over a kept mirrors folder is ready at once. Once ready, the server never turns back to `503`: a host that
fails later, or a repository that joins a group and still has to be mirrored, takes nothing from what is served. Probes are left out of the server's log. Only exactly `/health` is answered without the token; every other
path, `/mcp` included, still needs it.

Use it as the **readiness** probe, which decides whether traffic is sent. Don't use it as the **liveness** probe,
which restarts the container: a first sync of a hundred repositories takes a couple of minutes, and a liveness probe on
`/health` would restart the server in the middle of it. For liveness, check that the port answers.

## Behind an MCP gateway

An organisation's MCP gateway signs people in, decides who sees which servers, and passes their calls on. To put this
server behind one:

- **Point the gateway at `/mcp`**, for example `http://repo-reader:8000/mcp` inside the cluster. Answers are plain
  JSON, request ids may be strings or numbers, and no session is kept, so whatever the gateway does with sessions
  works.
- **Give the server the gateway's own key** as its bearer token (`http.token_env`). Gateways usually drop the caller's
  `Authorization` and send a key of their own to each backend. With that key as the token, a request that reaches
  the server around the gateway is refused. If only the gateway can reach the server (a network policy),
  `http.behind_gateway: true` serves without a token.
- **Send traffic once ready.** Gate the backend on `/health`. While it syncs, the server still answers `initialize`
  and every tool. A mirror not made yet says so instead of reading.
- **No request waits for a sync.** Syncs run in the background. Each git command behind an answer is stopped after
  30 seconds, and each fetch of an older commit's contents after two minutes. A long history (blame across many
  renames) or a search over many repositories runs several of them in one call.

The server answers the gateway, not the person: it doesn't know who is asking. Everyone the gateway lets through reads
every repository the configuration serves. To give different people different repositories, run two servers with two
configurations and let the gateway decide who reaches which.

A gateway may rename the tools (`code__read_file`). The server's answers still name them by their own names
(`read_guidance(repo="…")`), and agents follow them either way.

## Docker Compose

```yaml
services:
  repo-reader:
    image: ghcr.io/alexeiveselov92/repo-reader-mcp:0.2.0
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    volumes:
      - ./config:/config:ro
      - mirrors:/data
    environment:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
      REPO_READER_MCP_TOKEN: ${REPO_READER_MCP_TOKEN}
    ports: ["127.0.0.1:8000:8000"]   # a reverse proxy with TLS in front
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request as u; u.build_opener(u.ProxyHandler({})).open('http://127.0.0.1:8000/health')"]
      interval: 30s
      start_period: 5m

volumes:
  mirrors:
```

## Kubernetes

What the pod needs, in pieces:

```yaml
securityContext: { runAsUser: 10001, runAsGroup: 10001, fsGroup: 10001, runAsNonRoot: true }
containers:
  - name: repo-reader
    image: ghcr.io/alexeiveselov92/repo-reader-mcp:0.2.0
    ports: [{ containerPort: 8000 }]
    securityContext: { readOnlyRootFilesystem: true, allowPrivilegeEscalation: false, capabilities: { drop: [ALL] } }
    env:
      - { name: GITHUB_TOKEN, valueFrom: { secretKeyRef: { name: repo-reader, key: github-token } } }
      - { name: REPO_READER_MCP_TOKEN, valueFrom: { secretKeyRef: { name: repo-reader, key: gateway-key } } }
    volumeMounts:
      - { name: config, mountPath: /config, readOnly: true }   # a ConfigMap with config.yaml
      - { name: mirrors, mountPath: /data }                    # a volume claim, or emptyDir: a restart syncs again
      - { name: tmp, mountPath: /tmp }                         # emptyDir
    readinessProbe: { httpGet: { path: /health, port: 8000 }, periodSeconds: 10 }
    livenessProbe: { tcpSocket: { port: 8000 }, periodSeconds: 30 }
```

You can run several copies: any of them answers any request. Give each copy a `/data` of its own rather than a shared
one.

## Repositories on the server's disk

A repository given by `path` is mounted into the container, read-only, at a path the configuration names
(`path: /repos/shop`). git won't read a repository another user owns. A mount from the host belongs to the host's
user, not to `10001`, so the server refuses to start and says so. Either run the container as the owner (`--user`,
with `/data` writable by that user; ssh addresses then fail, since that user has no name in the image), or name the
folders in `safe.directory` of a git configuration the server reads:

```bash
printf '[safe]\n\tdirectory = /repos/*\n' > config/gitconfig
docker run … -v "$PWD/repos:/repos:ro" -e GIT_CONFIG_GLOBAL=/config/gitconfig ghcr.io/alexeiveselov92/repo-reader-mcp:0.2.0
```

Name only the folders you mount: `safe.directory` stands guard against a repository someone else set up.

## ssh

For `ssh://` and `git@host:path` addresses, ssh looks in `/home/reader/.ssh`. Mount a folder there holding the key
and `known_hosts` (with no `known_hosts`, the host can't be checked and the sync fails). The server's user must be able
to read the key. A key the server's user owns must be readable by it alone (mode `600` or `400`). A Kubernetes Secret
mounted with `defaultMode: 0440` and the pod's `fsGroup` works. A token over https needs none of this, and is the
simpler way in a container.
