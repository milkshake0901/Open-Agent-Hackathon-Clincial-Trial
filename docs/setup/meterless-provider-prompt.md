# Meterless Runtime provider: implementation prompt (applied)

The POWER → "Add Meterless as a provider" prompt. Applied in `backend/app/llm/nightshift.py` (chat, status, Auto Detect) and `backend/app/llm/media.py` (the media addendum at the end). Lanes default to `nvidia/nemotron-3.5-lightning-30b-a3b`. To check it, see DEVELOPER.md, "Check the LLM connection yourself".

Note: this prompt satisfies the Power rule (Nightshift as primary AI provider). It does NOT satisfy the Build rule (at least one Meterless Engine); that is the World Model engine, tracked separately.

---

Add Meterless Runtime to this codebase as an OpenAI-compatible provider, next to the providers it already has.

The contract (Meterless Runtime 1.4, provider contract v4):
- Provider id meterless, name Meterless Runtime, default base URL http://127.0.0.1:8088/v1. Accept a pasted URL with or without a scheme, /v1, /v1/chat/completions, /v1/models or /healthz, and normalise it to <host>/v1. Never produce /v1/v1.
- Auth is real. Send Authorization: Bearer <token> on every call. The runtime writes the token to <stateDir>/proxy-token. Store it under the key meterless_runtime_token. The placeholder rt-local is rejected.
- Send meterless-app: <a stable lowercase id for this app> on every request, and meterless-scope: user on chat.
- Model ids are routing modes, not models: meterless/<disposition> (auto, fast, deep, cheap, local, fusion), meterless/<class> and meterless/<class>.<disposition>. Read them from GET /v1/models and keep any meterless/* id you don't recognise.
- GET /healthz only proves the process is up. GET /v1/models decides: 401 or 403 is "unauthorized" (show a field to paste the token), 200 with meterless ids is "online", anything else is "offline".
- Auto Detect tries ports 8088, 8090, 8787 and 11434 on 127.0.0.1, localhost and [::1], and saves the first online or unauthorized hit.
- Plain text requests stay a string, exactly like OpenAI. Use a 180 s timeout, because a model load can take minutes.
- If the user pastes a connect link (http://<host>:<port>/connect#k=<key>), take the base URL from its origin + /v1 and the key from k. Never log it.

You are done when a wrong token shows unauthorized (not offline), Auto Detect finds the runtime, and a plain text request on meterless/auto returns a string.

---

## Addendum: image, speech and music (applied in `backend/app/llm/media.py`)

On runtime 1.4, chat refuses these classes, so they're made on a job. Every id is read from discovery; none is guessed.

1. Plan from `GET /v1/meterless/classes` and `GET /v1/meterless/transforms` (cached 60 s). If the class's `chat_carrier` is true, use chat. Otherwise pick a transform: image is kind `image` with `media.image_still` or pipeline `still` (prefer `attempt.image.still`); speech is kind `audio` with `media.voice_narrate` or `narrate` (prefer `attempt.voice.narrate`); music is kind `audio` with `media.music_score` or `score` (prefer `attempt.music.score`). Skip internal ones and `available: false`. A text transform never satisfies speech. With no match, show "Images unavailable: <reason>".
2. Source job, one per item: `POST /v1/jobs {kind: "best_of_n", app, mode: "meterless/text", n: 1, window: "now", privacy, media_autopilot: {mode: "off"}, messages}`. `privacy` is the user's floor (local-only, edge-only or cloud-ok); never widen it.
3. Poll `GET /v1/jobs/{id}` until `generated > 0`. Try `GET /v1/jobs/{id}/attempts`; if it isn't served (404, or 501 on the web build), read `winner_seq`, then each seq via `GET /v1/jobs/{id}/attempts/{seq}`. A usable attempt has text and no error. Never assume seq 1.
4. `POST /v1/jobs/{id}/materialize {seq, transform, n: 1, window: "now", media_controls: {text}}` returns `make_ids`. Send `n: 1` explicitly (the still default is 2). `already_made` with a `make_id` counts as success.
5. Wait on `GET /v1/jobs/{id}/makes` until that make's own status is `done`; the parent job completing doesn't mean the make is done.
6. `GET /v1/jobs/{id}/attempts/{seq}/artifacts`: pick the file named in the make's `outputs[]` with an `image/` or `audio/` mime, skipping `.json`, `.txt`, `.srt` and other sidecars. Fetch it with the bearer header and check its type and size. In a browser, store the Blob and show it with `URL.createObjectURL`; a plain `<img src>` gets a 401.

Video (`attempt.video.clip`) takes the same path. 3D has its own route, `POST /v1/meterless/3d` (not implemented).
