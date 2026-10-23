# Write to Postgres directly, read through Zetaris

Zetaris is the required data layer, but it federates over other stores rather than owning writes, it exposes Postgres read-only, and it cannot read files on the laptop. So the app writes Facts, Profile versions, Trials and Verdicts straight into its own Postgres container, registers that Postgres and the ClinicalTrials.gov API as Zetaris sources, and every agent reads only through Zetaris SQL. Source PDFs never enter Zetaris; only Facts extracted from them do, each carrying its Document hash and page.

## Consequences

- There are two connection paths to the same data (a Postgres writer, a Zetaris reader). Code that writes must not also read its own writes back through Zetaris in the same step without allowing for Zetaris caching.
- Our Postgres is separate from the `postgres` container inside the Zetaris bundle, which is Zetaris's internal store.
