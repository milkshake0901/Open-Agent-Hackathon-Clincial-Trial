"""app/record/postcodes.py — coarse location points for Australian postcodes. Private to record: a postcode is
turned into its point when it is stored as a Search preference (ADR 0003), and distances are measured from the point.

A small committed table, enough for a Sydney demo plus each capital city and the suburbs of the Australian sites
in the saved Trial snapshot. Never fetched at runtime; a postcode not listed here means "distance unknown".

Values are approximate postcode-area centroids (latitude, longitude in degrees), rounded to 0.01° (about 1 km),
which is as coarse as a distance shown in whole km needs. Source: the Australian Bureau of Statistics Postal Areas
(POA), ASGS Edition 3 (2021), CC BY 4.0, https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/non-abs-structures/postal-areas
To extend: add rows from that dataset's POA centroids, keyed by the four-digit postcode.
"""
from __future__ import annotations

Point = tuple[float, float]   # (latitude, longitude) in degrees

CENTROIDS: dict[str, Point] = {
    # Sydney and surrounds (NSW)
    "2000": (-33.87, 151.21),   # Sydney CBD
    "2010": (-33.88, 151.21),   # Surry Hills
    "2031": (-33.91, 151.24),   # Randwick
    "2050": (-33.89, 151.18),   # Camperdown
    "2060": (-33.84, 151.21),   # North Sydney
    "2065": (-33.82, 151.19),   # St Leonards
    "2077": (-33.70, 151.10),   # Hornsby
    "2099": (-33.75, 151.29),   # Dee Why
    "2112": (-33.81, 151.10),   # Ryde
    "2140": (-33.86, 151.08),   # Homebush
    "2145": (-33.81, 150.99),   # Westmead
    "2150": (-33.82, 151.00),   # Parramatta
    "2153": (-33.76, 150.99),   # Baulkham Hills
    "2170": (-33.92, 150.92),   # Liverpool
    "2200": (-33.92, 151.03),   # Bankstown
    "2232": (-34.03, 151.06),   # Sutherland
    "2250": (-33.43, 151.34),   # Gosford
    "2300": (-32.93, 151.78),   # Newcastle
    "2500": (-34.42, 150.89),   # Wollongong
    "2560": (-34.07, 150.82),   # Campbelltown
    "2750": (-33.75, 150.69),   # Penrith
    # Capital cities
    "2600": (-35.30, 149.13),   # Canberra (ACT)
    "3000": (-37.81, 144.96),   # Melbourne (VIC)
    "4000": (-27.47, 153.03),   # Brisbane (QLD)
    "5000": (-34.93, 138.60),   # Adelaide (SA)
    "6000": (-31.95, 115.86),   # Perth (WA)
    "7000": (-42.88, 147.33),   # Hobart (TAS)
    "0800": (-12.46, 130.84),   # Darwin (NT)
    # Suburbs of the snapshot Trial's other Australian sites
    "3168": (-37.92, 145.12),   # Clayton (VIC)
    "4120": (-27.51, 153.05),   # Greenslopes (QLD)
    "6150": (-32.07, 115.84),   # Murdoch (WA)
}


def point(postcode: str | None) -> Point | None:
    """The postcode's coarse location point; None for no postcode or one not in the table ("distance unknown")."""
    return CENTROIDS.get(postcode.strip()) if postcode else None
