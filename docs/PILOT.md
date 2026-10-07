# Supervised engineering-value pilot

Status: **NOT_RUN**. The observation CSV contains a header only. No authoring-time savings, case acceptance, requirement coverage improvement or confirmed ECU defects have been measured. Synthetic extraction and mutation scores are excluded from business-value results.

## Design and supervision

Recruit diagnostic engineers authorized to work with the selected OEM requirements and bench. Use matched task pairs with comparable service/condition complexity. Counterbalance manual and assisted order across engineers; use different equivalent requirement sets to limit learning effects. Hold out the evaluation ECU/document families from parser and prompt development. Record participant expertise and document complexity anonymously.

An independent reviewer approves the requirement catalogue and hand-authored reference vectors before either arm. Both arms receive the same protocol/reference access and bench conditions. The assisted arm uses SpecProbe, including correction and approval time. Both arms receive equivalent review standards. Hardware work follows a separately signed bench safety approval; simulator-only work is labeled accordingly and cannot establish ECU defects.

Pre-register acceptance targets, exclusion rules, sample size and failure criteria with the project owner. Proposed targets belong in that signed protocol and are not copied into measured-results fields. Do not declare success from a single convenient task or from an unreviewed output count.

## Measurements

- **Authoring time:** active seconds from requirement reading through submission of reviewable cases; record interruptions separately. Include extraction correction and case revision time in the assisted arm.
- **Review effort:** independent active review seconds and number/type of corrections, including source interpretation, setup, timing, expected response and trace errors. Count rejected or unsupported cases.
- **Accepted generated cases:** cases accepted after review divided by generated cases submitted, with exact numerators/denominators. Retain suite snapshot hashes and reviewer decisions.
- **Requirement coverage:** independently approved catalogue requirements with at least one accepted, successfully executed linked case divided by the scoped catalogue. List uncovered requirements and infeasible/redundant predicate witnesses. Service/NRC counts alone are not coverage.
- **Confirmed defects:** unique findings reproduced on the approved reference bench and independently confirmed with firmware identity and raw request/response/timing evidence. Simulator mutants, extraction errors, duplicates and spec ambiguities do not count as ECU defects.

Use `data/evaluation/pilot-observations.csv`. Each row records participant/task/mode, measured author/review seconds, generated/accepted counts, scoped total/covered requirements, confirmed defects, independent confirmation reference and reviewer. Maintain a separate signed requirement-to-case matrix and defect register; assign each confirmed defect to its first discovery observation to avoid duplicate counts. Do not enter proposed targets or model generation runtime as human authoring time.

```powershell
uv run python -m eval.pilot_eval --observations <signed-observations.csv> --output <pilot-results.json>
```

The aggregation script validates supplied counts and confirmation-reference presence, summarizes each arm and returns `NOT_RUN` for an empty file. It does not verify human signatures or bench evidence. Review the raw records, paired task comparisons, medians/distributions, correction categories and uncertainty before making a benefit claim. Report missing observations, withdrawals, failures and all unsupported-layout corrections. Archive source hashes, approved snapshots, audit export, bench captures and model/deployment identities with the report.

## Release decision

An engineering review must separately accept extraction accuracy on real held-out documents, grounded answer quality with configured local models, independent protocol/timing results, deployment/recovery/access controls and measured pilot benefit. Failure or absence of one gate remains explicit. Successful simulator tests alone authorize only the supervised simulator scope; they do not authorize uncontrolled production-vehicle diagnostics.
