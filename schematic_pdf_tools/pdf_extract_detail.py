#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
原理图 PDF 单页完整文本提取（深挖层）

把某一页的全部文本标签/器件位号/网络名/注释完整定格，
用于"这一页到底有哪些网络、器件、注释"的深挖。

用法：
    python pdf_extract_detail.py --pdf <原理图.pdf> --page 17 [--out page17.txt]
"""
import argparse
import sys
import os

try:
    from pypdf import PdfReader
except Exception:
    sys.exit("pypdf 未安装，请先执行：pip install pypdf")


def main():
    ap = argparse.ArgumentParser(description="原理图单页全文提取")
    ap.add_argument("--pdf", required=True, help="原理图 PDF 绝对路径")
    ap.add_argument("--page", required=True, type=int, help="页码（从 1 开始）")
    ap.add_argument("--out", help="输出文件（省略则打印到终端）")
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        sys.exit(f"未找到 PDF：{args.pdf}")

    reader = PdfReader(args.pdf)
    t = reader.pages[args.page - 1].extract_text() or "(无文本，可能是图片型 PDF)"

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(t)
        print(f"written: {args.out}")
    else:
        print(t)


if __name__ == "__main__":
    main()
