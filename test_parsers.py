#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IPC-2581 和 Gerber 解析器验证测试（强测试：失败即 exit(1)）"""

import sys
import tempfile
import os

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


print("=" * 60)
print("IPC-2581 & Gerber 解析器验证")
print("=" * 60)

# 测试1: IPC-2581解析器导入
print("\n[测试1] IPC-2581解析器导入")
try:
    from src.ipc2581_parser import IPC2581Parser, parse_ipc2581
    check("IPC-2581 解析器导入", True)
except ImportError as e:
    check("IPC-2581 解析器导入", False, str(e))

# 测试2: Gerber解析器导入
print("\n[测试2] Gerber解析器导入")
try:
    from src.gerber_parser import GerberParser, parse_gerber_traces
    check("Gerber 解析器导入", True)
except ImportError as e:
    check("Gerber 解析器导入", False, str(e))

# 测试3: IPC-2581解析器结构
print("\n[测试3] IPC-2581解析器结构验证")
test_ipc_xml = """<?xml version="1.0" encoding="UTF-8"?>
<IPC-2581 version="C">
    <Bom>
        <Assembly>
            <Component refDes="U1" packageRef="QFN32" part="STM32F103">
                <Location x="10.0" y="20.0" layerRef="TOP"/>
            </Component>
        </Assembly>
    </Bom>
    <LogicalNets>
        <Net name="VCC">
            <PinRef componentRef="U1" pin="1"/>
        </Net>
    </LogicalNets>
</IPC-2581>
"""

with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
    f.write(test_ipc_xml)
    test_xml_path = f.name

try:
    result = parse_ipc2581(test_xml_path)
    if 'error' in result:
        check("IPC-2581 解析成功", False, result['error'][:60])
    else:
        check("IPC-2581 解析成功", True)
        required_fields = ['components', 'nets', 'vias', 'diff_pairs', 'stackup',
                           'accuracy_level', 'source', 'constraints']
        missing_fields = [f for f in required_fields if f not in result]
        check("IPC-2581 所有必需字段完整", not missing_fields, f"缺少: {missing_fields}")
finally:
    os.unlink(test_xml_path)

# 测试4: Gerber解析器结构
print("\n[测试4] Gerber解析器结构验证")
test_gerber = """%FSLAX36Y36*%
%MOMM*%
%ADD10C,0.1524*%
G75*
D10*
X1000000Y2000000D02*
X3000000Y4000000D01*
M02*
"""

with tempfile.TemporaryDirectory() as tmpdir:
    gerber_file = os.path.join(tmpdir, 'test.gtl')
    with open(gerber_file, 'w') as f:
        f.write(test_gerber)
    result = parse_gerber_traces(tmpdir)
    if 'error' in result:
        check("Gerber 解析成功", False, result['error'][:60])
    else:
        check("Gerber 解析成功", True)
        required_fields = ['traces', 'total_length', 'layer_count',
                           'accuracy_level', 'source', 'constraints']
        missing_fields = [f for f in required_fields if f not in result]
        check("Gerber 所有必需字段完整", not missing_fields, f"缺少: {missing_fields}")

print()
print("=" * 60)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 60)
sys.exit(1 if failed else 0)
