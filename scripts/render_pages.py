#!/usr/bin/env python3
"""Render PDF pages (or a PDF figure) to PNG so agents can look at them with the Read tool.

  python render_pages.py paper.pdf --out $RV/work/pages [--pages 1-3,7] [--dpi 110]
  python render_pages.py figure.pdf --out $RV/work/figs --dpi 300      # judge a figure at print size

Prints one PNG path per page. Uses PyMuPDF from setup_env.sh, so no poppler is needed.
"""
import argparse
import os


def page_list(spec, n):
    if not spec:
        return list(range(1, n + 1))
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return [p for p in out if 1 <= p <= n]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages")
    ap.add_argument("--dpi", type=int, default=110)
    a = ap.parse_args()
    import pymupdf
    os.makedirs(a.out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.pdf))[0]
    with pymupdf.open(a.pdf) as doc:
        for p in page_list(a.pages, len(doc)):
            path = os.path.join(a.out, f"{stem}-p{p}.png")
            doc[p - 1].get_pixmap(dpi=a.dpi).save(path)
            print(path)


if __name__ == "__main__":
    main()
