#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
原理图 PDF 指定页批量全文提取（研究层）

用法：
    python pdf_extract_pages.py --pdf <原理图.pdf> --pages 3,5,6,11,17 [--out output.txt]

页码从 1 开始。若省略 --pages，则从 config 里读 pages 字段。
"""
import argparse
import json
import sys
import os

try:
    from pypdf import PdfReader
except Exception:
    sys.exit("pypdf 未安装，请先执行：pip install pypdf")


def main():
    ap = argparse.ArgumentParser(description="原理图指定页全文提取")
    ap.add_argument("--pdf", help="原理图 PDF 绝对路径")
    ap.add_argument("--config", help="产品线配置文件 json")
    ap.add_argument("--pages", help="页码列表，逗号分隔，如 3,5,6,11,17")
    ap.add_argument("--out", help="输出文件（省略则打印到终端）")
    args = ap.parse_args()

    cfg = {}
    if args.config:
        cfg = json.load(open(args.config, encoding="utf-8"))

    pdf = args.pdf or cfg.get("pdf_path")
    if not pdf or not os.path.exists(pdf):
        sys.exit(f"未找到 PDF：{pdf}")

    if args.pages:
        pages = [int(x.strip()) for x in args.pages.split(",") if x.strip()]
    elif cfg.get("pages"):
        pages = cfg["pages"]
    else:
        sys.exit("请用 --pages 指定页码（逗号分隔），或在 config 里填 pages 字段。")

    reader = PdfReader(pdf)
    out_lines = []
    for p in pages:
        try:
            t = reader.pages[p - 1].extract_text() or ""
        except Exception as e:
            t = f"(extract error: {e})"
        header = f"\n{'='*78}\nPAGE {p}\n{'='*78}\n"
        out_lines.append(header + t + "\n")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("\n".join(out_lines))
        print(f"written: {args.out}")
    else:
        print("\n".join(out_lines))


if __name__ == "__main__":
    main()
