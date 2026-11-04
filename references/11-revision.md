# Phase R: revision, annotated version and response to reviewers

Use only when the paper is a revision. All other phases run on the **revised** manuscript as usual. This
phase checks that the revision package is honest and complete: editors read the response letter first,
and a response that claims a change the manuscript does not contain, or quotes text that is not there,
damages trust more than the original problem.

Inputs: the revised manuscript, the response letter, ideally the annotated (tracked) version and the
previous version, and the reviewer/editor comments if they are not quoted in the response. Run:

```bash
$PY -I $SK/scripts/revision_tool.py --review $RV --revised <revised> --response <letter> \
    [--previous <old>] [--annotated <tracked>] [--comments <decision letter>]
```

`work/revision/auto.json` lists comment/response pairs (with parse quality), every quote in the responses
and whether it is in the revised manuscript, locations the responses cite, the real changes (with
`--previous`), changes no response mentions, changes the annotated version does not mark, and marked text
that is not in the revised manuscript. If parse quality is not `good`, pair comments and responses by
reading the letter yourself.

## Check every reviewer and editor comment

For each comment (`coverage.total` = number of comments, including editor comments from the decision letter):

1. **Responded?** A comment with no response, or a response that does not engage with it ("Thank you" only),
   is major.
2. **Response accurate?** Every change the response says was made exists in the revised manuscript, at
   the location given (page/line/section/table). Quote the manuscript text. A claimed change that is not
   there is critical (the editor will find it).
3. **Quotes exact?** Each quoted passage matches the revised text word for word (the script checks; you
   confirm and give the line). A misquote is major.
4. **Actually addressed?** Judge whether the change resolves the reviewer's point. Classify:
   `addressed`, `partially_addressed` (say what is left), `rebutted` (the authors disagree: is the
   argument supported by evidence in the paper or a checked source?), `not_addressed`, `promise_only`
   ("we will...", "in future work" for something the reviewer asked to be done now).
5. **New claims in the response** (new numbers, new analyses, new citations) are checked like the
   manuscript: numbers by code, citations against saved sources (run phase 1 and 2 on any new reference).
6. **Tone**: professional, no dismissiveness. Minor unless it could annoy the editor.

## Check the annotated version against the real changes

- Every real change (from the diff of previous and revised) is marked in the annotated version. Unmarked
  substantive changes are major: journals require all changes to be visible.
- Everything marked as added exists in the revised manuscript (and deleted text is absent from it).
- If the previous version was not provided, say that unmarked changes could not be checked.

## Check for unannounced changes

Every substantive change in the diff is either mentioned in the response or clearly minor (typo, format).
Substantive changes that no response mentions (new results, changed numbers, removed limitations, changed
conclusions) are major: reviewers notice them, and changed numbers need explaining.

## Output

`phases/R-revision.json`: `coverage.unit = "reviewer comments"`, items one per comment
`{"id", "reviewer", "comment", "response_summary", "verdict", "claimed_changes": [{"claim", "found", "line", "quote"}],
 "quotes_ok": true}`, plus findings (with `issue_key`) for every problem above, and info findings for
anything that could not be checked (no previous version, no annotated version, letter parse problems).
