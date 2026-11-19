#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方向分析器测试脚本（强测试：真实 list 结构 + 断言 + 失败即 exit(1)）"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src' / 'analyzers'))

from direction_analyzer import DirectionAnalyzer, format_direction_report

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


def main():
    print("=" * 80)
    print("方向分析器测试".center(76))
    print("=" * 80)
    print()

    # 真实 netlist_result 结构（main.py 传入）：components/nets 是 netlist_data 下的 list
    mock_netlist = {
        'netlist': {
            'netlist_data': {
                'components': [
                    {'ref': 'U1', 'value': 'QCS6490', 'footprint': ''},
                    {'ref': 'U2', 'value': 'MPQ8875', 'footprint': ''},
                    {'ref': 'U3', 'value': 'TXS0108E', 'footprint': ''},
                    {'ref': 'C1', 'value': '100nF', 'footprint': ''},
                    {'ref': 'C2', 'value': '10uF', 'footprint': ''},
                    {'ref': 'R1', 'value': '10k', 'footprint': ''},
                ],
                'nets': [
                    {'code': 1, 'name': 'VDD_CORE', 'nodes': [{'ref': 'U1', 'pin': '1'}]},
                    {'code': 2, 'name': 'VDD_IO', 'nodes': [{'ref': 'U1', 'pin': '2'}]},
                    {'code': 3, 'name': 'RESET_N', 'nodes': [{'ref': 'U1', 'pin': '3'}, {'ref': 'R1', 'pin': '1'}]},
                ],
            }
        }
    }

    mock_analysis = {
        'power_nets': ['VDD_CORE', 'VDD_IO'],
        'gnd_signal_count': 15,
        'classified_nets': {'control': ['RESET_N', 'PWREN']},
    }

    analyzer = DirectionAnalyzer(mock_netlist, mock_analysis)
    result = analyzer.analyze()

    # 断言：检测到的 issue 类型（netlist 相关检测应真实生效）
    issue_types = [i['type'] for i in result.get('detected_issues', [])]
    check("检测到多电源域 multi_power_domain", 'multi_power_domain' in issue_types)
    check("检测到 RESET 电路 reset_circuit", 'reset_circuit' in issue_types)
    check("检测到多地网络 multiple_gnd_nets", 'multiple_gnd_nets' in issue_types)
    check("检测到去耦电容 decoupling_capacitors", 'decoupling_capacitors' in issue_types)
    check("检测到电平转换器 level_shifter", 'level_shifter' in issue_types)

    # 断言：RESET 电路正确提取了电阻 R1
    reset_issue = next((i for i in result.get('detected_issues', []) if i['type'] == 'reset_circuit'), None)
    if reset_issue:
        resistors = reset_issue.get('detail', {}).get('resistors', [])
        check("RESET 电路提取到电阻 R1", 'R1' in resistors, f"resistors={resistors}")
    else:
        check("RESET 电路提取到电阻 R1", False, "无 reset_circuit issue")

    # 断言：去耦电容统计正确（2 个电容）
    dec_issue = next((i for i in result.get('detected_issues', []) if i['type'] == 'decoupling_capacitors'), None)
    if dec_issue:
        total = dec_issue.get('detail', {}).get('total', 0)
        check("去耦电容总数 = 2", total == 2, f"total={total}")
    else:
        check("去耦电容总数 = 2", False, "无 decoupling_capacitors issue")

    # 断言：生成了排查方向
    directions = result.get('possible_directions', [])
    check("生成至少一个排查方向", len(directions) > 0, f"directions={len(directions)}")

    print()
    print(format_direction_report(result))

    print()
    print("=" * 80)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 80)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
