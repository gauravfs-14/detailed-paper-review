# Phase 4b: missing critical statistics, metrics and reporting items

Goal: find what a referee will ask for because it is not there. Phase 4 checks what is reported; this
phase checks what should be reported and is absent. Each missing item is a finding with severity by
impact: missing for a headline claim is major or critical; missing for a side analysis is minor.

## Step 1: classify the study

Pick every type that applies: randomized trial; observational/epidemiological; diagnostic accuracy;
prediction or machine-learning model; systematic review or meta-analysis; animal study; qualitative or
interview study; survey; computational/simulation; benchmark or dataset paper; engineering experiment.

## Step 2: run the matching checklist

Report each item as present (with location), absent, or not applicable. Use the reporting guideline the
field expects and name it in the finding (CONSORT, STROBE, STARD, TRIPOD/TRIPOD+AI, PRISMA, ARRIVE,
COREQ/SRQR, CHERRIES/AAPOR, CLAIM for medical imaging AI, MI-CLAIM, model cards / datasheets).

**Every quantitative paper**
- `n` for every group and analysis, and what `n` counts; how `n` was chosen (power analysis or rationale).
- Effect sizes with uncertainty (CI or credible interval) for each main result, not only p values.
- Exact test names, sidedness, test statistics, degrees of freedom, exact p values.
- Multiple-comparison handling. Missing-data handling. Exclusions with counts at each step (flow).
- Descriptive statistics of the sample (who or what was studied).
- Software and versions; code and data availability statement.

**Prediction / machine learning / NLP**
- Dataset sizes per split and per class; how splits were made; leakage controls.
- Number of runs/seeds and the spread (s.d. or CI) for every reported metric.
- Per-class metrics for imbalanced data; confusion matrix for classification; macro and weighted averages.
- Baseline results under the same protocol; ablations for each claimed component.
- Hyperparameters, tuning procedure, and which split was used for tuning; compute budget and hardware.
- Calibration (for probability outputs), threshold choice, and error analysis.
- Statistical comparison between the best model and the next best (bootstrap, McNemar, paired test).
- For LLM use: model name and version, date, prompts, temperature, and validation of LLM outputs against
  humans with agreement statistics.
- External or out-of-distribution validation if generalization is claimed.

**Annotation / labeling / coding**
- Codebook availability; annotator number and training; inter-annotator agreement with the statistic,
  sample size, and how disagreements were resolved; label distribution.

**Trials and clinical / epidemiological studies**
- Registration, primary outcome as pre-specified, randomization and blinding, flow diagram, baseline
  table, adverse events, confounder adjustment, sensitivity analyses.

**Surveys and human-subject studies**
- Ethics approval and consent statement; recruitment and response rate; instrument validity/reliability;
  demographics; compensation.

**Reviews and meta-analyses**
- Search strategy with dates and databases, PRISMA flow, inclusion criteria, risk-of-bias assessment,
  heterogeneity statistics, publication-bias assessment.

**Figures and tables** (cross-check with phase 6)
- Error bars defined, `n` per panel, statistical test named in the caption, units on every axis.

## Step 3: also look for

- A metric mentioned in the methods but never reported in the results (or the reverse).
- A comparison claimed in the text with no number behind it.
- A limitation the design obviously implies that the discussion does not mention.

## Output

`phases/04b-missing-reporting.json`: `coverage` in `checklist items` (total = items applicable to this
study type, checked = items you decided). `items`: `{"item", "guideline", "status": "present|absent|n/a",
"location"}`. One finding per absent item that matters, with a concrete fix ("Report the s.d. across the
five seeds for each model in Table 3").
