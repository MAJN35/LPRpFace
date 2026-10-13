#!/usr/bin/env python3
"""Markdown tables comparing plate-reading accuracy of two evaluations (tools/eval_reader.py --json-out files).
    python3 tools/accuracy_table.py docs/m3_accuracy_v2_pad0.json docs/m3_accuracy_v1_pad0.json --names v2 v1
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--names", nargs=2, default=["A", "B"])
    a = ap.parse_args()
    A, B = (json.load(open(p))["stats"] for p in (a.a, a.b))
    na, nb = a.names

    def cell(s, k):
        c, t = s.get(k, (0, 0))
        return (100.0 * c / t if t else None), c, t

    for split in ("real", "synthetic"):
        print(f"\n**{split.capitalize()} images** (exact string; standard8 = 8-character standard-format plates)\n")
        print(f"| Group / plate type | Plates | {na} | {nb} | {nb} − {na} |")
        print("|---|---|---|---|---|")
        keys = sorted(k for k in set(A) | set(B) if k.startswith(split + "|") and "|detected|" not in k)
        order = [k for k in keys if "|all|" in k] + [k for k in keys if "|group|" in k] + [k for k in keys if "|type|" in k]
        for k in order:
            pa, ca, ta = cell(A, k)
            pb, cb, tb = cell(B, k)
            label = " / ".join(k.split("|")[1:]).replace("all / ", "all: ").replace("group / ", "").replace("type / ", "type ")
            d = f"{pb - pa:+.1f}" if pa is not None and pb is not None else ""
            fa = f"{pa:.1f} % ({ca})" if pa is not None else "–"
            fb = f"{pb:.1f} % ({cb})" if pb is not None else "–"
            print(f"| {label} | {max(ta, tb)} | {fa} | {fb} | {d} |")


if __name__ == "__main__":
    main()
