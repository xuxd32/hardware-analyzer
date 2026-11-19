#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试netlist集成功能
"""

import sys
import os

# 添加src目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# 创建测试netlist文件
test_kicad = """(export (version D)
  (design
    (source test.kicad_sch)
    (date "2026-08-27")
    (tool "Eeschema 7.0"))
  (components
    (comp (ref U1)
      (value STM32F103C8T6)
      (footprint QFP-48))
    (comp (ref U2)
      (value AMS1117-3.3)
      (footprint SOT-223))
    (comp (ref C1)
      (value 100nF)
      (footprint 0402))
    (comp (ref C2)
      (value 100nF)
      (footprint 0402))
    (comp (ref C3)
      (value 10uF)
      (footprint 0805))
    (comp (ref R1)
      (value 10K)
      (footprint 0402)))
  (libparts)
  (nets
    (net (code 1) (name VCC)
      (node (ref U1) (pin 1))
      (node (ref C1) (pin 1))
      (node (ref C2) (pin 1)))
    (net (code 2) (name V3V3)
      (node (ref U2) (pin 3))
      (node (ref U1) (pin 24))
      (node (ref C3) (pin 1)))
    (net (code 3) (name GND)
      (node (ref U1) (pin 48))
      (node (ref U2) (pin 1))
      (node (ref C1) (pin 2))
      (node (ref C2) (pin 2))
      (node (ref C3) (pin 2)))
    (net (code 4) (name USB_DP)
      (node (ref U1) (pin 33)))
    (net (code 5) (name USB_DN)
      (node (ref U1) (pin 32)))))
"""

print("创建测试netlist文件...")
with open("test_netlist.net", "w", encoding="utf-8") as f:
    f.write(test_kicad)

print("✅ 测试文件创建成功: test_netlist.net")
print("\n运行测试:")
print("-" * 60)

# 测试仅netlist模式
os.system("python src/main.py --netlist test_netlist.net")

print("\n" + "=" * 60)
print("测试完成！")
print("=" * 60)
