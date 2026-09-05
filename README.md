# ASFBot

ASFBot is a small Telegram frontend for controlling
[ArchiSteamFarm](https://github.com/JustArchiNET/ArchiSteamFarm) over its IPC
API. It is intended for a private, explicitly allowed set of Telegram accounts.

## Commands

- `/help` — show the command summary.
- `/ping` — report whether the Telegram process is alive and ASF IPC responds.
- `/status [bot]` — show ASF or one bot's status.
- `/pause <bot>` and `/resume <bot>` — pause or resume farming.
- `/start <bot>` and `/stop <bot>` — start or stop a bot.
- `/redeem <bot> <key> [key...]` — redeem up to 20 Steam keys.

An allowed user may also send a normal ASF command with `/` or `!`, or send a
message containing complete Steam keys for automatic redemption on `ASF`.

## Configuration

Environment variables override matching command-line arguments.

| Variable | Required | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | yes | Token issued by BotFather. |
| `TELEGRAM_ALLOWED_USER_ID` | yes | One positive numeric Telegram user ID, or a comma-separated allowlist. |
| `TELEGRAM_PROXY` | no | Telegram proxy URL such as `http://host:7890`. |
| `ASF_IPC_HOST` | no | ASF hostname; default `127.0.0.1`. Use `asf` in Compose. |
| `ASF_IPC_PORT` | no | ASF IPC port; default `1242`. |
| `ASF_IPC_PASSWORD` | no | Password matching ASF's `IPCPassword`. |
| `ASF_IPC_CONNECT_TIMEOUT` | no | Connection timeout in seconds; default `3.05`. |
| `ASF_IPC_READ_TIMEOUT` | no | Response timeout in seconds; default `15`. |

IPC calls use a 3.05-second connection timeout and a 15-second read timeout,
so a stopped or unresponsive ASF does not block Telegram polling indefinitely.
Do not commit `.env`, bot tokens, IPC passwords, or Steam keys.

### Migrating from username authorization

`TELEGRAM_USER_ALIAS=@name` and `--alias` are no longer accepted. Replace them
with the immutable numeric ID:

```dotenv
TELEGRAM_ALLOWED_USER_ID=123456789
```

For more than one administrator, use comma-separated IDs. Obtain your numeric
ID from Telegram's API or a reputable user-info bot and verify it before access.

## Run locally

Python 3.12 is the supported runtime:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=... TELEGRAM_ALLOWED_USER_ID=... python bot.py \
  --host 127.0.0.1 --port 1242 --password ...
```

Prebuilt images are published for `linux/amd64` and `linux/arm64` to both
registries:

```sh
docker pull ghcr.io/zieglar/asfbot:latest
docker pull zieglar/asfbot:latest
```

The default branch publishes `latest`. A tag such as `v1.2.3` publishes
`1.2.3` and `1.2`; pull requests only build and never receive registry
credentials. To build the production runtime locally instead:

```sh
docker build -t asfbot:local .
```

The image installs only the fully resolved, hashed packages in
`requirements.lock`, contains no development dependencies, runs as an unprivileged user, and has an offline
health check for the polling process. The check intentionally does not contact
Telegram or expose credentials; ASF reachability is available through `/ping`.

`requirements.txt` is the short list of direct runtime requirements. After an
intentional dependency update, regenerate and review the Python 3.12 ARM64
Alpine lock with the same resolver command recorded at the top of the file:

```sh
uv pip compile requirements.txt --python-version 3.12 \
  --python-platform aarch64-unknown-linux-musl --generate-hashes \
  --only-binary :all: --output-file requirements.lock
```

Commit `requirements.txt` and `requirements.lock` together, then run the full
test suite and `scripts/verify-container.sh`. Docker installs the lock with
`--require-hashes`, so an unreviewed version or artifact cannot be substituted.

## Docker Compose with ASF

Save the following as `compose.yml` in your ASF deployment directory:

```yaml
services:
  asf:
    image: justarchi/archisteamfarm:6.3.9.6
    restart: unless-stopped
    environment:
      ASF_ARGS: --server
    volumes:
      - ./config:/app/config
    networks:
      - asf-private

  asfbot:
    image: ghcr.io/zieglar/asfbot:latest
    restart: unless-stopped
    depends_on:
      asf:
        condition: service_started
    environment:
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:?set TELEGRAM_BOT_TOKEN in .env}
      TELEGRAM_ALLOWED_USER_ID: ${TELEGRAM_ALLOWED_USER_ID:?set TELEGRAM_ALLOWED_USER_ID in .env}
      TELEGRAM_PROXY: ${TELEGRAM_PROXY:-}
      ASF_IPC_HOST: asf
      ASF_IPC_PORT: "1242"
      ASF_IPC_PASSWORD: ${ASF_IPC_PASSWORD:-}
      ASF_IPC_CONNECT_TIMEOUT: ${ASF_IPC_CONNECT_TIMEOUT:-3.05}
      ASF_IPC_READ_TIMEOUT: ${ASF_IPC_READ_TIMEOUT:-15}
    networks:
      - asf-private

networks:
  asf-private:
    driver: bridge
```

Create an untracked `.env` file beside `compose.yml`:

```dotenv
TELEGRAM_BOT_TOKEN=replace-me
TELEGRAM_ALLOWED_USER_ID=123456789
ASF_IPC_PASSWORD=replace-me
ASF_IPC_CONNECT_TIMEOUT=3.05
ASF_IPC_READ_TIMEOUT=15
# TELEGRAM_PROXY=http://host:7890
```

Pull and start the service from the same directory:

```sh
docker compose pull asfbot
docker compose up -d asfbot
docker compose ps
docker compose logs --tail=100 asfbot
```

Both services join the `asf-private` bridge. ASF listens on `1242` inside that
network, but the configuration has no `ports` mapping, so IPC is not published
on the host. The bridge still permits ASFBot's outbound Telegram connection.

The example deliberately pins ASF to `justarchi/archisteamfarm:6.3.9.6` rather
than a moving `latest` tag. To upgrade ASF, review its official release notes,
change this version explicitly, back up `config`, pull/build, and verify `/ping`
and `/status` before removing the previous local image.

ASF must enable IPC and listen on the container network. In `config/ASF.json`:

```json
{
  "IPC": true,
  "IPCPassword": "the-same-value-as-ASF_IPC_PASSWORD"
}
```

In `config/IPC.config` (or the corresponding current ASF IPC configuration),
bind Kestrel inside the container:

```json
{
  "Kestrel": {
    "Endpoints": {
      "HTTP": { "Url": "http://0.0.0.0:1242" }
    }
  }
}
```

Binding `0.0.0.0` makes IPC reachable by ASFBot on the Docker bridge; omitting
a host port mapping keeps it private from the LAN and internet.

## Supported architectures

The published ASFBot image, official Python image, and ASF image support ARM64.
This Dockerfile uses Python 3.12 Alpine. Docker automatically selects the
`linux/arm64` image on ARM64 hosts and `linux/amd64` on Intel/AMD hosts, so no
`platform` override is normally required.
