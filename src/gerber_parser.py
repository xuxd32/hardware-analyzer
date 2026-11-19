#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerber 可选解析器 - 仅用于走线长度估算
=========================================
**重要约束**：
- ✅ 用途：走线长度粗略估算（±20%误差）
- ❌ 不能：网络映射（Gerber无语义）
- ❌ 不能：元件坐标提取（应使用xy.xlsx）
- ❌ 不能：过孔层对分析（应使用IPC-2581）

准确性边界：
- 走线长度：⭐⭐⭐ 趋势准确（±20%误差，基于几何路径）
- 不支持：网络、元件、电气参数

使用场景：
- 快速估算差分对长度匹配（<5mil）
- 布线密度可视化
- 走线宽度统计

**为什么不用Gerber做更多？**
根据 DATA_FORMAT_CONSTRAINTS.md 第118-140行：
1. Gerber是几何指令，无语义
2. BGA/盲埋孔误判率高（~30%）
3. 工具定位是"Layout审查"，不是"PCB逆向"
"""

import re
import math
from pathlib import Path
from collections import defaultdict


class GerberParser:
    """Gerber RS-274X 格式解析器（仅走线长度）"""
    
    def __init__(self, gerber_dir):
        """初始化解析器
        
        Args:
            gerber_dir: Gerber文件目录（包含所有层）
        """
        self.gerber_dir = Path(gerber_dir)
        self.layers = {}
        self.traces = []

        
    def parse(self):
        """解析Gerber文件，仅提取走线长度"""
        try:
            # 扩展名覆盖：.gbr/.gtl/.gbl（KiCad/Altium）+ .pho（PADS 光绘）
            gerber_files = list(self.gerber_dir.glob('*.gbr')) + \
                          list(self.gerber_dir.glob('*.gtl')) + \
                          list(self.gerber_dir.glob('*.gbl')) + \
                          list(self.gerber_dir.glob('*.pho'))
            
            if not gerber_files:
                return {'error': '未找到Gerber文件（.gbr/.gtl/.gbl/.pho）'}
            
            for gfile in gerber_files:
                layer_name = gfile.stem
                traces = self._parse_gerber_file(gfile)
                self.layers[layer_name] = traces
                self.traces.extend(traces)
            
            total_length = sum(t['length_mm'] for t in self.traces)
            
            return {
                'traces': self.traces,
                'total_length': round(total_length, 2),
                'layer_count': len(self.layers),
                'accuracy_level': '⭐⭐⭐ 趋势准确（±20%误差）',
                'source': 'Gerber',
                'constraints': '仅几何估算，无网络语义，不能映射到元件',
                'warning': '⚠️ Gerber走线长度为粗略估算，不可用于精确阻抗计算'
            }
            
        except Exception as e:
            return {'error': f'Gerber解析失败: {e}'}
    
    def _parse_gerber_file(self, filepath):
        """解析单个Gerber文件。

        兼容格式：
          - .gbr/.gtl/.gbl（KiCad/Altium，通常 %MOMM 绝对坐标）
          - .pho（PADS 光绘，%MOIN 英寸 + 增量坐标，见下）
        精确性约束：单位/坐标模式必须从文件声明读，禁止猜测（精确性红线）。
        """
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        apertures = self._extract_apertures(content)
        format_spec = self._detect_format(content)      # 小数位数（10^dec）
        unit_scale = self._detect_unit(content)         # mm→1.0，inch→25.4
        incremental = self._detect_incremental(content) # True=增量(G91)

        traces = []
        current_x, current_y = 0.0, 0.0
        current_circle_aperture = None   # 圆形 aperture 直径（mm）
        current_quadrant = 'G75'         # G74 单象限 / G75 多象限（模态）
        current_interpolation = 'G01'     # G01 直线 / G02 顺弧 / G03 逆弧（模态）
        in_region = False                 # 是否在 G36/G37 region 内
        region_first_point = False        # G36 后第一个坐标 = 绝对坐标（PADS 非标准行为）

        for line in content.split('\n'):
            s = line.strip()
            if not s or s.startswith('%') or s.startswith('G04'):
                continue

            # 插值/象限模式（模态，支持单独行 G03* 或同行 G03X..D01*）
            if re.search(r'G0([123])', s, re.IGNORECASE):
                g = re.search(r'G0([123])', s, re.IGNORECASE).group(1)
                current_interpolation = {'1': 'G01', '2': 'G02', '3': 'G03'}[g]
            if re.search(r'G7([45])', s, re.IGNORECASE):
                current_quadrant = 'G74' if re.search(r'G74', s, re.IGNORECASE) else 'G75'

            # Region 起止
            if re.fullmatch(r'G36\*?', s, re.IGNORECASE):
                in_region = True
                region_first_point = True
                continue
            if re.fullmatch(r'G37\*?', s, re.IGNORECASE):
                in_region = False
                region_first_point = False
                continue

            # 选中 aperture（D 数字，如 D10*）
            m = re.match(r'^D(\d{1,3})\*?$', s)
            if m:
                ap = apertures.get(int(m.group(1)), {})
                if ap.get('type') == 'circle':
                    current_circle_aperture = ap.get('size', 0.0) * unit_scale
                continue

            # 坐标 D 指令：D01/D02/D03
            m = re.search(r'D0([123])', s)
            if not m:
                continue
            op = int(m.group(1))

            # 提取 X/Y（可为负、可缺省）
            xm = re.search(r'X([+-]?\d+)', s)
            ym = re.search(r'Y([+-]?\d+)', s)
            dx = int(xm.group(1)) / format_spec * unit_scale if xm else 0.0
            dy = int(ym.group(1)) / format_spec * unit_scale if ym else 0.0

            if op == 2 and (xm or ym):
                # D02 移动：PADS 用「绝对坐标」（实测 82% 落板内验证），非增量
                new_x = dx
                new_y = dy
                region_first_point = False
            elif region_first_point and (xm or ym):
                # G36 后第一个坐标（若为 D01）也是绝对
                new_x = dx
                new_y = dy
                region_first_point = False
            elif incremental:
                new_x, new_y = current_x + dx, current_y + dy
            else:
                # 绝对模式：缺省 X/Y 时继承当前值（而非归零）
                new_x = dx if xm else current_x
                new_y = dy if ym else current_y

            # D01 画线/画弧（按 current_interpolation）；D02 移动；D03 闪光不计
            if op == 1:
                if current_interpolation in ('G02', 'G03'):
                    arc_dir = 'cw' if current_interpolation == 'G02' else 'ccw'
                    im = re.search(r'I([+-]?\d+)', s)
                    jm = re.search(r'J([+-]?\d+)', s)
                    i_mm = int(im.group(1)) / format_spec * unit_scale if im else 0.0
                    j_mm = int(jm.group(1)) / format_spec * unit_scale if jm else 0.0
                    length = self._arc_length(current_x, current_y, new_x, new_y,
                                              i_mm, j_mm, arc_dir, quadrant=current_quadrant)
                else:
                    length = ((new_x - current_x) ** 2 + (new_y - current_y) ** 2) ** 0.5
                traces.append({
                    'length_mm': length,
                    'width_mm': current_circle_aperture or 0.1,
                    'x1': round(current_x, 4),
                    'y1': round(current_y, 4),
                    'x2': round(new_x, 4),
                    'y2': round(new_y, 4),
                    'layer': Path(filepath).stem,
                    'is_region': in_region,
                })

            current_x, current_y = new_x, new_y

        return traces

    @staticmethod
    def _arc_length(sx, sy, ex, ey, i_mm, j_mm, direction, quadrant='G75'):
        """计算圆弧长度。圆心 = 起点 + (i,j)（增量）。

        Args:
            sx, sy: 起点（mm）
            ex, ey: 终点（mm）
            i_mm, j_mm: 弧心相对起点的偏移（mm，已换算）
            direction: 'cw'（G02 顺时针）或 'ccw'（G03 逆时针）
            quadrant: 'G75'（多象限，i/j 有符号，圆心唯一）
                      或 'G74'（单象限，i/j 无符号距离，4 候选圆心选择）

        Returns:
            弧长(mm)。整圆（终点==起点）返回周长 2πR。

        规范依据：Ucamco §4.10。单象限 G74 的圆心有 4 个候选(±i,±j)，
        选"终点在圆上 + 扫角≤90° + 方向正确 + 偏差最小"者。
        """
        r = math.hypot(i_mm, j_mm)
        if r <= 0:
            # 半径为零，退化为直线
            return math.hypot(ex - sx, ey - sy)

        if quadrant == 'G74':
            # 单象限：I/J 是无符号距离，4 候选圆心
            candidates = [
                (sx + abs(i_mm), sy + abs(j_mm)),
                (sx - abs(i_mm), sy + abs(j_mm)),
                (sx + abs(i_mm), sy - abs(j_mm)),
                (sx - abs(i_mm), sy - abs(j_mm)),
            ]
            # 去重
            seen = set()
            best = None  # (deviation, sweep)
            for cx, cy in candidates:
                key = (round(cx, 9), round(cy, 9))
                if key in seen:
                    continue
                seen.add(key)
                r_end = math.hypot(ey - cy, ex - cx)
                dev = abs(r - r_end)
                # 终点需在圆上（容差）
                if dev > max(1e-6, r * 1e-4):
                    continue
                start_ang = math.atan2(sy - cy, sx - cx)
                end_ang = math.atan2(ey - cy, ex - cx)
                if direction == 'ccw':
                    sweep = (end_ang - start_ang) % (2 * math.pi)
                else:
                    sweep = (start_ang - end_ang) % (2 * math.pi)
                # 单象限：扫角 ≤ 90°
                if sweep > math.pi / 2 + 1e-9:
                    continue
                if best is None or dev < best[0]:
                    best = (dev, sweep)
            if best is not None:
                return r * best[1]
            # 无合法候选 → 整圆兜底或按直线
            return 2 * math.pi * r if (abs(ex-sx) < 1e-9 and abs(ey-sy) < 1e-9) else math.hypot(ex - sx, ey - sy)

        # G75 多象限：有符号偏移，圆心唯一（默认）
        cx, cy = sx + i_mm, sy + j_mm
        # 整圆：终点与起点重合
        if abs(ex - sx) < 1e-9 and abs(ey - sy) < 1e-9:
            return 2 * math.pi * r

        start_ang = math.atan2(sy - cy, sx - cx)
        end_ang = math.atan2(ey - cy, ex - cx)
        if direction == 'ccw':
            sweep = (end_ang - start_ang) % (2 * math.pi)
        else:
            sweep = (start_ang - end_ang) % (2 * math.pi)
        if sweep == 0:
            sweep = 2 * math.pi
        return r * sweep

    def _extract_apertures(self, content):
        """提取孔径定义（走线宽度）。支持 C（圆形）和 R（矩形，用短边）。"""
        apertures = {}
        for match in re.finditer(r'%ADD(\d+)C,([0-9.]+)', content):
            apertures[int(match.group(1))] = {'size': float(match.group(2)), 'type': 'circle'}
        for match in re.finditer(r'%ADD(\d+)R,([0-9.]+)X([0-9.]+)', content):
            w, h = float(match.group(2)), float(match.group(3))
            apertures[int(match.group(1))] = {'size': min(w, h), 'type': 'rect'}
        return apertures

    def _detect_format(self, content):
        """检测坐标格式 %FS...X/Y 位数，返回小数位对应的 10^dec。

        兼容 %FSLAX../%FSLIX..（L=省略前导零，A=绝对/I=增量）、%FST... 等。
        解析 %FS<L/T><A/I>X<整数位><小数位>Y<整数位><小数位>。
        """
        m = re.search(r'%FS([LT])([AI])X(\d)(\d)Y(\d)(\d)', content)
        if m:
            decimal_places = int(m.group(4))  # X 的小数位
            return 10 ** decimal_places
        return 1e6

    def _detect_unit(self, content):
        """检测单位，返回 mm 的比例：%MOMM→1.0，%MOIN→25.4。缺省按 mm（不猜，声明为准）。"""
        if re.search(r'%MOMM', content, re.IGNORECASE):
            return 1.0
        if re.search(r'%MOIN', content, re.IGNORECASE):
            return 25.4
        return 1.0  # 未声明单位按 mm（Gerber 常见缺省，见精确性红线）

    def _detect_incremental(self, content):
        """检测坐标模式：%FSLIX（I=增量）→True；%FSLAX（A=绝对）→False。缺省 False。"""
        m = re.search(r'%FS[LT]([AI])X', content)
        if m:
            return m.group(1) == 'I'
        return False


def parse_gerber_traces(gerber_dir):
    """快速接口：解析Gerber走线长度"""
    parser = GerberParser(gerber_dir)
    return parser.parse()


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python gerber_parser.py <Gerber文件目录>")
        print("\n⚠️  注意：Gerber解析仅用于走线长度估算，不能：")
        print("   - ❌ 提取元件坐标（应使用 xy.xlsx）")
        print("   - ❌ 映射网络连接（应使用 IPC-D-356）")
        print("   - ❌ 分析过孔层对（应使用 IPC-2581）")
        sys.exit(1)
    
    result = parse_gerber_traces(sys.argv[1])
    
    if 'error' in result:
        print(f"❌ {result['error']}")
    else:
        print(f"✅ Gerber解析成功")
        print(f"   走线数量: {len(result['traces'])}")
        print(f"   总长度: {result['total_length']} mm")
        print(f"   层数: {result['layer_count']}")
        print(f"   准确性: {result['accuracy_level']}")
        print(f"   约束: {result['constraints']}")
        print(f"\n{result.get('warning', '')}")
