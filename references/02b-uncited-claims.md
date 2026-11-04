# Phase 2b: factual claims with no citation

Goal: every statement of fact about the world that the paper does not itself establish is backed by a
citation (or by the paper's own data, with a pointer to it). Phase 2 checks sentences that cite something;
this phase checks every sentence that cites nothing, so no claim escapes checking.

Input: `work/uncited_auto.json` (`claim_tools.py uncited`): every sentence without a citation, classed by
script as `candidate` (numbers, comparisons, generalisations, "studies show"), `own_work` (refers to this
paper's data, tables, methods) or `other`. The class is a hint. **Read every sentence in the file**, not only
the candidates; `coverage.total` must be at least `total_uncited_sentences`.

## Decide each sentence

| Verdict | Meaning | Severity if it is a problem |
|---|---|---|
| `own_result` | States a result of this paper; the table, figure, or computation that shows it exists. Give the location. | none (if the pointer is wrong, it is a phase 3b/4 issue) |
| `definition_or_method` | Defines a term or describes what the authors did. | none |
| `common_knowledge` | A reader in the field would not ask for a source (e.g. "Transformers are neural networks"). Be strict: numbers, trends, prevalence, causes and "studies show" are never common knowledge. | none |
| `needs_citation` | A factual claim about the world (statistic, trend, prior finding, cause, prevalence, policy, law) with no source. | major when it supports the motivation or a conclusion, minor otherwise |
| `citation_elsewhere` | The source is cited in the neighbouring sentence and clearly covers this one. Name the key. | none; but if that source was not checked for this sentence in phase 2, check it now against the saved text and record the quote |
| `opinion_or_hedge` | An interpretation clearly presented as the authors' view ("we argue", "this suggests"). | none, unless it is presented as fact (then `needs_citation`) |

For `needs_citation`, suggest what kind of source is needed and, when a saved source in `sources/text/`
explicitly supports the sentence, give the key and the exact quote (that is the fix). Never propose a
citation from memory: a suggested source must be one you opened and quoted in this session, with its
registry record (DOI) fetched.

## Output

`phases/02b-uncited-claims.json`: `coverage.unit = "sentences without a citation"`, items one per sentence
`{"sentence", "line", "text", "verdict", "pointer", "note"}`, findings for every `needs_citation` (with
`issue_key`, the sentence as `quote`, and the fix).
