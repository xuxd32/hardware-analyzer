#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
is_power_net 电源网络识别（收紧后）强测试
========================================
覆盖：
1. 真电源主干 → True（PWR_IN/VDD/VBAT/V3V3/VIN 且不以信号后缀结尾）
2. 使能/复位/按键后缀 → False（*_PWR_EN / *_RST / *_KEY）
3. 非电源 → False（GND/SIG/I2C 等）
4. 边界（大小写、空串）

运行：python test_is_power_net.py  （失败即 exit(1)）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from main import is_power_net

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {detail}")


print("=" * 70)
print("is_power_net 电源网络识别 强测试")
print("=" * 70)

# 1. 真电源主干
print("\n【1. 真电源主干 → True】")
for n in ["PWR_IN", "PWR_IN0", "PWR_IN1", "VDD_3V3", "SC_VBAT_V38",
          "AV_PWR2_V50", "CAR_PWR_IN", "SC_SIM1_VDD", "VCC_5V", "VBAT"]:
    check(f"{n} → True", is_power_net(n) is True, f"实际={is_power_net(n)}")

# 2. 使能/复位/按键后缀 → False
print("\n【2. 使能/复位/按键后缀 → False】")
for n in ["ST32_GSM_PWR_EN", "SC_CMA_PWR1_EN", "PWR_KEY_RST",
          "SC_PWR_KEY", "ST32_BAT_PWR_EN", "ST32_USBHUB_PWR_EN"]:
    check(f"{n} → False", is_power_net(n) is False, f"实际={is_power_net(n)}")

# 3. 非电源 → False
print("\n【3. 非电源 → False】")
for n in ["GND", "SIG_A", "I2C_SDA", "UART_TX", "CLK_32K", "RESET"]:
    check(f"{n} → False", is_power_net(n) is False, f"实际={is_power_net(n)}")

# 4. 边界
print("\n【4. 边界】")
check("小写 vdd_3v3 → True", is_power_net("vdd_3v3") is True)
check("混合 pWr_In → True", is_power_net("pWr_In") is True)
check("空串 → False", is_power_net("") is False)
check("None → False", is_power_net(None) is False)

# 反例：确保不会把真电源误伤（含关键词但后缀不是信号）
check("VDD_3V3_EN 确实应排除", is_power_net("VDD_3V3_EN") is False)  # EN 是使能，确应排除

# ========== 总结 ==========
print()
print("=" * 70)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 70)
if failed:
    print("❌ 存在失败测试")
    sys.exit(1)
else:
    print("✅ is_power_net 电源网络识别 全部通过")
    sys.exit(0)
