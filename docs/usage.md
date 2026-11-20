# Using Transcriber

- [Transcribe a file](#transcribe-a-file)
- [Transcribe live audio](#transcribe-live-audio)
- [Create and run workflows](#create-and-run-workflows)
- [Personal and team mode](#personal-and-team-mode)

Before you start, add at least one provider key and model in **Manage API Keys** (see [Configuration › Providers and models](configuration.md#providers-and-models)).

## Transcribe a file

1. Choose a registered transcription model.
2. Select the spoken language or leave automatic detection on.
3. Optionally add names, acronyms, or subject vocabulary as context.
4. Optionally enable AssemblyAI speaker diarization.
5. Optionally select a workflow to run after transcription.
6. Upload an `mp3`, `m4a`, `wav`, `ogg`, `webm`, `mpga`, or `mpeg` file and select **Transcribe**.
7. Follow progress on the page; the finished transcript appears in history.

Files up to 200 MB are accepted. Files larger than the selected model's limit are split automatically.

## Transcribe live audio

Open **Live transcription**, choose a microphone, language, and live model, then select **Start**. Interim text appears while you speak. Select **Stop and save** to store the transcript in history, where it behaves like any uploaded transcription.

Live transcription needs browser microphone permission and a browser that supports the transport used by the selected provider. Sessions can run for up to 120 minutes.

## Create and run workflows

Open **Manage Workflow Prompts** to save reusable prompts, such as summaries, action items, or meeting notes. Run a workflow on a finished transcript from history, or select it before an upload so it runs automatically. Workflow results can be edited or deleted.

Admins can publish workflow templates for one transcription language or for all languages.

## Personal and team mode

Transcriber starts in **personal mode**: one owner account, sign-in off by default. Switch to **team mode** in **User Settings > Access** to give everyone their own account, history, workflows and API keys, and to unlock the Admin panel.

When team mode is turned on, the owner becomes the admin and nothing they already have is shared. Switching back keeps every other account and its data, but those accounts can't sign in or use their API keys until team mode is on again.

Anyone who can reach a personal-mode instance without a password can use it. Set a password before you make it reachable from the internet.
