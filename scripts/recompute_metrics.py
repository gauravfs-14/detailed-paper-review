#!/usr/bin/env python3
"""Recompute reported numbers from what the paper itself gives. Stdlib only.

Never estimate these by eye: run the command and paste its output into the phase 4 evidence.

  cm      confusion matrix -> accuracy, per-class precision/recall/F1/specificity/support,
          macro/weighted/micro F1, balanced accuracy, Cohen's kappa, MCC
          --matrix '[[50,3],[4,43]]' --labels pos,neg [--rows actual|predicted]
          [--reported '{"accuracy":0.93,"macro_f1":0.92,"recall.pos":0.94}']
  pvalue  p from a test statistic:  --test t|z|chi2|f|r --stat 2.31 --df 28 [--df2 3] [--tails 2]
  ci      interval for a proportion: --k 151 --n 183 [--level 0.95]  (Wilson and Clopper-Pearson)
  grim    can a mean of integer data with this n exist?  --mean 3.47 --n 21 [--items 1]
  pct     --k 1220 --n 25139   (percent with the decimals needed to match a report)
  sum     --values 12193,11119,1232,595 [--total 25139]  (do parts add up?)

Each command prints a JSON object, so agents can paste it as computation evidence.
--reported compares every reported value with the recomputed one at the reported precision.
"""
import argparse
import json
import math


# ------------------------------------------------------------------ special functions
def betacf(a, b, x):
    MAXIT, EPS, FPMIN = 300, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > FPMIN else FPMIN)
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > FPMIN else FPMIN)
        c = 1 + aa / c
        c = c if abs(c) > FPMIN else FPMIN
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > FPMIN else FPMIN)
        c = 1 + aa / c
        c = c if abs(c) > FPMIN else FPMIN
        de = d * c
        h *= de
        if abs(de - 1) < EPS:
            break
    return h


def betai(a, b, x):
    """Regularized incomplete beta I_x(a,b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * betacf(a, b, x) / a
    return 1 - bt * betacf(b, a, 1 - x) / b


def gammainc_upper(s, x):
    """Regularized upper incomplete gamma Q(s,x)."""
    if x <= 0:
        return 1.0
    if x < s + 1:
        term, total, n = 1 / s, 1 / s, 0
        while abs(term) > 1e-15 * abs(total) and n < 1000:
            n += 1
            term *= x / (s + n)
            total += term
        return 1 - total * math.exp(-x + s * math.log(x) - math.lgamma(s))
    b, c, d = x + 1 - s, 1e300, 1 / (x + 1 - s)
    h = d
    for i in range(1, 1000):
        an = -i * (i - s)
        b += 2
        d = an * d + b
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = b + an / c
        c = c if abs(c) > 1e-300 else 1e-300
        de = d * c
        h *= de
        if abs(de - 1) < 1e-15:
            break
    return math.exp(-x + s * math.log(x) - math.lgamma(s)) * h


def norm_sf(z):
    return 0.5 * math.erfc(z / math.sqrt(2))


def norm_ppf(p):
    lo, hi = -40.0, 40.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if 1 - norm_sf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def beta_ppf(q, a, b):
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if betai(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ------------------------------------------------------------------ commands
def decimals(v):
    s = repr(v)
    return len(s.split(".")[1]) if "." in s else 0


def compare_reported(computed, reported):
    rows = []
    for k, v in reported.items():
        if k not in computed:
            rows.append({"metric": k, "reported": v, "computed": None, "match": "unknown_metric"})
            continue
        c = computed[k]
        scale = 100 if (v > 1.0 and c <= 1.0) else 1  # reported as percent
        d = decimals(v)
        ok = round(c * scale, d) == round(v, d) or abs(c * scale - v) <= 0.5 * 10 ** (-d) + 1e-12
        rows.append({"metric": k, "reported": v, "computed": round(c * scale, max(d, 4)), "match": "yes" if ok else "NO"})
    return rows


def cmd_cm(a):
    m = json.loads(a.matrix)
    k = len(m)
    labels = a.labels.split(",") if a.labels else [str(i) for i in range(k)]
    if a.rows == "predicted":
        m = [list(r) for r in zip(*m)]
    n = sum(map(sum, m))
    tp = [m[i][i] for i in range(k)]
    act = [sum(m[i]) for i in range(k)]
    pred = [sum(m[r][i] for r in range(k)) for i in range(k)]
    out = {"n": n, "accuracy": sum(tp) / n}
    f1s, recs = [], []
    for i, lab in enumerate(labels):
        p = tp[i] / pred[i] if pred[i] else 0.0
        r = tp[i] / act[i] if act[i] else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        tn = n - act[i] - pred[i] + tp[i]
        spec = tn / (n - act[i]) if n - act[i] else 0.0
        out[f"precision.{lab}"], out[f"recall.{lab}"], out[f"f1.{lab}"] = p, r, f
        out[f"specificity.{lab}"], out[f"support.{lab}"] = spec, act[i]
        f1s.append(f)
        recs.append(r)
    out["macro_f1"] = sum(f1s) / k
    out["weighted_f1"] = sum(f * s for f, s in zip(f1s, act)) / n
    out["micro_f1"] = out["accuracy"]
    out["macro_precision"] = sum(out[f"precision.{l}"] for l in labels) / k
    out["macro_recall"] = sum(recs) / k
    out["balanced_accuracy"] = out["macro_recall"]
    pe = sum(act[i] * pred[i] for i in range(k)) / n ** 2
    out["cohen_kappa"] = (out["accuracy"] - pe) / (1 - pe) if pe != 1 else 0.0
    cov_xy = n * sum(tp) - sum(act[i] * pred[i] for i in range(k))
    den = math.sqrt((n ** 2 - sum(p ** 2 for p in pred)) * (n ** 2 - sum(t ** 2 for t in act)))
    out["mcc"] = cov_xy / den if den else 0.0
    res = {"command": "cm", "matrix_rows": "actual" if a.rows != "predicted" else "predicted (transposed)",
           "labels": labels, "computed": {kk: (round(v, 6) if isinstance(v, float) else v) for kk, v in out.items()}}
    if a.reported:
        res["comparison"] = compare_reported(out, json.loads(a.reported))
    print(json.dumps(res, indent=2))


def cmd_pvalue(a):
    t, s, df = a.test, a.stat, a.df
    if t == "z":
        p1 = norm_sf(abs(s))
    elif t == "t":
        p1 = 0.5 * betai(df / 2, 0.5, df / (df + s * s))
    elif t == "r":
        tt = s * math.sqrt(df / (1 - s * s))
        p1 = 0.5 * betai(df / 2, 0.5, df / (df + tt * tt))
    elif t == "chi2":
        p1 = gammainc_upper(df / 2, s / 2)
    elif t == "f":
        p1 = betai(a.df2 / 2, df / 2, a.df2 / (a.df2 + df * s))
    p = p1 if t in ("chi2", "f") else min(1.0, p1 * a.tails)
    print(json.dumps({"command": "pvalue", "test": t, "stat": s, "df": df, "df2": a.df2,
                      "tails": a.tails if t not in ("chi2", "f") else 1, "p": p, "p_display": f"{p:.3g}"}, indent=2))


def cmd_ci(a):
    k, n, lvl = a.k, a.n, a.level
    z = norm_ppf(1 - (1 - lvl) / 2)
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    lo_cp = 0.0 if k == 0 else beta_ppf((1 - lvl) / 2, k, n - k + 1)
    hi_cp = 1.0 if k == n else beta_ppf(1 - (1 - lvl) / 2, k + 1, n - k)
    wald = z * math.sqrt(ph * (1 - ph) / n)
    print(json.dumps({"command": "ci", "k": k, "n": n, "proportion": round(ph, 6), "level": lvl,
                      "wilson": [round(c - h, 4), round(c + h, 4)], "clopper_pearson": [round(lo_cp, 4), round(hi_cp, 4)],
                      "wald": [round(ph - wald, 4), round(ph + wald, 4)]}, indent=2))


def cmd_grim(a):
    d = decimals(a.mean)
    total = a.n * a.items
    lo = math.floor(a.mean * total)
    possible = [x / total for x in (lo - 1, lo, lo + 1, lo + 2)]
    ok = any(round(p, d) == round(a.mean, d) for p in possible)
    print(json.dumps({"command": "grim", "mean": a.mean, "n": a.n, "items": a.items, "consistent": ok,
                      "nearest_possible_means": [round(p, d + 2) for p in possible]}, indent=2))


def cmd_pct(a):
    v = 100 * a.k / a.n
    print(json.dumps({"command": "pct", "k": a.k, "n": a.n, "percent": v,
                      "rounded": {str(d): round(v, d) for d in range(0, 4)}}, indent=2))


def cmd_sum(a):
    vals = [float(x) for x in a.values.split(",")]
    s = sum(vals)
    res = {"command": "sum", "values": vals, "sum": s}
    if a.total is not None:
        res.update(total=a.total, difference=s - a.total, adds_up=abs(s - a.total) < 1e-9)
    print(json.dumps(res, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("cm")
    p.add_argument("--matrix", required=True)
    p.add_argument("--labels")
    p.add_argument("--rows", choices=["actual", "predicted"], default="actual")
    p.add_argument("--reported")
    p = sub.add_parser("pvalue")
    p.add_argument("--test", choices=["t", "z", "chi2", "f", "r"], required=True)
    p.add_argument("--stat", type=float, required=True)
    p.add_argument("--df", type=float, default=1)
    p.add_argument("--df2", type=float, default=1)
    p.add_argument("--tails", type=int, default=2)
    p = sub.add_parser("ci")
    p.add_argument("--k", type=int, required=True)
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--level", type=float, default=0.95)
    p = sub.add_parser("grim")
    p.add_argument("--mean", type=float, required=True)
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--items", type=int, default=1)
    p = sub.add_parser("pct")
    p.add_argument("--k", type=float, required=True)
    p.add_argument("--n", type=float, required=True)
    p = sub.add_parser("sum")
    p.add_argument("--values", required=True)
    p.add_argument("--total", type=float)
    a = ap.parse_args()
    {"cm": cmd_cm, "pvalue": cmd_pvalue, "ci": cmd_ci, "grim": cmd_grim, "pct": cmd_pct, "sum": cmd_sum}[a.cmd](a)


if __name__ == "__main__":
    main()
