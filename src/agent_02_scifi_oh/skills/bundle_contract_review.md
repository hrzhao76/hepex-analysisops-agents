# Bundle Contract Review Skill

Before returning, check the bundle as if another agent will reject it:

- The top-level value is JSON with an `artifacts` object.
- Required artifact names are present and no undeclared artifact names appear.
- JSON artifacts are objects and markdown artifacts are strings.
- Required schema fields are present.
- Histogram arrays align: edges are one longer than counts, and uncertainties
  match counts.
- Residual arrays align with either bin centers or bin edges.
- `submission_trace.json` agrees with `diphoton_fit_summary.json` on the signal
  peak field.
- `interpretation.md` is consistent with the computed fit and residuals.

