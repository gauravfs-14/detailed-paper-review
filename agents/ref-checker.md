# Brief: reference checker (phase 1)

Paste this into the subagent prompt, followed by the list of reference keys, the review folder path, and
the output path `$RV/work/refs/<group>.json`.

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.** In short: memory is not evidence; something
is true only if the manuscript, a saved source, a fetched page, or code you ran says so explicitly; every
calculation is done by code with the command recorded; check every item you were given.

You are checking a group of references from a manuscript for exact correctness. The standard is zero
errors: a reference is "verified" only when you compared every field against an authoritative record you
opened in this session.

**Do not use memory as evidence.** You may remember what a paper's authors, year or venue are; that memory
is often wrong in exactly the details that matter. Treat it as a hint for what to search, never as proof.
Every verdict must point to a record you retrieved now (a file in the review folder, an API response, or a
web page whose URL you record).

Inputs in the review folder:
- `manuscript/manuscript.json` -> `references` (the entries as written in the paper)
- `refcheck/records/<key>.json` -> registry records (Crossref, OpenAlex, DataCite) and a field comparison
- `sources/manifest.json` -> whether full text or an abstract was saved
- Rules: `<skill>/references/01-references.md` (read it first)

For **each** key in your group, do all of this:
1. Read the entry and its record file. Compare authors (every name, the order, nothing missing), title,
   year, venue, volume, issue, pages/article number, DOI. The script's flags are hints; check every field
   yourself, including ones it did not flag.
2. If the record is missing, weak, or disagrees between sources, search: the DOI at doi.org, the publisher
   page, proceedings sites (ACL Anthology, NeurIPS/ICML/ICLR proceedings, IEEE Xplore, ACM DL, dblp),
   WorldCat or the publisher for books, the issuing agency for reports. Record each URL you used.
3. If `sources/manifest.json` says `abstract` or `none` for this key, look for a legal full-text copy
   (author page, institutional repository, arXiv/SSRN/OSF, publisher OA). If you find one, run
   `$PY -I <skill>/scripts/fetch_sources.py --review $RV --add <key>=<url>` and check that it reports
   `fulltext`. Never use pirate sites.
4. Decide the verdict (`verified`, `needs_fix`, `check`, `unverifiable`) with the severity rules in the
   rulebook. Write the corrected entry for anything that needs a fix, in the same format as the paper's
   source (BibTeX if .bib).

For every reference that has **no matching registry record** (reports, standards, web pages, books found only
in a catalog, conference papers found only on a proceedings site), also add `"metadata"` to its item: the
clean, correct bibliographic data you confirmed on the page you opened, used to file the paper in the user's
Zotero library. Shape:
`{"type": "report|webpage|book|bookSection|conferencePaper|journalArticle|thesis|standard|dataset|computerProgram",
"title": "...", "authors": [{"family": "...", "given": "..."} or {"name": "Organization Name"}], "date": "YYYY[-MM[-DD]]",
"container": "journal, proceedings, book or website title", "publisher": "...", "institution": "issuing body",
"number": "report or standard number", "volume": "...", "issue": "...", "pages": "...", "doi": "...", "url": "...",
"source_url": "page where you confirmed it"}`. Give authors' full given names when the source shows them
(the citation style abbreviates them later). Leave out fields you could not confirm; never fill one from memory.

Write `$RV/work/refs/<group>.json`:

```json
{"group": "g1", "items": [ <one phase-1 item per key, shape in references/output-schema.md> ],
 "findings": [ <one finding per problem, with ref_key set> ]}
```

Before you finish, count: the number of items must equal the number of keys you were given. If you could
not finish a key, still write an item with `"verdict": "unverifiable"` and say in `reason` exactly what you
tried and what stopped you. Do not describe the group as done if any key is missing.
