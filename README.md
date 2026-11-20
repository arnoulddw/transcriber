# Transcriber

**Self-hosted AI transcription, live speech-to-text, and reusable LLM workflows for individuals and teams.**

Transcriber turns uploaded audio or a live microphone feed into searchable transcription history. It combines a clean web app, a bearer-token REST API, role-based access control, per-user model keys, usage quotas, and cost analytics—while keeping deployment and data under your control.

[![CI](https://github.com/arnoulddw/transcriber/actions/workflows/docker-build.yml/badge.svg)](https://github.com/arnoulddw/transcriber/actions/workflows/docker-build.yml)
[![Docker](https://img.shields.io/docker/pulls/arnoulddw/transcriber?logo=docker&label=Docker%20pulls)](https://hub.docker.com/r/arnoulddw/transcriber)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

![Transcriber web interface](transcriber-screenshot.png)

## Why Transcriber?

- **File and live transcription:** Upload audio files or transcribe a microphone in real time.
- **Bring your own models and keys:** Use OpenAI, AssemblyAI, Google Gemini, and OpenRouter without locking the app to a hard-coded model list.
- **Turn transcripts into useful output:** Generate titles and run reusable prompts for summaries, action items, notes, or any custom workflow.
- **Operate it for a team:** Add authentication, RBAC, per-user keys, quotas, retention policies, pricing, and admin analytics.
- **Automate it:** Submit and poll transcription jobs through a public REST API.
- **Self-host it:** Run the Flask and MySQL stack with Docker Compose or deploy the published Docker image.

## Feature overview

### Transcription

| Capability | What it supports |
|---|---|
| File transcription | OpenAI, AssemblyAI, Google Gemini, and OpenRouter models |
| Live transcription | OpenAI over WebRTC, Google Gemini over WebSocket, and OpenRouter using short audio chunks with streamed responses |
| Speaker diarization | Speaker labels on supported AssemblyAI jobs |
| Context prompting | Names, acronyms, and domain vocabulary where supported by the selected provider |
| Language handling | Manual language selection, automatic detection, and persisted detected-language metadata |
| Large files | Uploads up to 200 MB, with automatic splitting when a file exceeds the selected model or provider limit |
| Job lifecycle | Live progress, cancellation, recovery of abandoned jobs, and incomplete-chunk warnings |

Live sessions can run for up to 120 minutes. The app reserves live minutes against role quotas, automatically resumes Gemini connections when possible, and saves the finished live transcript to normal history. Provider API keys remain server-side; Gemini uses a constrained, short-lived token for the browser connection.

### Models, API keys, and AI workflows

- Models are registered dynamically when an admin or permitted user saves a provider API key and model name in **Manage API Keys**.
- A saved model can be marked for `transcription`, `live`, `llm`, or multiple purposes. Model lists refresh immediately after a key is saved or removed.
- Admins can rename registered models in one place, **Admin → Models**; that display name is then used consistently in selectors, history, pricing, logs, and analytics.
- Users can choose separate defaults for file transcription, live transcription, title generation, and workflows.
- Reusable workflows can summarize transcripts, extract decisions or action items, create notes, or run any custom prompt.
- A workflow can be selected before upload, or run later from history. Workflow results can be edited or deleted.
- Automatic title generation uses the selected model and recovers cleanly from interrupted operations.

### History and user experience

- Search, pin, copy, download, delete, restore, or clear transcriptions.
- View provider/model, duration, language, timestamps, workflow output, and processing warnings.
- Use the responsive interface on desktop or mobile.
- Choose English, Spanish, French, or Dutch for the interface.
- Set personal defaults for content language, models, and automatic title generation.

### Team and administration

Transcriber starts in **personal mode** and can switch to **team mode** from inside the app, with no restart or redeploy.

| | Personal mode (default) | Team mode |
|---|---|---|
| Accounts | One owner account, created on first start | Everyone gets their own account, history, workflows and API keys |
| Sign-in | Off by default; turn it on with a password in **User Settings > Access** | Required. Sign-up page (can be turned off), Google Sign-In, password resets |
| User Settings, Manage API Keys, workflows, Live | Yes | Yes |
| Admin panel | No | Yes, for admins |

Switch modes in **User Settings > Access**. The owner becomes the admin when team mode is turned on, and nothing they already have is shared. Switching back keeps every other account and its data, but those accounts can't sign in or use their API keys until team mode is on again.

Anyone who can reach an instance in personal mode without a password can use it. Set a password before you make it reachable from the internet.

The admin panel includes:

- User and role management.
- Provider and feature permissions, including API key management, public API access, downloads, workflows, context prompts, diarization, and live transcription.
- Daily, weekly, and monthly limits for transcription minutes, live minutes, workflow runs, and cost.
- History item and retention limits.
- Default models per role for file transcription, live transcription, titles, and workflows.
- Transcription, workflow, language, model, cost, performance, user, and error analytics.
- Per-model pricing for transcription, title generation, and workflows.
- System-wide workflow templates scoped to one language or all languages.

## Quick start

You need [Docker](https://docs.docker.com/get-docker/) and an API key from at least one provider (OpenAI, AssemblyAI, Google Gemini, or OpenRouter).

```bash
git clone https://github.com/arnoulddw/transcriber.git
cd transcriber
docker compose up -d
```

Then:

1. Open [http://localhost:5004](http://localhost:5004).
2. Go to **Manage API Keys**, paste a provider key, and enter a model name such as `gpt-4o-transcribe`.
3. Upload an audio file, or start a live transcription.

That's it. Transcriber starts in personal mode on your machine, with sign-in off. No configuration file is needed. When you want more, everything is optional and documented below.

> **Putting it on a server?** Set a sign-in password and your own database passwords first. See [Running on a server](docs/installation.md#running-on-a-server).

## Documentation

| Guide | What's in it |
|---|---|
| [Installation](docs/installation.md) | How the Docker setup works, running on a server, the published image, updating |
| [Configuration](docs/configuration.md) | Providers and models, live transcription, personal and team mode, every environment variable |
| [Using Transcriber](docs/usage.md) | File and live transcription, workflows |
| [Public API](docs/api.md) | Submit audio and fetch transcripts over REST |
| [Development](docs/development.md) | Local setup, CLI commands, running the tests |
| [Troubleshooting](docs/troubleshooting.md) | Fixes for common problems |

## License

Transcriber is available under the [MIT License](LICENSE).
