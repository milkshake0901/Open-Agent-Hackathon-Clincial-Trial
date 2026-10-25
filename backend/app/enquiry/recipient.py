"""app/enquiry/recipient.py — who an Enquiry is addressed to. Only a contact with an email can be; with none, the
recipient is left blank and the Enquiry names the sponsor."""
from __future__ import annotations

import re

from app import matching, trials
from app.enquiry.types import Recipient


def _emailed(contacts: tuple[trials.Contact, ...]) -> trials.Contact | None:
    return next((c for c in contacts if c.email), None)


def for_open(sites: tuple[trials.TrialSite, ...], contacts: trials.TrialContacts,
             at: tuple[float, float] | None) -> Recipient | None:
    """Open trial: the contact of the nearest Australian Trial site that may still take the patient (distance from
    the patient's coarse point; registry order when it is unknown), else the central contact."""
    def distance(i_site: tuple[int, trials.TrialSite]):
        i, s = i_site
        d = matching.km(at, (s.lat, s.lon)) if at and s.lat is not None and s.lon is not None else None
        return d is None, d or 0, i
    for _, s in sorted(enumerate(sites), key=distance):
        if s.status not in matching.CLOSED_SITE and (c := _emailed(s.contacts)):
            return Recipient(name=c.name, email=c.email, kind="site", facility=s.facility)
    if c := _emailed(contacts.central):
        return Recipient(name=c.name, email=c.email, kind="central", facility=None)
    return None


def _words(name: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", name.lower()))


def for_closed(sites: tuple[trials.TrialSite, ...], contacts: trials.TrialContacts) -> Recipient | None:
    """Closed trial: the responsible party, else an overall official. The registry gives a responsible party no email,
    so they are reached where the Trial lists the same person with one (an overall official, a central or a site
    contact: every word of the responsible party's name in theirs, so "Jane Citizen" is "Dr Jane Citizen")."""
    if (rp := contacts.responsible_party) and (want := _words(rp.name)):
        listed = contacts.officials + contacts.central + tuple(c for s in sites for c in s.contacts)
        if c := _emailed(tuple(c for c in listed if want <= _words(c.name))):
            return Recipient(name=c.name, email=c.email, kind="responsible_party", facility=None)
    if c := _emailed(contacts.officials):
        return Recipient(name=c.name, email=c.email, kind="official", facility=None)
    return None
