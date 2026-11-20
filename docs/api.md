# Public transcription API

Users whose role allows public API access can create and revoke named bearer tokens in **Manage API Keys → Public API Access**. API jobs use the user's default model and language, follow the same permissions and quotas as the web app, and appear in normal history.

## Submit audio

```bash
curl -X POST https://your-domain.example.com/api/v1/transcribe \
  -H "Authorization: Bearer <YOUR_API_KEY>" \
  -F "audio_file=@/path/to/audio.wav"
```

A successful request returns HTTP `202`:

```json
{
  "job_id": "<uuid>",
  "message": "Transcription job started successfully.",
  "audio_length_minutes": 3.42
}
```

## Poll status and get the result

```bash
curl https://your-domain.example.com/api/v1/transcribe/<job_id> \
  -H "Authorization: Bearer <YOUR_API_KEY>"
```

The response includes a machine-readable `status`. A finished job includes `result.transcription_text`, the detected language, filename, provider, duration, and creation time. Failed or cancelled jobs include `error_message`. The alias `/api/v1/transcriptions/<job_id>` is also supported.

## Rate limits

By default each API key can make 10 submissions per hour and 120 status requests per hour.
