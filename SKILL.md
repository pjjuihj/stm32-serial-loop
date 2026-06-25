---
name: stm32-serial-loop
description: >
  通用嵌入式串口闭环调试工具。串口数据采集 → 数据分析 → 报告 → 对比历史。
  适用于任何嵌入式项目的传感器数据调试、执行器控制调试、协议通信调试。
  支持文本数据、HEX 数据包、VOFA+ 协议等多种格式。
  配置系统支持自定义心跳前缀、寄存器位定义、问题检测规则。
---

# 串口闭环调试

串口数据采集 → 数据分析 → 报告 → 对比历史 → 闭环验证

## 职责

本工具是**测量工具**，不是维修工具。职责：

| 做 | 不做 |
|----|------|
| 采集串口数据 | 生成 C 代码 |
| 分析范围/跳变/连续性/统计/频率/卡值/时序 | 注入代码到源文件 |
| 解析心跳/寄存器值 | 搜索社区 |
| 对比历史数据 | 读 HAL 源码 |
| 读项目文档（solutions-log 等） | 生成诊断步骤 |
| 写调试日志 | 编译烧录 |
| 复位设备 | |

## 核心流程

```
采集 → 分析 → 报告 → 对比历史
         ↓
    读文档匹配已知问题
         ↓
    写调试日志
         ↓
    编译烧录 + 复位
         ↓
    重新采集验证
```

## 快速开始

```bash
# 数据采集（10秒）
python serial_loop.py --port COM3 --mode collect --duration 10

# 数据分析
python serial_loop.py --port COM3 --mode analyze --duration 10 --min-val 0 --max-val 100

# 闭环调试（采集 → 分析 → 报告 → 编译烧录 → 验证）
python serial_loop.py --port COM3 --mode loop --duration 10 --max-iterations 5

# 采集前发送诊断命令
python serial_loop.py --port COM3 --mode collect --duration 10 --send-cmd "HB"

# 发送十六进制命令
python serial_loop.py --port COM3 --mode collect --duration 10 --send-hex AA550100FF

# 使用自定义配置
python serial_loop.py --port COM3 --mode collect --config my_config.json
```

## 工作模式

| 模式 | 说明 | 命令 |
|------|------|------|
| `collect` | 数据采集 | `--mode collect --duration 10` |
| `analyze` | 数据分析 | `--mode analyze --duration 10` |
| `loop` | 闭环调试 | `--mode loop --duration 10 --max-iterations 5` |
| `report` | 生成报告 | `--mode report --input data.json` |
| `reset` | 设备复位 | `--mode reset --reset-method dtr_rts` |

## CLI 参数

```
--port PORT           串口号 (如 COM3)
--baud BAUD           波特率 (默认 115200)
--mode MODE           工作模式 (collect/analyze/loop/report/reset)
--duration SECONDS    采集时长 (秒)
--protocol TYPE       协议类型 (text/hex/vofa)
--min-val FLOAT       最小值阈值
--max-val FLOAT       最大值阈值
--jump-threshold      跳变阈值
--expected-interval   预期间隔
--input FILE          输入数据文件
--output FILE         输出文件路径
--list                列出可用串口
--send-cmd STR        采集前发送文本命令（可多次使用）
--send-hex HEX        采集前发送十六进制数据
--check-build         采集后检查 BUILD 时间戳
--config FILE         JSON 配置文件
--build-marker STR    编译时间戳前缀（默认 BUILD:）
--heartbeat-prefix STR 心跳行前缀，逗号分隔

复位相关:
--reset-method METHOD 复位方法 (dtr/rts/dtr_rts/break/break_dtr/custom/bootloader)
--verify-reset        复位后验证设备响应
--verify-pattern STR  验证匹配的字符串
--max-retries N       复位最大重试次数 (默认 3)
--auto-detect         自动探测最佳复位方法
--reset-log           查看复位日志
--bootloader          进入 STM32 bootloader 模式

闭环相关:
--max-iterations N    闭环最大迭代次数 (默认 5)
--timeout SECONDS     闭环总超时 (默认 300)
--health-check        编译前运行健康检查
--brick-check         烧录前运行死机预防检查
```

## 数据分析功能

### 基础分析

| 分析 | 说明 | CLI |
|------|------|-----|
| 范围检查 | 数据是否在有效范围内 | `--min-val 0 --max-val 100` |
| 跳变检测 | 数据异常跳变 | `--jump-threshold 20` |
| 连续性检查 | 采样间隔是否均匀 | `--expected-interval 1.0` |
| 统计分析 | 均值/中位数/标准差/方差 | 自动 |
| 趋势分析 | 上升/下降/平稳 | 自动 |
| 异常值检测 | Z-score 方法 | 自动 |
| 周期性检测 | 自相关方法 | 自动 |
| 稳定性分析 | 滑动标准差 | 自动 |
| 分布分析 | 直方图/偏度/峰度 | 自动 |

### 嵌入式专用分析

| 分析 | 说明 |
|------|------|
| 频率检测 | 零交越法估算信号频率 |
| 卡值检测 | ADC/传感器值长时间不变 |
| 时序间隙 | 采样间隔不均匀 |
| 心跳解析 | 通用 key:value 解析，自动识别寄存器位域 |

### 心跳解析

自动识别固件输出的诊断信息，解析 key:value 对和寄存器值。

```bash
# 默认前缀: HB, STATUS, DBG, DIAG
# 固件输出: "HB H:1 C:1 | DAC CR:0x000034B1 NDTR:128"
# 自动解析: h=1, c=1, dac_cr=0x000034B1, ndtr=128
# 自动展开寄存器位: dac_cr_en=1, dac_cr_circ=1, dac_cr_psize=1, dac_cr_msize=1
```

配置文件自定义：
```json
{
    "heartbeat_prefixes": ["HB", "STATUS"],
    "register_bits": {
        "en":    {"bit": 0,  "width": 1},
        "circ":  {"bit": 8,  "width": 1},
        "psize": {"bit": 11, "width": 2},
        "msize": {"bit": 13, "width": 2}
    },
    "register_name_pattern": "(?:DMA_)?CR|SR|CSR|ISR"
}
```

## 配置系统

通过 `--config` JSON 文件或 CLI 参数覆盖默认配置。

```json
{
    "build_marker": "BUILD:",
    "heartbeat_prefixes": ["HB", "STATUS", "DBG", "DIAG"],
    "register_bits": {
        "en":    {"bit": 0,  "width": 1},
        "circ":  {"bit": 8,  "width": 1},
        "minc":  {"bit": 10, "width": 1},
        "psize": {"bit": 11, "width": 2},
        "msize": {"bit": 13, "width": 2}
    },
    "register_name_pattern": "(?:DMA_)?CR|SR|CSR|ISR",
    "issue_rules": [
        {"field": "h",      "op": "<=", "value": 1, "type": "counter_stopped"},
        {"field": "c",      "op": "<=", "value": 1, "type": "counter_stopped"},
        {"field": "*_circ", "op": "==",  "value": 0, "type": "no_circ"}
    ]
}
```

配置优先级：默认值 → JSON 文件 → CLI 参数

## 文档集成

### 读取已知问题

自动搜索 `docs/` 目录下的问题文档（solutions-log.md、issues.md、problems.md 等），
与当前分析结果对比，匹配已知问题。

### 写入调试日志

每轮分析后自动写入 `docs/debug_logs/debug_YYYYMMDD_HHMMSS_iterN.md`。

## 闭环调试流程

```bash
# 单轮闭环
python serial_loop.py --port COM3 --mode loop --duration 10

# 多轮闭环 + 复位验证
python serial_loop.py --port COM3 --mode loop --duration 10 \
    --max-iterations 5 --reset-method dtr_rts --verify-reset

# 闭环 + 健康检查 + 死机预防
python serial_loop.py --port COM3 --mode loop --duration 10 \
    --health-check --brick-check
```

**4 步流程：**
1. 采集数据
2. 分析 + 报告 + 对比文档 + 写日志
3. 编译烧录 + 复位
4. 重新采集验证（对比前后数据）

## 设备复位

| 方法 | 说明 | 适用场景 |
|------|------|----------|
| `dtr` | DTR 信号复位 | DTR 连接 NRST |
| `rts` | RTS 信号复位 | RTS 连接 NRST |
| `dtr_rts` | DTR+RTS 组合 | CH340/CP2102 |
| `break` | BREAK 信号 | 支持 BREAK 的模块 |
| `bootloader` | 进入 STM32 bootloader | BOOT0 拉高后复位 |

```bash
# 自动探测最佳复位方法
python serial_loop.py --port COM3 --mode reset --auto-detect

# 复位 + 验证
python serial_loop.py --port COM3 --mode reset --reset-method dtr_rts --verify-reset
```

## 数据可视化

```bash
# ASCII 图表
python serial_loop.py --mode analyze --input data.json --chart

# ASCII 直方图
python serial_loop.py --mode analyze --input data.json --histogram
```

## stm32-keil-workflow 集成

| 集成功能 | 触发条件 |
|---------|---------|
| 编译烧录 | `compile_and_flash()` |
| 健康检查 | `--health-check` 参数 |
| 死机预防 | `--brick-check` 参数 |
| 错误总结 | 编译失败时自动调用 |
| 错误追踪 | `search_error_history()` |

## 示例

### 传感器数据调试

```bash
# 采集温度数据
python serial_loop.py --port COM3 --mode collect --duration 30 --filter "temp"

# 分析稳定性
python serial_loop.py --port COM3 --mode analyze --duration 30 --jump-threshold 5
```

### 协议通信调试

```bash
# HEX 数据包
python serial_loop.py --port COM3 --mode collect --duration 10 --protocol hex

# VOFA+ 协议
python serial_loop.py --port COM3 --mode collect --duration 10 --protocol vofa
```

### 带诊断命令的采集

```bash
# 采集前发送 HB 命令让固件输出心跳
python serial_loop.py --port COM3 --mode collect --duration 10 --send-cmd "HB"

# 发送十六进制诊断命令
python serial_loop.py --port COM3 --mode collect --duration 10 --send-hex "AA550100FF"
```

## 依赖

| 依赖 | 必需 | 说明 |
|------|------|------|
| Python 3.8+ | ✅ | 运行脚本 |
| pyserial | ✅ | 串口通信 |
| Keil MDK-ARM | ⚠️ | 编译工具链（闭环模式需要） |
| stm32-keil-workflow | ⚠️ | 编译烧录工作流（闭环模式需要） |

## 安全约束

- **不全片擦除** — 只烧录指定固件
- **不写 Option Bytes** — 避免锁定芯片
- **不改读保护** — 保持原有 RDP 级别
- **代码注入前自动备份** — 原文件保存为 `.bak`
- **复位日志可追溯** — `--reset-log` 查看历史
