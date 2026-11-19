#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
原理图 PDF 关键词→页码定位器（导航层）

把几十/几百页的矢量原理图 PDF 变成"可检索、可按页定位"的纯文本，
回答"某某网络/GPIO/器件在哪一页"。

用法：
    python pdf_extract.py --pdf <原理图.pdf> [--kw 关键词1 关键词2 ...] [--config config/xxx.json]

参数优先级：--pdf > --config.json 里的 pdf_path；--kw > --config.json 里的 keywords。

依赖：pip install pypdf
"""
import argparse
import json
import sys
import os

try:
    from pypdf import PdfReader
except Exception:
    sys.exit("pypdf 未安装，请先执行：pip install pypdf")


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="原理图 PDF 关键词定位")
    ap.add_argument("--pdf", help="原理图 PDF 绝对路径")
    ap.add_argument("--config", help="产品线配置文件 json（含 pdf_path / keywords）")
    ap.add_argument("--kw", nargs="*", help="要检索的关键词（空格分隔，可多个）")
    ap.add_argument("--out", help="把命中结果写入文件（可选）")
    args = ap.parse_args()

    cfg = {}
    if args.config:
        cfg = load_config(args.config)

    pdf = args.pdf or cfg.get("pdf_path")
    if not pdf or not os.path.exists(pdf):
        sys.exit(f"未找到 PDF：{pdf}。请用 --pdf 或 --config 指定。")

    kws = args.kw or cfg.get("keywords") or []
    if not kws:
        kws = ["GPIO", "PWR", "LDO", "I2C", "ANT", "VDD", "EN", "RST", "INT"]

    reader = PdfReader(pdf)
    n = len(reader.pages)
    print(f"TOTAL_PAGES={n}")
    print(f"KEYWORDS={kws}")

    hits = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        tl = t.lower()
        found = [k for k in kws if k.lower() in tl]
        if found:
            hits.append((i + 1, found))
            print(f"PAGE {i+1}: {found}")

    print("\n=== HIT PAGE MAP（关键词 → 页码）===")
    for p, kw in hits:
        print(f"  page {p}: {kw}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(f"PDF={pdf}\nTOTAL_PAGES={n}\n")
            for p, kw in hits:
                f.write(f"page {p}: {kw}\n")
        print(f"\n命中结果已写入：{args.out}")


if __name__ == "__main__":
    main()
