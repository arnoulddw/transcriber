# Development

- [Local development](#local-development)
- [CLI commands](#cli-commands)
- [Running tests](#running-tests)

## Local development

Python 3.11, Node.js 18, MySQL 8, and FFmpeg match the container and CI environments.

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
npm ci
export FLASK_APP=app
flask bootstrap
npm run build:css:prod
flask run --host=0.0.0.0 --port=5004
```

Outside Docker Compose, set the MySQL variables in `.env` for your local database (`MYSQL_HOST=localhost`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`). The MySQL started by Compose is reachable at `127.0.0.1:3307` with the [default credentials](configuration.md#database).

For CSS development, run `npm run build:css:dev` in a second terminal.

## CLI commands

On start, the bootstrap step creates the schema, runs migrations, seeds default roles and languages, repairs the model catalog, creates the owner account, and recovers interrupted work. You can also run each step by hand:

```bash
export FLASK_APP=app
flask init-db
flask create-roles
flask create-admin
flask db-migrate
flask cleanup-once
flask bootstrap
```

`flask cleanup-loop` is the long-running command used by the Compose cleanup service. `flask worker` runs the background job worker. `flask reset-owner-password` sets a new owner password.

## Running tests

JavaScript tests:

```bash
npm ci
npm run test:js
```

Python tests run against a dedicated MySQL test container. Start the main stack first (the test container joins its network):

```bash
docker compose -f tests/docker-compose.test.yml up -d
```

```bash
env MYSQL_HOST=127.0.0.1 MYSQL_PORT=3308 MYSQL_USER=test MYSQL_PASSWORD=test MYSQL_DB=test_db \
    MYSQL_TEST_HOST=127.0.0.1 MYSQL_TEST_PORT=3308 MYSQL_TEST_USER=test MYSQL_TEST_PASSWORD=test MYSQL_TEST_DB=test_db \
    venv/bin/pytest -q
```

```bash
docker compose -f tests/docker-compose.test.yml down
```

See [`tests/README.md`](../tests/README.md) for the container-based test workflow and fixture conventions.
