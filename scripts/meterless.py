"""Check the Meterless Nightshift connection by hand. Reads the repo's .env; never prints the token.

    backend/.venv/bin/python scripts/meterless.py status              # online | unauthorized | offline, lane check
    backend/.venv/bin/python scripts/meterless.py detect              # Auto Detect on the standard ports
    backend/.venv/bin/python scripts/meterless.py chat "Say pong"     # plain text on METERLESS_MODEL
    backend/.venv/bin/python scripts/meterless.py lane fast           # JSON through a lane's LangChain model
    backend/.venv/bin/python scripts/meterless.py media               # which media kinds this box can make
    backend/.venv/bin/python scripts/meterless.py illustrate "a calm hospital garden, watercolour" [--privacy cloud-ok]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pydantic import BaseModel  # noqa: E402

from app.config import Settings  # noqa: E402
from app.llm import Lane, LlmUnavailable, Media, MediaFailed, MediaUnavailable  # noqa: E402
from app.llm.nightshift import Nightshift, auto_detect  # noqa: E402


class Ping(BaseModel):
    answer: str
    confident: bool


def connect(s: Settings) -> Nightshift:
    return Nightshift(s.meterless_base_url, s.meterless_runtime_token, s.meterless_app_id, s.lane_models,
                      default_model=s.meterless_model)


async def main(args: argparse.Namespace) -> int:
    s = Settings(_env_file=ROOT / ".env")
    if args.cmd == "detect":
        hit = await auto_detect(s.meterless_runtime_token, s.meterless_app_id)
        print(f"found {hit[0]} ({hit[1]})" if hit else "no runtime on 8088, 8090, 8787 or 11434")
        return 0 if hit else 1

    ns = connect(s)
    try:
        if args.cmd == "status":
            state, ids = await ns.status()
            print(f"{ns.base_url}: {state}")
            if state == "unauthorized":
                print("  the runtime rejected METERLESS_RUNTIME_TOKEN; paste the token from <stateDir>/proxy-token")
            for lane, model in ns.lanes.items():
                print(f"  lane {lane:<5} → {model}  {'listed' if model in ids else 'NOT LISTED'}")
            return 0 if state == "online" else 1

        if args.cmd == "chat":
            print(f"[{ns.default_model}] {await ns.text(args.text)}")
            return 0

        if args.cmd == "lane":
            done = await ns.complete(Lane(args.lane), "You answer oncology questions briefly.",
                                     "Is EGFR exon 19 deletion an activating mutation?", Ping)
            print(f"requested {done.model_requested}, answered {done.model_answered}, "
                  f"{done.latency_ms} ms, {done.prompt_tokens}+{done.completion_tokens} tokens")
            print(f"  {done.value.model_dump()}")
            return 0

        media = Media(ns, ROOT / s.media_dir)
        if args.cmd == "media":
            for kind in ("image", "speech", "music", "video"):
                try:
                    plan = await media.plan(kind)
                    print(f"{kind:<6} ✓ {plan.via} → {plan.target}")
                except MediaUnavailable as e:
                    print(f"{kind:<6} ✗ {e}")
            return 0

        if args.cmd == "illustrate":
            privacy = args.privacy or s.media_privacy
            print(f"illustrating at privacy floor {privacy} …")
            made = await media.illustrate(args.text, privacy=privacy)
            print(f"stored {made.path.relative_to(ROOT)} ({made.mime}, {made.size} bytes; "
                  f"job {made.job_id}, seq {made.seq}, make {made.make_id}, {made.transform})")
            return 0
    except MediaUnavailable as e:
        print(e)
        return 2
    except (LlmUnavailable, MediaFailed) as e:
        print(f"failed: {e}")
        return 1
    finally:
        await ns.aclose()
    return 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("detect")
    sub.add_parser("chat").add_argument("text", nargs="?", default="Reply with exactly: pong")
    sub.add_parser("lane").add_argument("lane", choices=[l.value for l in Lane])
    sub.add_parser("media")
    ill = sub.add_parser("illustrate")
    ill.add_argument("text")
    ill.add_argument("--privacy", choices=["local-only", "edge-only", "cloud-ok"])
    sys.exit(asyncio.run(main(p.parse_args())))
