# Brief: fixes (fix mode only, editable source)

Inputs: every `$RV/phases/*.json` finding marked `fixable` or carrying a `fix`, `$RV/phases/01-references.json`
(`corrected_entry` for references), the manuscript source files named in `$RV/review.json`, and the
`fixes.json` rules in `<skill>/references/output-schema.md`. Output: `$RV/fixes.json`.

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.**

Turn each finding the evidence supports into exact find/replace pairs, as `SKILL.md` "Fix mode" describes:
registry fields, wording the source supports, numbers recomputed by code. Things that need the author's
data or judgment are left out (they stay as findings). Open each source file and copy `find` exactly; it
must occur once in the file. In `.tex` files escape `\%`, `\&`, `\#`, `\_` and keep braces balanced. Use the
finding's id as the fix id, one fix per change.
