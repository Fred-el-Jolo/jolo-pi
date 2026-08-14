# Brief one-line summary of what each pattern does

Trimmed from the full 234-pattern Fabric catalog to the patterns that are genuinely science/evidence-based and non-overlapping with each other and with the other draft skills (FirstPrinciples, IterativeDepth, RootCauseAnalysis, SystemsThinking, ISA).

## Rigor / epistemics

1. **analyze_claims**: Analyse and rate truth claims with evidence, counter-arguments, fallacies, and final recommendations.
2. **analyze_paper**: Analyses research papers by summarizing findings, evaluating rigor, and assessing quality to provide insights for documentation and review.
3. **explain_math**: Helps you understand mathematical concepts in a clear and engaging way.
4. **extract_extraordinary_claims**: Extracts and outputs a list of extraordinary claims from conversations, focusing on scientifically disputed or false statements ("extraordinary claims require extraordinary evidence" — Sagan standard).
5. **find_logical_fallacies**: Identifies and analyzes fallacies in arguments, classifying them as formal or informal with detailed reasoning.
6. **solve_with_cot**: Forces explicit step-by-step reasoning before an answer — chain-of-thought prompting (Wei et al. 2022).

## Personal development, science-grounded

7. **create_better_frame**: Finds alternative interpretive frames for a situation — cognitive reframing, a core CBT technique.
8. **dialog_with_socrates**: Draws out and pressure-tests your own beliefs via Socratic questioning.
9. **t_check_dunning_kruger**: Checks self-perception against demonstrated competence — Dunning-Kruger effect (Kruger & Dunning, 1999). **Needs adaptation**: as written it expects a LifeOS "TELOS File" as input context; generalize that before use.
10. **t_find_negative_thinking**: Flags cognitive distortions in your own writing/journaling — rooted in Beck/Burns cognitive-distortion theory (CBT). **Needs adaptation**: same TELOS-file coupling as above.

## Considered, not added (flagging in case you want them)

- **identify_dsrp_distinctions / _perspectives / _relationships / _systems** (4 patterns) — Cabrera's DSRP systems-thinking framework, real academic grounding, but overlaps the domain already covered by the kept `SystemsThinking` skill (Meadows/Iceberg-based). Worth adding only if you want DSRP specifically as a second, distinct systems-thinking lens.
- **rate_ai_response / rate_ai_result / arbiter-create-ideal / arbiter-evaluate-quality / arbiter-general-evaluator / arbiter-run-prompt** — structured LLM-output evaluation/rubric patterns. Legitimate measurement-methodology grounding and on-theme for "high precision," but 6 overlapping patterns with no `Evals` skill in this repo to anchor them. Worth a dedicated pass rather than a blind add.
- **t_find_blindspots**, **t_red_team_thinking**, **analyze_mistakes** — reasonable personal-development value but weaker/no named research grounding, and some overlap with `RootCauseAnalysis` (mistake/failure analysis) already kept.
- **judge_output** — despite the generic name, it's hardcoded to Honeycomb query evaluation. Not generalizable.
