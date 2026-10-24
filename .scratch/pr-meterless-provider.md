Wires Meterless Nightshift in as the app's LLM provider (the Power rule). Agents get LangChain chat models from it, and there's a client for image, speech, music and video jobs.

## What's in it

- **`backend/app/llm/nightshift.py`** implements `docs/setup/meterless-provider-prompt.md`: it normalises pasted URLs to `<host>/v1`, sends the bearer token and the `meterless-app` and `meterless-scope` headers, and reads `/v1/models` to report online, unauthorized or offline. It also has Auto Detect, connect links and plain text chat. `chat_model(lane)` returns a LangChain `ChatOpenAI` pinned to the lane's model, which is how agents get a model.
- **`backend/app/llm/media.py`** makes media on a Meterless job: it plans from discovery (cached 60 s), creates the source job, finds a usable attempt, materializes with `n: 1`, waits on the make's own status, then fetches, checks and stores the bytes. If the attempts list isn't served (404, or 501 on the web build), it reads each seq one by one.
- **`app.llm.complete`** retries once with the validation error appended.
- **Config:** adds `METERLESS_MODEL`, which the old Settings rejected, so the app crashed on startup with our `.env`. All three lanes default to `nvidia/nemotron-3.5-lightning-30b-a3b`. Also adds `MEDIA_DIR` and `MEDIA_PRIVACY`, and the repo-root `.env` is now found when running from `backend/`.
- **`scripts/meterless.py`** and the DEVELOPER.md section "Check the LLM connection yourself" let you check the connection by hand.

## Tested

- 28 tests in `backend/tests/llm` run against a mocked runtime, and the boundary test passes.
- Against the local Nightshift: `status` shows online with every lane listed, a wrong token shows unauthorized, Auto Detect finds 8088, chat returns `pong`, and a JSON call on the fast lane is answered by `nvidia/nemotron-3.5-lightning-30b-a3b`.

## Not done

- **No real image yet.** The local Nightshift is the web build, which has no media engine (`runtime_unavailable: no sd-server`) and doesn't serve the artifacts route (501). `illustrate` prints `Images unavailable: <reason>`. It needs the daemon with still-sdcpp and model weights.
- LangChain agent calls aren't written to `llm_call` yet; that needs a callback once `app.trace` exists.
- The World Model conformance tests still fail 8/8. There's no ADR yet for LangChain as the agent framework.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
