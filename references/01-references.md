# Phase 1: reference check

Goal: every entry in the reference list is a real work, every field (authors and their order, title, year,
venue, volume, issue, pages or article number, DOI) matches an authoritative record, nothing is cited that
is missing from the list, nothing in the list is uncited (unless the venue allows it), and the source text
of every cited work is saved for phase 2.

The standard is zero errors. A reference that "looks right" is not verified; a reference is verified when
its fields were compared against a record you retrieved in this session.

## Procedure

1. **Mechanical pass** (`verify_refs.py`). For each entry:
   - DOI present: resolve it at Crossref first (cheapest, catches the most common error). HTTP 404 means the
     DOI is wrong. A DOI that resolves to a different title means the DOI belongs to another paper. In real
     audits most reference errors are DOI errors, so never skip this.
   - No DOI or wrong DOI: bibliographic search at Crossref (title + first author), then OpenAlex.
   - DataCite for Zenodo, arXiv and dataset DOIs. OpenAlex also gives retraction status and OA locations.
   - Output: `refcheck/auto_refs.json` and one raw record file per reference in `refcheck/records/`.
2. **Source download** (`fetch_sources.py`): user's own PDFs first, then OpenAlex OA locations, Semantic
   Scholar `openAccessPdf`, arXiv, Europe PMC, then the entry's own URL when it is the document itself
   (government reports, standards, web pages). Every PDF is validated: real `%PDF`, and the title words
   appear on its first pages. Failures go to `sources/_quarantine/`, never into evidence.
   - `auto_status: lookup_failed` means a registry could not be asked (rate limit or outage). It is **not**
     "not found" and **not** checked: rerun `verify_refs.py` later (or set `OPENALEX_API_KEY` /
     `OPENALEX_MAILTO`), and in the meantime the agent checks that entry by hand (publisher page, Crossref
     search, proceedings site). Never report such a reference as verified from the script alone.
3. **Adjudication** by `ref-checker` agents (10 to 15 references each, in parallel). For every entry:
   - Read `refcheck/records/<key>.json`. Compare every field yourself; the script's flags are hints only.
   - For entries the script could not match (`auto_status: manual`), search: publisher site, Google
     Scholar/Semantic Scholar via web search, the issuing agency's site for reports, WorldCat or the
     publisher's catalog for books, the conference's proceedings page (ACL Anthology, NeurIPS proceedings,
     IEEE Xplore, ACM DL, dblp) for conference papers. Record the URL you used.
   - For entries with `kind` abstract or none in `sources/manifest.json`: search for a legal full text
     (author's page, institutional repository, arXiv/SSRN/OSF version, publisher OA page). If found, run
     `fetch_sources.py --review $RV --add key=<url>`, which applies the same validation.
   - Decide the verdict and write problems, a corrected entry (BibTeX if the source is .bib, otherwise the
     corrected reference text in the paper's style), and evidence.
4. **List-level checks** (main agent):
   - Cited keys missing from the list, and list entries never cited (from `extract_manuscript.py` output).
   - Duplicates: two entries for the same work (same DOI, or same title and first author).
   - Preprint cited when a peer-reviewed version exists (Crossref relation `is-preprint-of`, or the same
     title on a later journal or proceedings record). Recommend the published version.
   - Retracted or corrected works (OpenAlex `is_retracted`, Crossref `update-to`). Always critical.
   - Style consistency of the list (author format, journal abbreviation vs full name, DOI format, title case)
     against the target venue's style, or internal consistency if no venue was given.
   - Very old or very new references only when relevant (for example, a "recent work" sentence citing 2009).

## Field rules and severities

| Check | Severity | Notes |
|---|---|---|
| DOI does not resolve | critical | Common typo: one digit off. Search by title to find the right DOI. |
| DOI resolves to another work | critical | Compare title and first author of the resolved record. |
| First author differs, or author invented | critical | Typical of AI-generated references. |
| Author missing (entry has fewer authors than record) | critical | Common when only the first 3 or 4 of 5+ authors were typed. `and others` in BibTeX is acceptable only if the venue style truncates. |
| Author order differs | critical | Use the publisher's order. |
| Title core words differ | critical | Case and punctuation differences are info only. |
| Pages differ by 5 or more, or article number wrong | critical | Watch letters read as digits: T/7, l/1, O/0 in article numbers. |
| Volume wrong | critical | |
| Year differs by more than one | critical | |
| Year differs by one | major | Usually online year vs volume year. Cite the volume (issue) year; if no volume yet, the online year. |
| Early Access record changed (volume/pages/year now final) | major | Use the current Crossref values. |
| Issue missing or wrong | major/minor | Missing is minor; wrong is major. |
| Pages differ by 4 or fewer | major | |
| Venue name differs | major if it is a different venue; info if abbreviation vs full name | arXiv record vs cited conference: confirm the proceedings version and its pages. |
| Middle initial or diacritic missing | minor | `Brommelstroet` vs `Brömmelstroet` is minor; a different surname is critical. |
| Title case, journal abbreviation, `and` vs `&` | info | Report once as a style finding, not per entry. |

Things that are **not** errors, so do not flag them as such:
- Old IEEE DOIs that Crossref does not return (pre-2000): confirm on IEEE Xplore instead.
- Chinese-language DOIs not in Crossref: confirm on CNKI or Wanfang.
- Spanish or Portuguese double surnames in different valid forms.
- A corporate author written in braces (`{National Highway Traffic Safety Administration}`).
- IEE before 2006 vs IET after (same institution, cite the historical name).

## Reports, standards, web pages, books, theses, datasets, software

- Reports and standards: confirm on the issuing body's site that the document exists with this title,
  report number, year, and issuing organization. Save the PDF via `--add` when it is public.
- Web pages: the URL loads and shows the cited content; record an access date if the style needs one.
- Books: publisher catalog or WorldCat for title, edition, publisher, year, ISBN. Note the edition.
- Theses: the university repository or ProQuest.
- Datasets and software: DataCite/Zenodo/GitHub release with version and DOI. A dataset or package cited
  without a version is a minor finding.
- `unverifiable` only after all of the above failed; say what was tried in `reason`.

## Output

`phases/01-references.json` with one item for **every** reference (see `output-schema.md`) and one finding
per problem. `coverage` is recomputed by the dashboard from the reference list, so a missing item shows as
"not finished". In fix mode, also add each corrected field to `fixes.json`.
