"""app/llm/media.py — image, speech, music and video made on a Meterless job (Runtime 1.4).

Chat refuses these classes on 1.4, so each item goes: plan from discovery → source job → usable attempt →
materialize → wait for the make → fetch its artifact → store the bytes under Settings.media_dir.
Every id (class, transform, job, seq, make, file) is read from the runtime; none is guessed.
3D is a separate route (POST /v1/meterless/3d) and isn't covered here."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:
    from app.llm.nightshift import Nightshift

MediaKind = Literal["image", "speech", "music", "video"]
Privacy = Literal["local-only", "edge-only", "cloud-ok"]
PRIVACY: tuple[str, ...] = ("local-only", "edge-only", "cloud-ok")

DISCOVERY_TTL_S = 60.0
SIDECARS = (".json", ".txt", ".srt", ".vtt", ".md", ".log")
FAILED = {"failed", "error", "cancelled", "canceled", "skipped", "rejected"}


@dataclass(frozen=True)
class _Want:
    cls: str          # class in GET /v1/meterless/classes
    kind: str         # transform kind
    capability: str   # transform capability
    pipeline: str     # or transform pipeline
    prefer: str       # preferred transform id when several match
    mime: str         # artifact mime prefix
    label: str


WANTS: dict[str, _Want] = {
    "image":  _Want("image", "image", "media.image_still", "still", "attempt.image.still", "image/", "Images"),
    "speech": _Want("speech", "audio", "media.voice_narrate", "narrate", "attempt.voice.narrate", "audio/", "Speech"),
    "music":  _Want("music", "audio", "media.music_score", "score", "attempt.music.score", "audio/", "Music"),
    "video":  _Want("video", "video", "media.video_clip", "clip", "attempt.video.clip", "video/", "Video"),
}


class MediaUnavailable(Exception):
    """Nothing on this runtime can make the kind. str() is the line to show: 'Images unavailable: <reason>'."""
    def __init__(self, kind: MediaKind, reason: str) -> None:
        super().__init__(f"{WANTS[kind].label} unavailable: {reason}")
        self.kind, self.reason = kind, reason


class MediaFailed(Exception):
    """Planned, but the job, attempt, make or artifact failed."""


@dataclass(frozen=True)
class Plan:
    kind: MediaKind
    via: Literal["chat", "transform"]
    target: str       # class name (chat) or transform id


@dataclass(frozen=True)
class StoredMedia:
    kind: MediaKind
    path: Path
    mime: str
    size: int
    transform: str | None
    job_id: str | None
    seq: int | None
    make_id: str | None


def _items(body, *keys: str) -> list[dict]:
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    for k in keys:
        if isinstance(body.get(k), list):
            return [x for x in body[k] if isinstance(x, dict)]
    return []


def _first(d: dict, *keys: str):
    return next((d[k] for k in keys if d.get(k) not in (None, "")), None)


def _error(r: httpx.Response) -> dict:
    """The runtime's {"error": {"code", "message", ...}} body, or {} when there isn't one."""
    try:
        body = r.json()
    except ValueError:
        return {}
    err = body.get("error") if isinstance(body, dict) else None
    return err if isinstance(err, dict) else {}


# The web build answers routes it doesn't serve with 501 route_not_implemented; older runtimes with 404.
NOT_SERVED = (404, 501)


class Media:
    """Media generation on one Nightshift connection. poll_s / wait_s bound every wait."""

    def __init__(self, ns: "Nightshift", media_dir: str | Path, *, poll_s: float = 2.0, wait_s: float = 1800.0,
                 clock=time.monotonic) -> None:
        self.ns, self.dir = ns, Path(media_dir)
        self.poll_s, self.wait_s, self.clock = poll_s, wait_s, clock
        self._cache: tuple[float, dict, dict] | None = None

    # ---- 1. plan ------------------------------------------------------------------------------
    async def discovery(self) -> tuple[dict, dict]:
        """GET /v1/meterless/classes and /v1/meterless/transforms, cached for 60 s."""
        if self._cache and self.clock() - self._cache[0] < DISCOVERY_TTL_S:
            return self._cache[1], self._cache[2]
        classes, transforms = await asyncio.gather(self._get("/meterless/classes"), self._get("/meterless/transforms"))
        self._cache = (self.clock(), classes, transforms)
        return classes, transforms

    async def plan(self, kind: MediaKind) -> Plan:
        """Chat when the class says chat carries it; otherwise the best available, non-internal transform of
        the right kind. A text transform never satisfies speech. Raises MediaUnavailable with the runtime's reason."""
        w = WANTS[kind]
        classes, transforms = await self.discovery()
        cls = (classes.get("classes") or {}).get(w.cls) or {}
        if cls.get("chat_carrier") is True:
            return Plan(kind, "chat", w.cls)
        fits = [t for t in _items(transforms, "data")
                if t.get("kind") == w.kind and not t.get("internal")
                and (t.get("capability") == w.capability or t.get("pipeline") == w.pipeline)]
        usable = [t for t in fits if t.get("available") is not False]
        if usable:
            best = next((t for t in usable if t.get("id") == w.prefer), usable[0])
            return Plan(kind, "transform", best["id"])
        preferred = [t for t in fits if t.get("id") == w.prefer]
        reason = (next((t["reason"] for t in preferred + fits if t.get("reason")), None)
                  or cls.get("why") or f"no transform offers {w.capability}")
        raise MediaUnavailable(kind, reason)

    # ---- the whole path -------------------------------------------------------------------------
    async def make(self, kind: MediaKind, text: str, *, privacy: Privacy, messages: list[dict] | None = None) -> StoredMedia:
        """One item. `text` is the exact prompt (image, video, music) or the exact words to speak (speech).
        `privacy` is the user's floor and is sent as given, never widened."""
        if privacy not in PRIVACY:
            raise ValueError(f"privacy must be one of {PRIVACY}, not {privacy!r}")
        plan = await self.plan(kind)
        if plan.via == "chat":
            return await self._via_chat(plan, text)
        job_id = await self.source_job(messages or [{"role": "user", "content": text}], privacy)
        seq = await self.usable_attempt(job_id)
        make_id = await self.materialize(kind, job_id, seq, plan.target, text)
        made = await self.wait_make(job_id, make_id)
        return await self.fetch(kind, job_id, seq, made, plan.target)

    async def illustrate(self, prompt: str, *, privacy: Privacy) -> StoredMedia:
        return await self.make("image", prompt, privacy=privacy)

    async def narrate(self, words: str, *, privacy: Privacy) -> StoredMedia:
        return await self.make("speech", words, privacy=privacy)

    async def score(self, prompt: str, *, privacy: Privacy) -> StoredMedia:
        return await self.make("music", prompt, privacy=privacy)

    # ---- 2. source job ------------------------------------------------------------------------
    async def source_job(self, messages: list[dict], privacy: Privacy) -> str:
        body = await self._post("/jobs", {
            "kind": "best_of_n", "app": self.ns.app_id, "mode": "meterless/text", "n": 1, "window": "now",
            "privacy": privacy, "media_autopilot": {"mode": "off"}, "messages": messages,
        }, what="source job")
        if not body.get("id"):
            raise MediaFailed(f"source job answered without an id: {json.dumps(body)[:200]}")
        return body["id"]

    # ---- 3. attempt ---------------------------------------------------------------------------
    async def usable_attempt(self, job_id: str) -> int:
        """Poll until generated > 0, then the first attempt with text and no error (winner first)."""
        deadline = self.clock() + self.wait_s
        while True:
            job = await self._get(f"/jobs/{job_id}")
            if (job.get("generated") or 0) > 0:
                break
            if job.get("status") in FAILED:
                raise MediaFailed(f"source job {job_id} {job['status']} before any attempt")
            if self.clock() > deadline:
                raise MediaFailed(f"source job {job_id} made no attempt in {self.wait_s:.0f} s (status {job.get('status')})")
            await asyncio.sleep(self.poll_s)

        r = await self.ns.http.get(f"/jobs/{job_id}/attempts")
        if r.status_code in NOT_SERVED:
            # No list on this runtime. Read the winner, then each seq the job reports.
            attempts = []
            for seq in self._seqs(job):
                one = await self.ns.http.get(f"/jobs/{job_id}/attempts/{seq}")
                if one.is_success:
                    attempts.append({"seq": seq, **one.json()})
        elif r.is_success:
            attempts = _items(r.json(), "data", "attempts")
            winner = job.get("winner_seq")
            attempts.sort(key=lambda a: a.get("seq") != winner)
        else:
            raise MediaFailed(f"attempts for {job_id}: HTTP {r.status_code} {r.text[:200]}")
        for a in attempts:
            if isinstance(a.get("text"), str) and a["text"].strip() and not a.get("error") and a.get("seq") is not None:
                return int(a["seq"])
        raise MediaFailed(f"source job {job_id} has no usable attempt (text and no error)")

    @staticmethod
    def _seqs(job: dict) -> list[int]:
        seqs = [job.get("winner_seq"), job.get("runner_up_seq")]
        for c in job.get("clusters") or []:
            if isinstance(c, dict):
                seqs += c.get("seqs") or c.get("members") or []
        seqs += range(1, (job.get("generated") or 0) + 1)   # each one is fetched and checked, not assumed
        return [int(s) for s in dict.fromkeys(seqs) if isinstance(s, int)]

    # ---- 4. make ------------------------------------------------------------------------------
    async def materialize(self, kind: MediaKind, job_id: str, seq: int, transform: str, text: str) -> str:
        """n: 1 explicitly (the still default is 2). already_made with a make_id counts as success."""
        r = await self.ns.http.post(f"/jobs/{job_id}/materialize", json={
            "seq": seq, "transform": transform, "n": 1, "window": "now", "media_controls": {"text": text},
        })
        if r.is_success and r.json().get("make_ids"):
            return r.json()["make_ids"][0]
        err = _error(r)
        if err.get("code") == "already_made" and err.get("make_id"):
            return err["make_id"]
        if err.get("code") == "runtime_unavailable":
            raise MediaUnavailable(kind, err.get("message") or "the runtime has no media engine")
        raise MediaFailed(f"materialize {transform} on {job_id}/{seq}: HTTP {r.status_code} {r.text[:300]}")

    # ---- 5. wait on the make ------------------------------------------------------------------
    async def wait_make(self, job_id: str, make_id: str) -> dict:
        """The make's own status decides; the parent job completing does not mean the make is done."""
        deadline = self.clock() + self.wait_s
        while True:
            makes = _items(await self._get(f"/jobs/{job_id}/makes"), "data", "makes")
            made = next((m for m in makes if make_id in (m.get("id"), m.get("make_id"))), None)
            status = (made or {}).get("status")
            if status == "done":
                return made
            if status in FAILED:
                raise MediaFailed(f"make {make_id} {status}: {_first(made, 'error', 'reason') or 'no reason given'}")
            if self.clock() > deadline:
                raise MediaFailed(f"make {make_id} not done in {self.wait_s:.0f} s (status {status})")
            await asyncio.sleep(self.poll_s)

    # ---- 6. bytes -----------------------------------------------------------------------------
    async def fetch(self, kind: MediaKind, job_id: str, seq: int, made: dict, transform: str | None) -> StoredMedia:
        """The file named in the make's outputs[] with an image/ or audio/ (or video/) mime, skipping
        sidecars, fetched with the bearer header, checked for type and size, then stored."""
        w = WANTS[kind]
        named = {PurePosixPath(o if isinstance(o, str) else str(_first(o, "name", "file", "path", "filename") or "")).name
                 for o in made.get("outputs") or []} - {""}
        listing = await self.ns.http.get(f"/jobs/{job_id}/attempts/{seq}/artifacts")
        if listing.status_code in NOT_SERVED:
            raise MediaUnavailable(kind, _error(listing).get("message") or "this runtime doesn't serve attempt artifacts")
        if not listing.is_success:
            raise MediaFailed(f"artifacts for {job_id}/{seq}: HTTP {listing.status_code}")
        files = _items(listing.json(), "data", "artifacts", "files")
        pick = None
        for f in files:
            name = PurePosixPath(str(_first(f, "name", "filename", "path", "file") or "")).name
            mime = str(_first(f, "mime", "mime_type", "content_type", "type") or mimetypes.guess_type(name)[0] or "")
            if name in named and mime.startswith(w.mime) and not name.lower().endswith(SIDECARS):
                pick = (f, name, mime)
                break
        if not pick:
            raise MediaFailed(f"make {made.get('id') or made.get('make_id')} lists {sorted(named)}, "
                              f"but no {w.mime}* artifact of that name is on {job_id}/{seq}")
        f, name, mime = pick
        url = str(_first(f, "url", "href", "download_url") or f"/jobs/{job_id}/attempts/{seq}/artifacts/{name}")
        data, got = await self._download(url)
        if not got.startswith(w.mime):
            raise MediaFailed(f"{name} came back as {got or 'no content type'}, not {w.mime}*")
        declared = _first(f, "size", "bytes", "size_bytes")
        if not data or (isinstance(declared, int) and declared != len(data)):
            raise MediaFailed(f"{name} is {len(data)} bytes; the runtime declared {declared}")
        path = self.dir / job_id / f"{seq}-{name}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredMedia(kind, path, got, len(data), transform, job_id, seq, made.get("id") or made.get("make_id"))

    async def _download(self, url: str) -> tuple[bytes, str]:
        parts = urlsplit(url)
        if parts.scheme:
            if f"{parts.scheme}://{parts.netloc}" != self.ns.origin:
                raise MediaFailed("artifact URL points off the runtime host; not sending the token there")
            full = url
        elif url.startswith("/v1/") or not url.startswith("/"):
            full = self.ns.origin + (url if url.startswith("/") else "/v1/" + url)
        else:
            full = self.ns.base_url + url
        r = await self.ns.http.get(full)   # same client: Authorization: Bearer on the download too
        if not r.is_success:
            raise MediaFailed(f"artifact download HTTP {r.status_code}")
        return r.content, r.headers.get("content-type", "").split(";")[0].strip()

    # ---- chat carrier ---------------------------------------------------------------------------
    async def _via_chat(self, plan: Plan, text: str) -> StoredMedia:
        w = WANTS[plan.kind]
        model = f"meterless/{plan.target}"
        if model not in await self.ns.models():
            raise MediaUnavailable(plan.kind, f"the runtime says chat carries {plan.target}, but lists no {model} model")
        body = await self.ns.chat(model, [{"role": "user", "content": text}])
        found = re.search(r"data:(%s[\w.+-]+);base64,([A-Za-z0-9+/=]+)" % re.escape(w.mime),
                          json.dumps(body.get("choices") or []))
        if not found:
            raise MediaFailed(f"{model} answered without {w.mime}* bytes")
        mime, data = found.group(1), base64.b64decode(found.group(2))
        path = self.dir / "chat" / f"{hashlib.sha256(data).hexdigest()[:16]}{mimetypes.guess_extension(mime) or ''}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredMedia(plan.kind, path, mime, len(data), None, None, None, None)

    # ---- http ---------------------------------------------------------------------------------
    async def _get(self, path: str) -> dict:
        try:
            r = await self.ns.http.get(path)
        except httpx.HTTPError as e:
            raise MediaFailed(f"GET {path}: {type(e).__name__}") from e
        if not r.is_success:
            raise MediaFailed(f"GET {path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    async def _post(self, path: str, body: dict, *, what: str) -> dict:
        try:
            r = await self.ns.http.post(path, json=body)
        except httpx.HTTPError as e:
            raise MediaFailed(f"{what}: {type(e).__name__}") from e
        if not r.is_success:
            raise MediaFailed(f"{what}: HTTP {r.status_code} {r.text[:300]}")
        return r.json()
