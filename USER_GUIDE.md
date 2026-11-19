# Hardware Analyzer - 完整使用说明

## 目录
1. [简介](#简介)
2. [快速开始](#快速开始)
3. [命令行参数详解](#命令行参数详解)
4. [分析模式](#分析模式)
5. [参数示例](#参数示例)
6. [输出文件](#输出文件)

---

## 简介

### 是什么
Hardware Analyzer  硬件分析程工具，用于：
- 格式自动检测: KiCad 文本格式 / OrCAD 二进制格式
- 二进制原理图分析: 无需设计工具，直接扫描 .sch 文件
- Netlist 真实连接分析: 支持 KiCad(.net) 和 Allegro(.net) 格式
- 网络分类: 自动识别电源/地/USB/显示/存储/通信/时钟/控制信号
- 电源电压域分组: PDN 目标阻抗估算
- 元件值统计: 识别关键器件（LDO/DCDC/晶振/ESD/保险丝等）
- 风险提示: 启发式检查表推荐
- 多格式报告: 生成 HTML 可视化报告

### 关键特性
- 纯标准库: 无第三方依赖，独立运行
- 只读分析: 绝不修改被分析的硬件文件
- 离线工作: 无需网络连接
- 多格式支持: 原理图、Netlist、Gerber、IPC-2581、DXF

---

## 快速开始

### 源码运行方式（在仓库根目录执行）
命令行：
```batch
python src/main.py --schematic "path/to/schematic.sch"
```

图形界面：
```batch
python src/gui.py
```

### 最简单的用法
```batch
hardware-analyzer.exe --schematic "C:\path\to\schematic.sch"
```

### 完整分析
```batch
hardware-analyzer.exe ^
  --schematic "C:\path\to\*.sch" ^
  --netlist "C:\path\to\design.net" ^
  --mode full ^
  --output ".\reports"
```

### 获取帮助
```batch
hardware-analyzer.exe --help
hardware-analyzer.exe -h
```

---

## 命令行参数详解

### 输入文件参数

#### --schematic / -s (必选或与 netlist 二选一)
原理图文件路径，支持通配符

用途: 
- 二进制格式直接扫描分析（OrCAD .sch）
- 文本格式原理图解析（KiCad .sch）

支持格式:
- OrCAD Capture 二进制: .sch (受支持)
- KiCad 5.x 文本: .sch (自动检测)
- KiCad 6.x 文本: .kicad_sch (自动检测)

通配符示例:
```batch
--schematic "C:\project\*.sch"              (当前目录所有 .sch)
--schematic "C:\project\**\*.sch"           (当前+子目录所有 .sch)
--schematic "C:\project\Main_SCH\*.sch"     (指定目录)
```

限制:
- 必须至少提供 --schematic 或 --netlist 之一
- 二进制 OrCAD 格式为只读扫描（不解析完整结构）

---

#### --netlist / -n (必选或与 schematic 二选一)
Netlist 文件路径（真实网络连接）

用途:
- 网络级完整分析（去耦、时序、差分对、电源树）
- 比原理图扫描更精准

支持格式:
- KiCad Netlist (.net) - 自动检测
- Allegro Netlist (.net) - 自动检测

格式自动检测:
工具根据文件内容自动判断格式，无需显式指定

输出内容:
- 总器件数 & 总网络数
- 电源网络列表
- 地网络列表
- IC 去耦分析（前20个IC）
- 差分对识别
- 电源树拓扑（转换器、电源轨统计）
- Mermaid 图表

---

#### --ipc2581
IPC-2581 XML 文件路径（高级 PCB 数据）

包含内容:
- 元件坐标与引脚级网络
- 过孔层对信息
- 差分对定义
- PCB 叠层

使用场景:
- 需要元件坐标时
- 需要精确过孔分析时

---

#### --gerber
Gerber 文件目录（PCB 走线数据）

用途:
- 走线长度估算
- 走线阻抗计算

目录结构:
需要包含标准 Gerber 层文件：.gbr, .gbl 等

---

### 输出参数

#### --output / -o (可选，默认 reports/)
报告输出目录

用途:
- 指定 HTML 报告生成位置

默认行为:
- 工具自身目录下的 reports/ 子目录
- 如不存在自动创建

示例:
```batch
--output ".\my_reports"
--output "C:\outputs\hardware_analysis"
```

---

### 分析模式

#### --mode / -m (可选，默认 full)
分析模式选择

可选值:
| 模式 | 说明 | 输出侧重 |
|------|------|--------|
| full | 完整分析（默认） | 所有内容 |
| power | 电源分析模式 | PDN 目标阻抗、电压域、去耦 |
| signal | 信号分析模式 | 信号分类、接口、时钟 |
| clock | 时钟分析模式 | 时钟网络、晶振、频率 |
| interface | 接口分析模式 | 连接器、USB、HDMI 等 |
| diagnostic | 诊断模式 | 风险提示详细列表 |

示例:
```batch
--mode full          # 完整分析，生成详细 HTML
--mode power         # 仅关注电源，PDN设计时使用
--mode diagnostic    # 风险审查
```

---

### 电源/信号完整性参数

#### --istep (可选，默认 1.0)
瞬态电流阶跃 I_step (单位: A)

用途:
- 母线掉压估算 (Bus Droop)
- 计算公式: delta_V_ESR = I_step * ESR

典型值:
- 低功耗设备: 0.5 A


---

## 分析模式详解

### full (完整分析)
默认模式，包含所有分析维度

输出内容:
- 元件引用与类型分布
- 电源/地网络分类
- 电压域分组与 PDN 目标阻抗
- 信号分类（USB、HDMI、存储等）
- 时钟网络与晶振统计
- 接口与连接器
- 元件值 Top 排行
- 关键器件识别
- 风险提示（启发式）

HTML 报告: 最完整的可视化

### power (电源分析)
针对电源完整性设计

专注输出:
- 电压域分组详情
- PDN 目标阻抗估算（每个电源网络）
- 母线瞬态掉压（delta_V_ESR + delta_V_ESL + delta_V_C）
- 去耦电容分析
- 电源树拓扑

使用场景:
- PDN 设计审查
- 去耦策略评估
- 电源树优化

### signal (信号分析)
针对信号完整性

专注输出:
- 信号按类别统计（USB、HDMI、PCIe 等）
- 差分对识别
- 信号长度估算（如有 Gerber）
- 阻抗计算（微带线、差分对）

使用场景:
- 信号完整性审查
- 差分对匹配检查

### clock (时钟分析)
针对时钟网络

专注输出:
- 时钟网络数量统计
- 晶振及其负载
- 晶体参数（频率、负载电容）
- 时钟树拓扑

使用场景:
- 时钟设计审查
- 晶振选型验证

### interface (接口分析)
针对接口与连接器

专注输出:
- 连接器数量与类型
- 接口信号分类（USB、HDMI、以太网等）
- 每个接口的信号统计

使用场景:
- 接口设计验证
- EMI/EMC 审查

### diagnostic (诊断模式)
风险提示详细检查

输出:
- 所有风险项的详细列表
- 严重级别（CRITICAL/HIGH/MEDIUM/INFO）
- 逐项说明与建议

使用场景:
- 硬件审查 Checklist
- 设计问题排查

---

## 参数示例

### 示例1: 最简单的原理图扫描
```batch
hardware-analyzer.exe --schematic "C:\design\main.sch"
```

输出: 基本统计（元件数、网络数）、风险提示、默认 HTML 报告到 reports/

### 示例2: Netlist 完整分析（KiCad）
```batch
hardware-analyzer.exe --netlist "C:\design\project.net" --mode full
```

输出: 元件清单、网络连接、去耦分析、差分对、电源树

### 示例3: 电源设计评审
```batch
hardware-analyzer.exe ^
  --netlist "design.net" ^
  --mode power ^
  --istep 10.0 ^
  --dt-us 20.0 ^
  --trise-us 1.0 ^
  --ripple-mv 50.0 ^
  --output ".\pdn_analysis"
```

输出: 每个电源网络的 Z_target、母线掉压计算（3 种分量）、PDN 设计建议、去耦策略评估

### 示例4: 风险诊断
```batch
hardware-analyzer.exe --schematic "*.sch" --mode diagnostic
```

输出: 检查清单风险、缺失器件告警、电源设计风险、接口完整性提示

### 示例5: 完整交付件分析
```batch
hardware-analyzer.exe ^
  --schematic "C:\project\*.sch" ^
  --netlist "project.net" ^
  --gerber ".\gerber_files" ^
  --ipc2581 "project.xml" ^
  --mode full ^
  --output ".\final_report"
```

输出: 原理图分析、Netlist 连接、Gerber 走线长度、IPC-2581 元件坐标、综合 HTML 报告

---

## 输出文件

### HTML 报告结构

生成的 HTML 文件包含以下章节：

1. 总览 (Summary)
   - 元件引用数
   - 电源网络数
   - 地网络引用数
   - 风险提示数

2. 风险提示 (Risks)
   - 级别: CRITICAL (严重缺陷) / HIGH (重要问题) / MEDIUM (一般问题) / INFO (信息)
   - 检查项: 缺失旁路电容、晶体负载不匹配、接口缺上下拉、电源树不完整等
   - 启发式检查，需人工复核

3. Netlist 分析 (如提供)
   - 元件列表
   - 网络连接
   - 去耦分析（IC级）
   - 差分对
   - 电源树（Mermaid 图表）

4. IPC-2581 分析 (如提供)
   - 元件坐标
   - PCB 叠层

5. Gerber 分析 (如提供)
   - 走线统计
   - 走线长度分布

6. 电源/信号完整性估算
   - delta_V_ESR 计算（ESR 压降）
   - delta_V_ESL 计算（ESL 压降）
   - delta_V_C 计算（电容放电）
   - 总掉压
   - Z_target（PDN 目标阻抗）

7. 电源分析 (Power)
   - 电压域分组
   - PDN 目标阻抗
   - 去耦策略

8. 信号分析 (Signal)
   - 信号分类统计
   - 接口类型
   - 差分对

9. 时钟分析 (Clock)
   - 晶振数量
   - 晶体参数

10. 接口分析 (Interface)
    - 连接器数量
    - 接口类型统计

11. 元件统计 (Component)
    - 元件值排行（电容、电阻、电感）
    - 关键器件（LDO、DCDC、ESD、保险丝等）

---

## 常见问题

### Q1: 如何处理"必须提供 --schematic 或 --netlist"错误?
A: 至少指定其中一个参数

```batch
正确: hardware-analyzer.exe --schematic "main.sch"
错误: hardware-analyzer.exe (无参数)
```

### Q2: 通配符 * 不工作怎么办?
A: 使用正确的通配符语法

```batch
正确: --schematic "C:\project\*.sch"
      --schematic "C:\project\**\*.sch" (递归)
错误: --schematic C:\project\*.sch (缺少引号)
```

### Q3: 原理图格式不支持怎么办?
A: 工具自动检测，通常支持:
- OrCAD Capture .sch (二进制)
- KiCad 5.x .sch (文本)
- KiCad 6.x .kicad_sch (文本)

如不支持，则需转换格式或导出 Netlist。

### Q4: Netlist 解析失败?
A: 确保:
1. 文件格式为 KiCad .net 或 Allegro .net
2. 文件未损坏
3. 文件中包含网络连接信息（非空）

### Q5: PDN 目标阻抗计算很高?
A: 检查参数:
- --ripple-mv: 是否设置过高? (默认 50mV)
- --istep: 电流是否过小? (默认 1A)

计算: Z_target = V_ripple / I_step

增加电流或降低纹波会降低 Z_target。

### Q6: 风险提示都是启发式的，可靠吗?
A: 是启发式推断，基于:
- 关键词匹配（例如 "VCC", "GND"）
- 设计规则库
- 字符串扫描

需要人工复核。特别是:
- 二进制格式扫描可能漏检
- 格式差异导致误报
- 特殊设计不一定符合标准规则

建议: 结合原理图或设计文档进行人工验证。

### Q7: 为什么 OrCAD 原理图是"二进制原理图"?
A: OrCAD Capture 使用二进制 .sch 格式，工具：
- 不完全解析二进制结构
- 只读扫描文件内嵌的 ASCII 字符串（如 RefDes、网络名）
- 无需 OrCAD 软件即可提取基本信息

完整的网络级分析需要 Netlist 文件。

### Q8: 如何指定 ESR/ESL?
A: 
- 不指定: 工具按 0603、0805 等封装自动查表，失败默认 10mohm ESR / 1nH ESL
- 指定: 使用 --esr-mohm 和 --esl-nh 覆盖查表

```batch
--esr-mohm 25.0 --esl-nh 0.8  # 覆盖查表值
```

### Q9: 输出目录不存在会怎样?
A: 工具自动创建 --output 指定的目录（如不存在）

```batch
--output ".\my_reports"  # 不存在时自动创建


## 完整参数参考

```
用法: hardware-analyzer.exe [选项]

必选（至少一个）:
  --schematic PATTERN, -s PATTERN
                        原理图路径（支持通配符）
  --netlist FILE, -n FILE
                        Netlist 文件路径（KiCad .net 或 Allegro .net）

可选:
  --mode {full,power,signal,clock,interface,diagnostic}, -m ...
                        分析模式 (默认: full)
  --output DIR, -o DIR  报告输出目录 (默认: reports/)
  
电源完整性参数:
  --istep FLOAT         瞬态电流 I_step (A) (默认: 1.0)
  --dt-us FLOAT         负载持续时间 delta_t (us) (默认: 10.0)
  --trise-us FLOAT      电流上升时间 t_rise (us) (默认: 1.0)
  --esr-mohm FLOAT      电容 ESR (mohm) (可选，自动查表)
  --esl-nh FLOAT        电容 ESL (nH) (可选，自动查表)
  --ripple-mv FLOAT     允许纹波 V_ripple (mV) (默认: 50.0)

高级:
  --ipc2581 FILE        IPC-2581 XML 文件路径
  --gerber DIR          Gerber 文件目录

示例:
  hardware-analyzer.exe -s "C:\project\*.sch" -m full
  hardware-analyzer.exe -n design.net -m power --ripple-mv 50.0
  hardware-analyzer.exe -s main.sch -n project.net -m diagnostic
```



- 中等功耗: 1.0 - 5.0 A
- 高功耗处理器: 10.0 - 50.0 A

示例:
```batch
--istep 5.0          # 5A 瞬态电流
```

---

#### --dt-us (可选，默认 10.0)
负载持续时间 delta_t (单位: 微秒)

用途:
- 电容充放电时间
- 计算公式: delta_V_C = (I_step * delta_t) / C

典型值:
- 快速开关: 1 - 5 us
- 中等负载: 10 - 100 us
- 缓慢变化: 100 - 1000 us

示例:
```batch
--dt-us 20.0         # 20 us 负载持续
```

---

#### --trise-us (可选，默认 1.0)
电流上升时间 t_rise (单位: 微秒)

用途:
- 计算 di/dt = I_step / t_rise
- 用于 ESL 压降: delta_V_ESL = L * di/dt

典型值:
- 快速 FPGA: 0.1 - 0.5 us
- 一般 MCU: 1 - 5 us
- 缓慢器件: 5 - 10 us

示例:
```batch
--trise-us 0.5       # 0.5 us 上升时间
```

---

#### --esr-mohm (可选，自动查表)
电容等效串联电阻 ESR (单位: 毫欧)

用途:
- 直接指定电容 ESR 值
- 跳过自动查表

默认行为:
- 不填则按 0805、1206 等封装自动查表
- 查表失败时默认 10 mohm 兜底

典型值:
- 陶瓷电容: 5 - 50 mohm
- 钽电容: 50 - 200 mohm
- 铝电解: 100 - 500 mohm

示例:
```batch
--esr-mohm 25.0      # 手动指定 25 mohm
```

---

#### --esl-nh (可选，自动查表)
电容等效串联电感 ESL (单位: 纳亨 nH)

用途:
- 直接指定电容 ESL 值
- 跳过自动查表

默认行为:
- 不填则按 0805、1206 等封装自动查表
- 查表失败时默认 1 nH 兜底

典型值:
- 0603: 0.5 - 1.0 nH
- 0805: 1.0 - 1.5 nH
- 1206: 1.5 - 2.0 nH

示例:
```batch
--esl-nh 0.8         # 手动指定 0.8 nH
```

---

#### --ripple-mv (可选，默认 50.0)
允许纹波/跌落 V_ripple (单位: 毫伏 mV)

用途:
- PDN 目标阻抗设计
- 公式: Z_target = V_ripple / I_step

典型值:
- 3.3V 电源: 50 - 100 mV (±1.5%-3%)
- 1.2V 电源: 12 - 24 mV (±1%-2%)
- 5V 电源: 100 - 250 mV (±2%-5%)

示例:
```batch
--ripple-mv 30.0     # 30 mV 纹波限制
```
