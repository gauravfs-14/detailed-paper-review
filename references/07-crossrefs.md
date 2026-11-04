# Phase 7: cross-references

Rule: every figure, table, box, equation that is referred to, algorithm, appendix and supplementary item is
cited in the text at least once, at the place where the reader needs it, and first cited in numerical
order (Figure 1 before Figure 2). A display that is never mentioned is a finding (minor for supplementary
items, major for a main figure or table, because the reader does not know why it is there).

## Procedure

1. Read `work/crossrefs_auto.json` (`text_checks.py crossrefs`): every display with its number, mention
   count, first mention line, and issues (`never_referenced`, `first_mention_out_of_order`,
   `reference_to_unknown_label`, `no_label_so_cannot_be_referenced`, `mention_of_missing_display`).
   A mention inside the display's own caption does not count.
2. For LaTeX: also scan the compiled log or the `.aux` if available for `Reference ... undefined` and
   `??` in the PDF. For PDF/DOCX input, confirm each "Figure N" mention by reading the context, since the
   script matches text patterns.
3. Read each mention in context and judge whether it is **meaningful**: the sentence tells the reader what
   to look at or what the display shows ("Figure 3 shows that errors concentrate between ..."). A bare
   "(see Table 4)" at the end of an unrelated paragraph, or a first mention pages after the display, is a
   minor finding with a suggested sentence.
4. Check that the text describes the display correctly (the mentioned panel exists; "the left panel" is
   really on the left; the table column named in the text exists). Mismatches are major.
5. Section and appendix references resolve; supplementary items mentioned in the text exist in the
   supplement you were given (if not given, mark not assessable).
6. Equations: numbered equations that are never referred to can be unnumbered (info).

## Output

`phases/07-crossrefs.json`: `coverage` in `labels` (total = displays + referenced labels). `items`: one per
display `{"label", "type", "number", "mentions", "first_mention_line", "verdict"}`. One finding per issue.
