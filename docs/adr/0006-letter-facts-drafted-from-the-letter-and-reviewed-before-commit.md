# A letter's Facts are drafted from the letter and reviewed before commit

Status: accepted, 2026-10-26. Changes how a letter reaches the record under ADR 0003; leaves ADR 0002 unchanged.

A referral letter used to fill the Intake questionnaire. Code copied its words into answers, and the answers became Patient-reported Facts. No Citation could reach the letter, and copying answers that way only worked for one letter's layout. Now every uploaded PDF is read page by page by Nemotron Parse into Regions, and the Intake agent drafts Facts from the letter itself, one call per page. Each Fact cites the Region it quotes. The Critic's code rules check the quote, the numbers and the date order before any person looks. The questionnaire asks only what the letter didn't answer.

Before commit, the Respondent may run a Letter review: each drafted Fact shown beside its Region, kept or dropped. The review happens before commit because ADR 0002 lets a clinical Fact supersede by observed-on date, so a later Patient-reported correction could lose to the very Fact it meant to fix. A dropped Fact is never committed, and what the Respondent says it should be becomes an answer in their questionnaire. The review is optional; skipping it commits the Facts as read, marked not checked.

An unknown Criterion result still cites nothing (the Evaluator rule). It may list the Context Facts it considered, which code checks are real Facts of that Profile version. That lets a "needs checking" reason open the letter without weakening what a Citation means.

## Considered options

- Keep the questionnaire as the only source of Facts, and have each pre-filled answer remember the Regions it was copied from. Rejected: the letter would never be a Document Intake reads, and copying answers still depends on the letter's layout.
- Correct letter Facts after commit with a Patient-reported Fact. Rejected: under ADR 0002 the correction does not reliably supersede.
- Let unknown results carry Citations. Rejected: a Citation means a Fact settles the claim.
