#!/usr/bin/env python3
"""
Hardware Analyzer - 演示测试
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from parsers.kicad_parser import Component, Net
from checkers.schematic_checklist import SchematicChecker
from analyzers.power_analyzer import PowerAnalyzer
from reporters.html_reporter import HTMLReporter


def create_mock_data():
    """创建模拟数据"""
    components = {
        'U1': Component('U1', 'STM32F407', 'LQFP-100'),
        'U2': Component('U2', 'AMS1117-3.3', 'SOT-223'),
        'C1': Component('C1', '100nF', '0603'),
        'C2': Component('C2', '10uF', '0805'),
    }
    
    nets = {
        '+3V3': Net('+3V3'),
        'GND': Net('GND'),
    }
    
    return components, nets


def load_config():
    """加载配置"""
    return {
        'power_rules': {
            'voltage_drop': {'tolerance_percent': 3},
            'pdn_impedance': {'default_ripple_mv': 50}
        }
    }


def main():
    print("=" * 60)
    print("Hardware Analyzer - 演示测试")
    print("=" * 60)
    
    # 加载配置
    print("\n[1] 加载配置...")
    config = load_config()
    print(f"✓ 配置加载成功")
    
    # 创建数据
    print("\n[2] 创建模拟数据...")
    components, nets = create_mock_data()
    print(f"✓ {len(components)} 个元件, {len(nets)} 个网络")
    
    # 检查
    print("\n[3] 运行检查...")
    checker = SchematicChecker(components, nets, config)
    checklist_results = checker.run_full_checklist()
    print("✓ 检查完成")
    
    # 电源分析
    print("\n[4] 电源分析...")
    power_analyzer = PowerAnalyzer(components, nets, config)
    power_results = power_analyzer.analyze()
    print("✓ 分析完成")
    
    # 生成报告
    print("\n[5] 生成报告...")
    reporter = HTMLReporter(Path(__file__).parent / "reports")
    
    all_issues = power_results.get('issues', [])
    
    analysis_results = {
        'total_components': len(components),
        'total_nets': len(nets),
        'all_issues': all_issues,
    }
    
    report_path = reporter.generate_report(analysis_results, "demo.sch")
    print(f"✓ 报告: {report_path}")
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
    print(f"\n✓ 所有核心模块运行正常")
    print(f"✓ 查看报告: {report_path.absolute()}")


if __name__ == '__main__':
    main()

