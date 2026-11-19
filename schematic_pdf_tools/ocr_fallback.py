#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片型/扫描版原理图 PDF 的 OCR 兜底脚本

当 pypdf 提取不到文本（TOTAL_PAGES 正常但命中为空）时，说明是扫描件/图片型 PDF，
需要用 OCR 方案。本脚本调用一个本地 OCR HTTP 服务（可选），或提示安装 OCR 库。

两种用法：
1) 有 OCR HTTP 服务（如原 fast_server.py，监听 127.0.0.1:8999）时：
       python ocr_fallback.py --pdf <原理图.pdf> --server http://127.0.0.1:8999
2) 本地 OCR（需要 paddlex / rapidocr，一次性安装）：
       pip install rapidocr-onnxruntime
       python ocr_fallback.py --pdf <原理图.pdf> --local

注意：OCR 只能得到"图上文字"，同样得不到走线拓扑；且版面识别不如矢量文本可靠。
"""
import argparse
import json
import os
import sys
import urllib.request


def ocr_local(pdf_path):
    """用本地 rapidocr 对 PDF 逐页渲染识别（需先 pip install rapidocr-onnxruntime pymupdf）。"""
    try:
        import fitz  # pymupdf
        from rapidocr_onnxruntime import RapidOCR
    except Exception as e:
        sys.exit(f"本地 OCR 依赖缺失：{e}\n请执行：pip install rapidocr-onnxruntime pymupdf")

    ocr = RapidOCR()
    doc = fitz.open(pdf_path)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        # rapidocr 直接吃 ndarray；这里走简易路径：写临时 png 后识别
        tmp = f"_ocr_page_{i+1}.png"
        pix.save(tmp)
        result, _ = ocr(tmp)
        os.remove(tmp)
        print(f"\n{'='*78}\nPAGE {i+1} (OCR)\n{'='*78}")
        if result:
            for box, text, score in result:
                print(text)
        else:
            print("(本页未识别到文字)")


def ocr_server(pdf_path, base):
    """调用 OCR HTTP 服务（POST multipart file 到 /ocr）。"""
    import io
    boundary = "----ocrboundary"
    with open(pdf_path, "rb") as f:
        data = f.read()

    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{os.path.basename(pdf_path)}\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{base}/ocr",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    print(f"总页数: {result.get('total_pages')}")
    print(result.get("ocr_result", ""))


def main():
    ap = argparse.ArgumentParser(description="图片型原理图 PDF OCR 兜底")
    ap.add_argument("--pdf", required=True, help="原理图 PDF 路径")
    ap.add_argument("--local", action="store_true", help="用本地 OCR（rapidocr）")
    ap.add_argument("--server", default="http://127.0.0.1:8999", help="OCR HTTP 服务地址")
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        sys.exit(f"未找到 PDF：{args.pdf}")

    if args.local:
        ocr_local(args.pdf)
    else:
        ocr_server(args.pdf, args.server)


if __name__ == "__main__":
    main()
