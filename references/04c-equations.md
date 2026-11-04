# Phase 4c: equations

Goal: every equation is correct, every symbol is defined, the notation is consistent, the equation matches
the source it is taken from, and it matches how the reported numbers were actually computed.

Input: `work/equations.json` (`claim_tools.py equations`): display equations and inline formulas with line,
label and surrounding text. For PDF/DOCX input also look at the rendered pages (`render_pages.py`), because
text extraction misses equations. `coverage.total` is at least the number of listed equations.

## Check each equation

1. **Symbols**: every symbol is defined before or right after first use; one symbol never means two things;
   indices and dimensions are consistent (sums run over defined sets, matrix shapes agree).
2. **Correctness**: the expression is mathematically right for what the text says it computes (e.g. F1 is
   the harmonic mean of precision and recall; a softmax normalises over all classes; an IDF has the stated
   smoothing). Check it with code: implement the formula in a few lines of Python and evaluate it on a small
   example or on the paper's own numbers, recording the command and output.
3. **Matches the source**: if the text attributes the formula to a citation, find it in the saved source
   text and compare term by term (quote the source). Variants (e.g. macro-F1 as the mean of per-class F1
   versus F1 of macro precision and recall) must be stated, because they give different numbers.
4. **Matches the numbers**: when the paper reports values computed with this formula, recompute at least
   one from the paper's own counts with code and compare (e.g. the confusion matrix with the stated F1
   definition). A mismatch means either the formula or the number is wrong.
5. **Presentation**: numbered only if referred to; punctuation and definitions follow the equation
   consistently; units shown where needed.

Severity: wrong formula that changes results or contradicts the numbers is critical; undefined or
inconsistent symbols in a formula the results depend on are major; presentation is minor.

## Output

`phases/04c-equations.json`: `coverage.unit = "equations"`, items
`{"line", "label", "latex", "checks": {...}, "command": "...", "verdict"}`, findings with `issue_key`.
