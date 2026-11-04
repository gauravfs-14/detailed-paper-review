# Phase 2c: literature coverage and recency

Goal: find relevant work the paper does not cite (especially recent work and work that a reviewer in the
field will expect), and references that are too old for the claims they support. A paper that misses the
closest prior work loses on novelty; one that cites only old work for "recent" claims loses credibility.

This phase depends on searching, so the evidence rules matter most here: **a paper may be named as missing
only if you fetched its registry record in this session** (DOI or OpenAlex/Semantic Scholar id, title,
authors, year, venue) and read its abstract. Never suggest a paper from memory, and never invent one.

## Procedure

1. Read the abstract, introduction and related-work section. Write 4 to 8 search queries that cover the
   paper's topic, method, data and application (e.g. "news framing traffic crashes", "transformer frame
   classification news", "LLM annotation validation").
2. Run `$PY -I <skill>/scripts/lit_search.py --review $RV --query "..." --query "..."`. It returns, per
   query, the most relevant works overall and from the last 4 years, each marked `already_cited`, with
   abstracts, plus an age profile of the reference list.
   OpenAlex indexes recent conference papers (ACL, NeurIPS, ICLR, CHI...) incompletely. For fields that
   publish at conferences, also search Semantic Scholar
   (`https://api.semanticscholar.org/graph/v1/paper/search?query=...&fields=title,year,venue,externalIds,abstract`)
   and the main proceedings sites, and say in `summary` which sources you searched.
3. For each candidate not already cited, read its abstract and decide:
   - `should_cite`: directly addresses the same question, method or data; a reviewer would ask why it is
     missing. Major if it challenges the paper's novelty claim or reports a conflicting result, minor
     otherwise.
   - `could_cite`: related and useful, not essential. Info.
   - `not_relevant`.
   Quote the part of its abstract that makes it relevant.
4. Novelty: compare each "first", "novel" or "no prior work" claim in the manuscript with the candidates.
   If a fetched record shows the same thing was done before, that is a major finding with the record as
   evidence.
5. Recency: use the age profile. Flag sentences that say "recent", "state of the art" or "current" but cite
   only works older than about 5 years (field-dependent; say which threshold you used and why). Flag a
   reference list where few works are from the last 5 years if the field moves fast.
6. Superseded or retracted: a cited preprint or older version with a newer published or updated version,
   and any retracted candidate (`is_retracted`).

## Output

`phases/02c-literature.json`: `coverage.unit = "candidate works"` (total = all candidates returned, each
decided), items `{"title", "doi", "year", "query", "verdict", "reason", "quote"}`, findings for
`should_cite`, novelty conflicts and recency problems. Include the queries you ran in `summary` so the user
can judge the search.
