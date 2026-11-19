#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
原理图 PDF 定向网络/GPIO 提取（取证层）

从指定页（或全本）逐行过滤含 GPIO/电源/使能/开关等关键词的行，
用于回答"某个 GPIO 到底管了哪些电源网络和控制信号"，以及复用冲突排查。

用法：
    python pdf_extract_network.py --pdf <原理图.pdf> --pages 11,17 [--pattern 'GPIO\d+|VBAT|PWR|EN']
    python pdf_extract_network.py --pdf <原理图.pdf> --pages 11,17 --config config/xxx.json

若省略 --pattern，则用内置默认正则（GPIO / 电源 / 使能 / 中断 / 开关）。
"""
import argparse
import json
import re
import sys
import os

try:
    from pypdf import PdfReader
except Exception:
    sys.exit("pypdf 未安装，请先执行：pip install pypdf")

DEFAULT_PATTERN = (
    r"(GPIO\d+|VBAT[\w_]*|VDD[\w_]*|VCC[\w_]*|PWR|POWER|电源|"
    r"PWR_EN|_EN\b|ENABLE|使能|RST|INT|EINT|CTL|开关|SEL_[LH])"
)


def main():
    ap = argparse.ArgumentParser(description="原理图网络/GPIO 定向过滤")
    ap.add_argument("--pdf", help="原理图 PDF 绝对路径")
    ap.add_argument("--config", help="产品线配置文件 json")
    ap.add_argument("--pages", help="页码列表，逗号分隔；省略则扫全本")
    ap.add_argument("--pattern", help="自定义正则（用于过滤行）")
    ap.add_argument("--out", help="输出文件（省略则打印到终端）")
    args = ap.parse_args()

    cfg = {}
    if args.config:
        cfg = json.load(open(args.config, encoding="utf-8"))

    pdf = args.pdf or cfg.get("pdf_path")
    if not pdf or not os.path.exists(pdf):
        sys.exit(f"未找到 PDF：{pdf}")

    pat = args.pattern or cfg.get("network_pattern") or DEFAULT_PATTERN
    rx = re.compile(pat, re.IGNORECASE)

    reader = PdfReader(pdf)
    if args.pages:
        pages = [int(x.strip()) for x in args.pages.split(",") if x.strip()]
    else:
        pages = list(range(1, len(reader.pages) + 1))

    out_lines = []
    for p in pages:
        try:
            t = reader.pages[p - 1].extract_text() or ""
        except Exception:
            t = ""
        matched = [line for line in t.splitlines() if rx.search(line)]
        if matched:
            out_lines.append(f"\n{'='*80}")
            out_lines.append(f"PAGE {p} — 关键网络/GPIO 上下文")
            out_lines.append("="*80)
            out_lines.extend(matched)

    content = "\n".join(out_lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"written: {args.out}")
    else:
        print(content)


if __name__ == "__main__":
    main()
