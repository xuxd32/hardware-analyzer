# Hardware Analyzer

只读的 PCB / 原理图 / 网表分析工具。从 EDA 导出的设计文件中提取网络、元件与布局信息，给出电源、信号、时钟、接口等方面的启发式检查提示，并生成 HTML 报告。

> 本工具为个人项目，代码与文档均可自由使用（见 [LICENSE](LICENSE)）。

## 环境要求

- Python 3.8+（开发与实测环境为 Python 3.13）
- 主程序与图形界面仅使用 Python 标准库（含 tkinter），无强制第三方依赖
- 可选的原理图 PDF 提取工具需要 `pypdf`；扫描件本地 OCR 另需 `pymupdf`、`rapidocr-onnxruntime`，见 [requirements.txt](requirements.txt)

## 快速开始

在仓库根目录执行。

命令行：

```bash
python src/main.py --schematic "path/to/schematics/*.sch" --mode full
```

图形界面（Tkinter）：

```bash
python src/gui.py
```

查看命令行参数：

```bash
python src/main.py --help
```

更多用法与参数说明见 [USER_GUIDE.md](USER_GUIDE.md)。

## 支持的输入

| 类别 | 格式 / 文件 | 说明 |
|------|-------------|------|
| 原理图 | `.sch` | 只读扫描，提取元件与网络线索 |
| 网表 | KiCad `.net`、Allegro `.net`、OrCAD EXPANDED `.dat`、PADS2000 `.asc` | 自动检测格式 |
| PCB 交付件目录 | `xy.xlsx`、IPC-D-356 `.ipc`、`.dxf` | 元件坐标、测试网络、板框范围 |
| IPC-2581 | `.xml` | 元件坐标、引脚级网络、过孔层对、差分对 |
| Gerber | `.gbr` / `.gtl` / `.gbl` / `.pho` | 走线长度估算 |

## 分析模式

`--mode` 可选：`full`（默认）、`power`、`signal`、`clock`、`interface`、`diagnostic`。

主要分析内容：

- 网络分类：电源 / 地 / USB / 显示 / 存储 / 通信 / 时钟 / 控制
- 电源电压域分组、PDN 目标阻抗估算
- 元件值统计与关键器件识别（LDO / DCDC / 晶振 / ESD / 保险丝等）
- 去耦电容、晶振、ESD 器件的布局距离检查
- 直流压降、母线掉压、安装环路 ESL 估算
- 差分对识别与启发式风险提示

## 输出

分析结果输出到 `reports/` 目录，生成 HTML 报告。报告内的电源树示意图通过 CDN 加载 mermaid，离线环境下图表可能不渲染，文字与表格不受影响。

## 目录结构

```
hardware-analyzer/
├── src/                     # 主程序源码
│   ├── main.py              # 命令行入口
│   ├── gui.py               # Tkinter 图形界面
│   ├── calculators.py       # 工程公式计算
│   ├── pcb_deliverables.py  # PCB 交付件分析
│   ├── *_parser.py          # 各类网表 / 结构解析器
│   ├── analyzers/           # 方向、电源等分析模块
│   ├── checkers/            # 原理图检查清单
│   ├── parsers/             # 解析辅助
│   └── reporters/           # HTML 报告生成
├── schematic_pdf_tools/     # 可选：原理图 PDF 文本提取与 OCR 兜底
├── scripts/                 # 集成测试脚本
├── config/rules.yaml        # 检查规则阈值
├── test_*.py                # 脚本式测试（无需 pytest）
├── requirements.txt
├── USER_GUIDE.md
└── LICENSE
```

## 测试

测试为脚本式断言，逐个在仓库根目录运行即可：

```bash
python test_calculators.py
python test_parsers.py
# 其余 test_*.py 同理
```

## 使用边界

- 工具**只读**分析输入文件，不会修改被分析的设计文件。
- 检查结论基于字符串扫描与启发式规则，**可能漏报或误报**，须结合原理图、网表与人工复核。
- 阻抗、压降、ESL、走线长度等为工程估算值，不能替代正式 DRC 、仿真或实测。

## 许可证

MIT License，见 [LICENSE](LICENSE)。
