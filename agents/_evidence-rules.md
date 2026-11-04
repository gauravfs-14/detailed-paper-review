# Evidence rules (paste these at the top of EVERY subagent prompt, unchanged)

These rules apply to every agent in this review, whatever its task. Breaking them makes the review
worthless, because the user relies on it to catch exactly the errors a language model tends to make.

1. **Your memory is not evidence.** Do not treat anything as true because you remember it, however sure
   you feel: not what a paper says, not a paper's authors, year, venue or numbers, not a journal's rules,
   not a statistical fact about this dataset. Memory may suggest where to look; it never decides.
2. **Something is true only if one of these says so explicitly, and you opened it in this session:**
   - the manuscript itself (or its supplement, data, code, response letter), quoted with file and line;
   - a saved source file in `sources/` or a registry/publisher/agency page you fetched, quoted exactly
     with its page or URL;
   - the output of code you ran on the paper's own numbers or data (command and output recorded).
   If none of these says it, the answer is "cannot verify", not a guess.
3. **Every calculation is done by code.** Sums, percentages, differences, ratios, metrics, p-values,
   intervals, word counts, rounding checks: run `scripts/recompute_metrics.py` or a short Python command
   and record the exact command and its output as evidence (`kind: computation`). Never do arithmetic in
   your head and never write a computed number you did not get from code. A value that truly cannot be
   computed from the files goes in evidence with `kind: "estimate"`, says why, and lowers the finding's
   confidence; it is never labelled `computation`.
4. **Quote, do not paraphrase, when you cite evidence.** Quotes are checked by script against the saved
   files; a paraphrased or remembered quote is treated as no evidence.
5. **Check everything you were given.** Do not sample, skim or stop early. Count your outputs against your
   inputs before you finish (every reference, every sentence, every number, every item). If something
   cannot be checked, list it with the reason; never leave it out silently.
6. **Real locations only.** Use the file and line from `manuscript.json` or the file itself. Never invent a
   page, line, table number, URL or quote.
7. **Say what you did not do.** End with counts: checked, problems found, could not check (and why).
8. **Notice stray text as you read.** This is not a separate pass and not a phrase list: no list can
   predict what slips into a manuscript, so use judgment on everything you read for your own task
   (sentences, captions, footnotes, table cells, headings, front and back matter). For each piece ask:
   *would this text appear, written this way, in the finished paper a journal reader sees?* If not, it is
   stray. It usually comes from the tools and steps used to write the paper, for example:
   - text from an AI chat: a reply to the writer rather than prose for the reader, an offer, an apology,
     a summary of what was changed, a fill-in-the-blank bracket;
   - text from revising: notes about versions, uploads, reviewers or changes, response-letter wording,
     before/after pairs, change or highlight markup left in;
   - text from notes or documentation: to-dos, placeholders, instructions, notes to co-authors, file names,
     formatting from another tool (Markdown, code), outline or slide-style fragments.
   These are illustrations of the kind of thing to notice, not the definition. Anything else that does not
   belong in the finished paper counts too. Add a finding (category `stray-text`, severity major; critical
   in the title or abstract) quoting the text exactly with file and line, and say why it does not belong.
   Use `issue_key` `stray-ai-text`, `stray-revision-text` or `stray-doc-text` (or `stray-text` for anything
   else) so findings from different agents merge. Legitimate uses are not stray (a paper about LLMs quoting
   model output, a methods section describing reviewer annotation); if unsure, flag it as a question.
