# A Condition term is the set of Condition labels the Respondent chose

Status: accepted, 2026-10-25. Supersedes the single model-named Condition term of #14.

The Diagnosis check used to have the model name one formal condition ("anterior cruciate ligament tear") for the Respondent to confirm, then selected Trials by word-set containment against each Trial's listed conditions. After the Australia-wide ingest (ADR 0004) that broke in two ways. The model's name need not be one any Trial uses: none of the four Australian ACL Trials list "tear" (they say "Rupture", "Injury", "Injuries"), so a confirmed term selected nothing. And with no confirmed term every Open trial was judged, which for 2,066 Open trials is thousands of model calls per new patient.

Now the Diagnosis check offers only Condition labels the stored Trials actually use. The model turns the Respondent's words into search phrases (expanding abbreviations such as ACL), code finds the labels containing them, and the model picks up to six that fit, each shown with how many Open and Closed trials use it. The Respondent ticks one or more, or answers none of these (and may re-word) or not sure. The ticked labels are the Condition term; a Trial is selected when any of its conditions equals a ticked label, ignoring case and spacing. Until a patient has a Condition term, a Re-scan judges nothing.

We chose labels from the data over a better model-named term because every option the Respondent sees then leads to real Trials, and the selection is an exact, explainable match. We chose letting the Respondent tick several over picking one because Trials name the same condition differently. MeSH terms from ClinicalTrials.gov would give a more uniform vocabulary; they are not stored yet and are left for later.

## Consequences

- No model is ever asked to judge a Trial the Respondent's Condition term did not select.
- "Not sure" settles the check with no Condition term: no Trial is judged and a Doctor question asks the clinician for the diagnosis, as before.
- A later Diagnosis check replaces the Condition term. Verdicts for Trials it no longer selects stay stored (ADR 0002) but are not listed.
- The offered shortlist and the ticked labels are kept on the Diagnosis check so the choice can be explained later.
