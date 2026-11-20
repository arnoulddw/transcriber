# Troubleshooting

## No transcription models appear

Save a provider key together with an exact model name and the `transcription` purpose in **Manage API Keys**, or set a provider key in `.env` (personal mode). Check that the user's role allows that provider. If personal key management is disabled, configure an administrator or global provider key and a role default.

## Live transcription will not start

- Allow microphone access in the browser.
- Check that the model was saved with the `live` purpose and that the role permits its provider.
- Check that the user has daily, weekly, and monthly live minutes left.
- For a new OpenRouter speech-to-text slug, add it to `OPENROUTER_LIVE_TRANSCRIPTION_MODELS`.
- Look at `docker compose logs -f transcriber` for upstream or transport errors.

## MySQL connection fails

With Docker Compose the app connects to the `mysql` service automatically. For a database installed on the host, set `MYSQL_HOST=localhost` and check the port, database, user, and password. Check service health with `docker compose ps` and database logs with `docker compose logs mysql`.

If you changed `MYSQL_USER` or `MYSQL_PASSWORD` after the first start, MySQL still has the old values in its data volume. Change them back, or update the user inside MySQL with `ALTER USER`.

## Saved API keys stopped working after a rebuild

Saved provider keys are encrypted with `SECRET_KEY`. If it was generated automatically, it lives in `runtime/secret_key`; deleting that folder or recreating a container without it creates a new key. Restore the old file (or set the old value as `SECRET_KEY`), or re-enter the API keys in **Manage API Keys**.

## I forgot the owner password

```bash
docker compose exec transcriber flask reset-owner-password
```

## Google Sign-In or password reset fails

Both only exist in team mode. Set `GOOGLE_CLIENT_ID` and configure the matching authorised origin for Google Sign-In. Password reset needs valid `MAIL_*` SMTP settings. If reCAPTCHA is on, check the site/secret key pair and the allowed domain.

## The app port is already in use

Set `APP_PORT` in `.env` (for example `APP_PORT=5005`), then run `docker compose up -d`. If port `3307` is taken, set `MYSQL_HOST_PORT` the same way.
