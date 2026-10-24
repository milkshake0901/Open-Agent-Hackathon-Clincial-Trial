# Question for the data engineer: what Trial data does Postgres keep, and what do we read live through Zetaris?

**Status:** open. **Asked:** 2026-10-24. **Blocks:** scaling from the one-Trial test to a cohort, and finalising the `trial` table.

## Background
- Zetaris is our single SQL access point. Agents read ClinicalTrials.gov through Zetaris REST tables and views, not
  through our own HTTP pipeline. HTTP is only a fallback.
- Our own Postgres holds what the World Model writes (ADR 0001). Zetaris registers it as datasource `trialmatch`.
- A **Verdict** is keyed by (Trial, eligibility hash, Profile version) (ADR 0002). A Verdict judged against old
  Criteria must keep showing those Criteria after the Trial changes.

The one-Trial test (`.scratch/zetaris-one-trial/`) currently copies the eligibility text into `trial` and the split
Criteria into `criterion`. Everything else comes from the Zetaris CT.gov views. That works for one Trial, but we need a rule before scaling.

## The question
**Which Trial fields must Postgres keep (versioned), and which should be read live through Zetaris every time?**

## Worked example: NCT07680790
- **1 Nov:** we judge the patient's Profile version 3. Criterion 4, "ECOG Performance Status 0-1", is **met**,
  citing a Fact "ECOG 1" from a referral letter. The Trial has 2 sites near Sydney, both NOT_YET_RECRUITING.
- **15 Nov:** the sponsor edits the criterion to "ECOG 0-2" and opens a new recruiting site in Sydney.

| | Criteria read live | Criteria kept in Postgres (by eligibility hash) |
|---|---|---|
| v3 Verdict on 16 Nov | cites "ECOG 0-2", text it was **never judged against** | still shows "ECOG 0-1 met" |
| New Verdict | judged against "ECOG 0-2" | judged against "ECOG 0-2" under the new hash; the old one is kept beside it |

| | Sites read live | Sites kept in Postgres |
|---|---|---|
| UI on 16 Nov | shows the new recruiting site | shows the 1 Nov list unless re-synced |
| v3 Verdict explanation | can't say which sites existed on 1 Nov | can |

## Options
1. **Copy Criteria only (our recommendation).** Postgres keeps `eligibility_text`, `eligibility_hash` and the split
   `criterion` rows. Sites, MeSH, interventions, age, sex and status are read live from Zetaris. The `trial` table
   shrinks to `nct_id, eligibility_hash, fetched_at`.
   - *For:* Verdicts stay explainable, and nothing is duplicated.
   - *Against:* "which sites existed when we judged" is lost.
2. **Copy everything.** Postgres keeps a full snapshot per sync.
   - *For:* every Verdict is fully reproducible.
   - *Against:* it duplicates Zetaris and goes against the sponsor's "no pipeline per source" point.
3. **Copy nothing.** Read Criteria live too.
   - *For:* smallest footprint.
   - *Against:* an edited Trial breaks the explanation and Citations of old Verdicts.

## Facts you'll need
- **Re-fetching:** a Zetaris REST table is one fixed URL and **re-fetches on every uncached query**. Without
  `CACHE TABLE`, a "live" read is a live API call, with the latency and rate-limit risk that brings.
- **Paging:** `/studies/{nct}` returns one study object. `/studies?…` returns pages of at most 1,000 Trials, and the
  next page's token is only known after reading the current page, so each page needs its own REST table.
- **Size:** one page of 96 NSCLC Trials is 4.0 MB. The `fields=` list cuts it by 37.5%, and sites take most of the
  space. One Trial with `fields=` is 39 KB.
- **Change detection:** `lastUpdatePostDate` (exposed as `ctgov_trial_core.last_update_posted`) is a cheap "did it
  change?" check before re-hashing the eligibility text.
- **Hash rule:** the eligibility hash is sha256 over whitespace-normalised text, so cosmetic edits don't create a new hash.
- **Not yet tested:** whether Zetaris keeps a `CACHE TABLE` across restarts, and how long it caches our Postgres reads.

## Sub-questions
- If option 1: is losing "which sites existed at judgement time" acceptable, or do sites need a lighter history
  (for example, sites as of each Verdict)?
- How often should a sync run, and should it be triggered by `lastUpdatePostDate`?
- Should CT.gov data be cached in Zetaris (`CACHE TABLE`), materialised, or left uncached?

## Answer
- **Decision:**
- **Decided by:**
- **Date:**
- **Notes:**
