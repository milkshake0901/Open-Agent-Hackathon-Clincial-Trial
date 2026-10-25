"""app/enquiry/types.py"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.trials import NctId


@dataclass(frozen=True)
class ClinicalDetail:
    """One clinical detail an Enquiry may include, already de-identified; the Respondent can untick it."""
    id: str          # the Fact id it comes from
    label: str       # "Daily activity"
    text: str        # "Fully active, doing everything as before the illness"


@dataclass(frozen=True)
class Recipient:
    """Who the Enquiry is addressed to: a Trial site contact or a central contact, always with an email."""
    name: str
    email: str
    kind: Literal["site", "central"]
    facility: str | None    # the Trial site, for a site contact


@dataclass(frozen=True)
class Enquiry:
    nct_id: NctId
    template: Literal["open", "closed"]
    subject: str
    body: str                                   # greeting, the drafted paragraphs, placeholders for name and contact
    recipient: Recipient | None                 # None: the Trial lists no email; the Respondent finds one
    sponsor: str                                # named so a Respondent with no recipient knows who runs the Trial
    details: tuple[tuple[ClinicalDetail, bool], ...]   # every detail offered, and whether this draft includes it
