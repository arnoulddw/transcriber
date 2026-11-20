# Configuration

Most things are configured inside the app: provider keys and models in **Manage API Keys**, mode and sign-in in **User Settings > Access**, and roles, quotas and pricing in the **Admin** panel (team mode).

Environment variables are for deployment-level settings. Put them in a `.env` file next to `docker-compose.yml` (start from [`.env.example`](../.env.example)) and run `docker compose up -d` to apply them. Every variable is optional.

- [Providers and models](#providers-and-models)
- [Live transcription](#live-transcription)
- [Personal and team mode](#personal-and-team-mode)
- [Environment variable reference](#environment-variable-reference)

## Providers and models

Transcriber has four built-in provider integrations. It does not hard-code a list of model names, so new provider models work without waiting for a release.

| Provider | File transcription | Live transcription | LLM workflows/titles | Notes |
|---|:---:|:---:|:---:|---|
| OpenAI | Yes | WebRTC | Yes | Examples include `whisper-1`, `gpt-4o-transcribe`, and `gpt-transcribe` |
| AssemblyAI | Yes | — | — | Supports optional speaker diarization |
| Google Gemini | Yes | WebSocket | Yes | Save the exact Gemini model name, such as `gemini-3.5-transcribe` |
| OpenRouter | Yes | Chunked streaming | Yes | Save the full vendor/model slug, such as `openai/gpt-transcribe` |

To add a model:

1. Open **Manage API Keys**.
2. Choose a provider and enter its API key.
3. Enter the exact provider model name.
4. Select one or more purposes: file transcription, live transcription, or LLM use.
5. Save. The model is available immediately in the relevant selectors.

**Which key is used?** In personal mode, the owner's saved key is used first, then the matching provider key from `.env` (`OPENAI_API_KEY`, `ASSEMBLYAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`). In team mode, if a role allows personal API key management, the user's own model-specific key is used. Otherwise it falls back to an administrator or environment-level provider key. Roles still decide which providers and features a user may access.

## Live transcription

The default live model is `gpt-live-transcribe`. Configure additional live models with a comma-separated list:

```dotenv
LIVE_TRANSCRIPTION_MODEL=gpt-live-transcribe
LIVE_TRANSCRIPTION_MODELS=gpt-live-transcribe,openai/gpt-transcribe
LIVE_TRANSCRIPTION_PROVIDER_OPENAI_GPT_TRANSCRIBE=openrouter
```

Model names without a slash default to OpenAI; `vendor/model` slugs default to OpenRouter. A Gemini model saved with the `live` purpose is routed to Gemini automatically. Use `OPENROUTER_LIVE_TRANSCRIPTION_MODELS` to allow a newly released OpenRouter speech-to-text model that is not yet in the built-in compatibility list.

## Personal and team mode

Transcriber starts in personal mode. Switch modes in **User Settings > Access** with no restart. To lock the mode so it can't be switched in the app, set `DEPLOYMENT_MODE=single` (personal) or `DEPLOYMENT_MODE=multi` (team). A fresh install locked to team mode needs `ADMIN_PASSWORD`.

## Environment variable reference

These are the settings most deployments care about. [`.env.example`](../.env.example) lists every option with comments, including MySQL tuning, title/workflow defaults, OpenRouter, rate limiting, upload cleanup, logging, and queue behaviour.

### Core

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Signs sessions and encrypts saved API keys | Generated on first start and saved to `runtime/secret_key` |
| `DEPLOYMENT_MODE` | Leave unset to switch modes in the app. `single` (personal) or `multi` (team) locks the mode | unset (personal mode on a fresh install) |
| `ALLOW_REGISTRATION` | Leave unset to control team-mode sign-ups in the app. `true` or `false` locks it | unset |
| `ADMIN_USERNAME` / `ADMIN_EMAIL` | Owner account created on first start | `admin` / unset |
| `ADMIN_PASSWORD` | Turns sign-in on and stops it being turned off in the app. Required for team mode on a fresh install | unset |
| `SESSION_COOKIE_SECURE` | Always mark cookies `Secure`. They are already marked on HTTPS requests | `false` |
| `APP_SETTINGS_CACHE_SECONDS` | How quickly other processes see a mode or sign-up change | `5` |
| `APP_PORT` | Host port exposed by Docker Compose | `5004` |
| `TZ` | Time zone used for quota periods and display | `UTC` |

### Database

| Variable | Purpose | Default (Compose) |
|---|---|---|
| `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DB` | Application database credentials | `transcriber` / `transcriber` / `transcriber` |
| `MYSQL_ROOT_PASSWORD` | MySQL root password | `transcriber-root` |
| `MYSQL_HOST_BIND` / `MYSQL_HOST_PORT` | Where MySQL is published on the host | `127.0.0.1` / `3307` |
| `MYSQL_HOST` / `MYSQL_PORT` | Database address. Set automatically by Compose; needed when running without it | `mysql` / `3306` |
| `MYSQL_POOL_SIZE` | Connection pool size | `10` |

MySQL stores the user and passwords when its data volume is first created. Set your own values before the first start on a server.

### Providers and models

| Variable | Purpose | Default |
|---|---|---|
| `OPENAI_API_KEY`, `ASSEMBLYAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY` | Environment-level provider keys (fallbacks to keys saved in the app) | unset |
| `TRANSCRIPTION_PROVIDERS` | Enabled built-in provider integrations | `assemblyai,openai,gemini,openrouter` |
| `DEFAULT_TRANSCRIPTION_PROVIDER` | Fallback provider when no catalog default is available | `openai` |
| `DEFAULT_LLM_PROVIDER` | Fallback provider for direct LLM operations (`LLM_PROVIDER` remains a legacy alias) | `GEMINI` |
| `DEFAULT_LANGUAGE` | Default content language or `auto` | `auto` |
| `SUPPORTED_LANGUAGE_CODES` | Languages seeded into the active language catalog | `en,nl,fr,es` |

### Jobs and limits

| Variable | Purpose | Default |
|---|---|---|
| `TRANSCRIPTION_MAX_CONCURRENT_JOBS` | System-wide jobs allowed to process simultaneously | `2` |
| `BACKGROUND_WORKER_CONCURRENCY` | Concurrent jobs in the dedicated worker | `2` |
| `BACKGROUND_JOB_MAX_ATTEMPTS` | Maximum attempts for a durable background job | `3` |
| `BACKGROUND_JOB_STALE_SECONDS` | Age at which an abandoned worker claim is recovered | `300` |
| `TRANSCRIPTION_WORKERS` | Parallel workers used for a split transcription | `4` |
| `WORKFLOW_MAX_OUTPUT_TOKENS` | Maximum generated tokens for a workflow result | `1024` |
| `WORKFLOW_RATE_LIMIT` | Per-user workflow endpoint limit | `10 per hour` |
| `PHYSICAL_DELETION_DAYS` | Delay before soft-deleted records are purged | `120` |

### Sign-in, email, and bot protection (team mode)

| Variable | Purpose | Default |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Enables Google Sign-In in team mode | unset |
| `MAIL_*` | SMTP settings used for password reset email | unset |
| `RECAPTCHA_V3_*` | Optional reCAPTCHA v3 or Enterprise login protection | unset |
