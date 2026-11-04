# Phase 5: acronyms and abbreviations

Rule the paper must follow: every acronym is defined at its first use in the main text, defined once,
and used in its short form after that. The abstract counts separately: an acronym used in the abstract
is defined there, and defined again at first use in the main text (most journals require this). Acronyms
in figure and table captions should be defined in the caption or be already standard for the readership,
because captions are read on their own.

## Procedure

1. Read `work/acronyms_auto.json` (`text_checks.py acronyms`). For each candidate it lists definitions,
   uses with line numbers, and possible issues:
   `never_defined`, `used_before_definition`, `defined_more_than_once`, `defined_but_never_used_again`,
   `defined_only_in_abstract`, `long_form_repeated_after_definition`.
2. The script misses some things and over-reports others. A `section-auditor` agent per part
   (`review_tool.py plan-sections`) reads every sentence and records:
   - every acronym and abbreviation it sees (including lowercase ones like "w.r.t.", unit-like terms,
     dataset and method short names, and plural forms like "LLMs"),
   - every definition pattern: "long form (LF)", "LF (long form)", "LF, or long form", definitions inside
     footnotes, and definitions written in a table.
   Then the main agent merges the parts in document order and decides each acronym.
3. Decide for each acronym:
   - **Proper names are not acronyms to define**: BERT, RoBERTa, GPT-4, ImageNet, NASA, NVIDIA, IEEE are
     names. Define a name only if the target readership would not know it (say so as `info`).
   - **Universally known units and terms** (DNA, USA, GPU, CPU, PDF) do not need definition unless the
     venue requires it.
   - Everything else follows the rule above.
4. Check that the long form is correct and consistent: same expansion every time, correct initials
   ("term frequency-inverse document frequency (TF-IDF)"), not two acronyms for one thing (FP and FPR
   used interchangeably), not one acronym for two things.
5. Check acronyms that are used only once or twice: usually better written out (minor).
6. If the paper has an abbreviations list, every acronym in the text is in the list and vice versa.

## Severity

- Undefined acronym that a reader of the target venue would not know: major for key terms, minor otherwise.
- Used before defined; defined twice; long form repeated after definition; inconsistent expansion: minor.
- Same acronym for two different things, or a wrong expansion: major.

## Output

`phases/05-acronyms.json`: `coverage` in `acronyms` (total = acronyms found, checked = decided). `items`:
`{"acronym", "long_form", "defined_at", "first_used_at", "uses", "verdict": "ok|issue|name", "issues": [...]}`.
One finding per issue with the line of the first use and the line of the definition. In fix mode, add the
exact edit (define at first use, drop the second definition, replace repeated long forms).
