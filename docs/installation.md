# Installation

The fastest way to run Transcriber is the [quick start in the README](../README.md#quick-start). This page covers what happens under the hood, how to customise the install, and how to prepare it for a server.

- [Docker Compose (recommended)](#docker-compose-recommended)
- [Running on a server](#running-on-a-server)
- [Published Docker image](#published-docker-image)
- [Local development without Docker](#local-development-without-docker)
- [Updating](#updating)

## Docker Compose (recommended)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with [Docker Compose](https://docs.docker.com/compose/install/) v2.24 or newer
- An API key for at least one provider (OpenAI, AssemblyAI, Google Gemini, or OpenRouter). You add it in the app after it starts.

### Start it

```bash
git clone https://github.com/arnoulddw/transcriber.git
cd transcriber
docker compose up -d --build
```

Open [http://localhost:5004](http://localhost:5004), then go to **Manage API Keys** to add a provider key and model (see [Configuration › Providers and models](configuration.md#providers-and-models)).

No `.env` file is needed. Without one, Transcriber uses these defaults:

| Setting | Default without `.env` |
|---|---|
| Mode | Personal mode, sign-in off. You can add a password in **User Settings > Access** |
| `SECRET_KEY` | Generated on first start and saved to `runtime/secret_key` |
| MySQL user / password / database | `transcriber` / `transcriber` / `transcriber` |
| MySQL access from the host | `127.0.0.1:3307` only |
| App port | `5004` |

To change anything, copy the example file and uncomment what you need:

```bash
cp .env.example .env
```

Then recreate the containers with `docker compose up -d`. See the [configuration reference](configuration.md) for every option.

### What Compose runs

| Service | Purpose |
|---|---|
| `mysql` | MySQL 8 database. Data lives in the `mysql_data` Docker volume |
| `transcriber` | The web app (Gunicorn). On first start it creates the schema, runs migrations, and seeds roles, languages, and the owner account |
| `transcriber-worker` | Durable background worker for transcription, workflow, and title jobs |
| `transcriber-cleanup` | Runs retention cleanup every six hours |

Uploaded temporary files, logs, and runtime state (including the generated `secret_key`) are mounted from the `uploads/`, `logs/`, and `runtime/` folders in the repository.

### Everyday commands

```bash
docker compose ps
docker compose logs -f transcriber
docker compose down
```

Run retention cleanup once, for example when diagnosing retention behaviour:

```bash
docker compose run --rm transcriber-cleanup flask cleanup-once
```

## Running on a server

The defaults are meant for a single machine. Before you make Transcriber reachable from the internet:

1. **Set a sign-in password.** Anyone who can reach an instance in personal mode without a password can use it. Set one in **User Settings > Access**, or set `ADMIN_PASSWORD` before the first start.
2. **Use your own database passwords.** Set `MYSQL_PASSWORD` and `MYSQL_ROOT_PASSWORD` in `.env` *before the first start*. MySQL stores them in its data volume when it initialises; changing them later requires an `ALTER USER` in MySQL as well.
3. **Keep the secret key.** Either back up `runtime/secret_key` or set `SECRET_KEY` explicitly (`openssl rand -hex 32`). It encrypts saved provider API keys; if it changes, those keys must be re-entered.
4. **Terminate TLS** in a reverse proxy in front of the app. Cookies are marked `Secure` automatically on HTTPS requests.
5. **Keep `.env` out of version control.**

If you already have a running install that relies on `runtime/secret_key`, moving to an explicit `SECRET_KEY` means copying the contents of that file into `.env`.

## Published Docker image

The image is published as [`arnoulddw/transcriber`](https://hub.docker.com/r/arnoulddw/transcriber). It needs a MySQL 8 database you provide. Its default command starts both Gunicorn and a background worker in one container.

```bash
docker run -d \
  --name transcriber \
  -e MYSQL_HOST=your-mysql-host \
  -e MYSQL_USER=transcriber \
  -e MYSQL_PASSWORD=change-me \
  -e MYSQL_DB=transcriber \
  -v transcriber-runtime:/app/runtime \
  -p 5004:5004 \
  arnoulddw/transcriber:latest
```

You can also pass `--env-file .env` instead of individual `-e` flags. Mount `/app/runtime` (as above) or set `SECRET_KEY`; otherwise a new key is generated each time the container is recreated.

Notes for running outside Compose:

- The worker must share the application's database and uploads directory. Set `START_EMBEDDED_WORKER=0` only if a separately supervised worker runs `flask worker` against those same resources.
- Retention cleanup is not started inside the web app. Run `flask cleanup-loop` as a separate supervised process, or schedule `flask cleanup-once`.

## Local development without Docker

See [Development](development.md#local-development).

## Updating

```bash
git pull
docker compose up -d --build
```

On start, the app applies any pending database migrations automatically.
