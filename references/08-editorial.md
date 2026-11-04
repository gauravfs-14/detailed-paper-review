# Phase 8: editorial check (what an editor does before sending a paper to referees)

An editor's desk check decides whether the paper goes to review or comes straight back. It is about
completeness, fit, and whether the paper reads as finished. Use the target venue's author guidelines when
the user named one (look them up on the venue's site and cite the page); otherwise apply general practice
and say so.

## Checklist

Fit and framing
- Title: specific, accurate, no unexplained abbreviations, not overclaiming. Within the venue's length.
- Abstract: states the problem, what was done, the main quantitative results, and the main limitation;
  within the word limit; no citations or undefined acronyms (unless the venue allows); numbers match the
  body.
- Introduction ends with a clear statement of the question and contributions; contributions are each
  supported in the results.
- Scope matches the venue (state the venue's aims if checked).

Structure and length
- Required sections present and in the venue's order; word count, page count, figure/table limits,
  reference limits; supplementary material referenced and organized.
- Paragraphs with one main point each; no section that only repeats another.

Required statements (each one present or not, with location)
- Data availability; code availability; ethics approval and consent (human or animal data); funding;
  conflicts of interest; author contributions (CRediT if required); acknowledgments; use of generative AI
  in writing or analysis (many venues now require disclosure); preregistration or trial registration if
  applicable; permissions for reproduced figures.

Language and presentation
- Grammar, spelling, punctuation, and clarity. Report patterns, not every comma: give each type of problem
  once with 2 to 3 examples and locations, plus any error that changes meaning (always report those).
- Overclaiming words ("prove", "first", "novel", "significant" in a non-statistical sense, "always") checked
  against the evidence.
- Hedging that is so heavy it hides the result.
- Tense: methods and results in past tense, established facts in present; consistent voice.
- Reference style consistent and matching the venue; in-text citation format consistent.
- Formatting: heading levels, list styles, equation formatting, units with a space (5 mm), non-breaking
  spaces before references, consistent number format.
- Anonymization for double-blind venues (author names, self-citations written in the first person,
  acknowledgments, file metadata, repository links).
- Leftovers: TODO, XXX, ??, comments, tracked changes, placeholder text, broken links, "[citation needed]".
- Stray text (rule 8 in `agents/_evidence-rules.md`): text that would not appear in the finished paper,
  such as AI-chat replies, revision notes, response-letter wording, placeholders or notes to co-authors.
  There is no script for this, because no pattern list can predict what slips in. Every agent notices it
  while doing its own task; here, the editorial readers judge every sentence for it explicitly. Also open
  the source file itself for what extraction may hide: Word comments, tracked changes and highlighting;
  LaTeX change or highlight commands outside comments.

## Splitting the work

Use `section-auditor` agents per part for language and presentation (they must read every sentence).
The main agent does fit, structure, length, required statements and anonymization, which need the whole
paper.

## Output

`phases/08-editorial.json`: `coverage` in `sections` (all parts read) and the checklist in `items`
(including one item `"Stray text"`: `ok` only after every part was read for it, otherwise `issue` with the
count)
`{"item", "status": "ok|missing|issue|n/a", "location", "note"}`. Findings for every missing statement
and every issue pattern. In fix mode, language fixes go into `fixes.json` as exact find/replace pairs;
missing statements are reported for the author to write (do not invent ethics approvals, funding, or
author contributions).
