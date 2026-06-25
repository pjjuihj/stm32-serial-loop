# 串口闭环调试

通用嵌入式串口闭环调试工具：数据采集 → 数据分析 → 报告 → 对比历史 → 闭环验证。

适用于任何嵌入式项目的传感器数据调试、执行器控制调试、协议通信调试。

## 职责

本工具是**测量工具**，不是维修工具：

| 做 | 不做 |
|----|------|
| 采集串口数据 | 生成 C 代码 |
| 分析数据（14 种分析） | 注入代码到源文件 |
| 解析心跳/寄存器值 | 搜索社区 |
| 对比历史数据 | 读 HAL 源码 |
| 读项目文档匹配已知问题 | 生成诊断步骤 |
| 写调试日志 | |
| 复位设备 | |

## 功能特性

| 功能 | 说明 |
|------|------|
| 📊 数据采集 | 文本、HEX、VOFA+、Modbus 协议 |
| 🔍 数据分析 | 14 种分析（见下方） |
| 💓 心跳解析 | 通用 key:value 解析，自动识别寄存器位域 |
| 📋 文档集成 | 自动搜索 docs/ 下的问题文档，匹配已知问题 |
| 📝 调试日志 | 自动写入 docs/debug_logs/ |
| 📈 数据可视化 | ASCII 图表、直方图、散点图 |
| 🔄 闭环调试 | 单轮或多轮自动迭代，烧录后验证 |
| 🔌 设备复位 | 7 种方法、bootloader 握手、自动探测 |
| ⚙️ 配置系统 | JSON 配置文件，自定义心跳前缀/寄存器位/规则 |

## 数据分析（14 种）

### 基础分析

| 分析 | 说明 |
|------|------|
| 范围检查 | 数据是否在有效范围内 |
| 跳变检测 | 数据异常跳变 |
| 连续性检查 | 采样间隔是否均匀 |
| 统计分析 | 均值/中位数/标准差/方差 |
| 趋势分析 | 上升/下降/平稳（线性回归） |
| 异常值检测 | Z-score 方法 |
| 周期性检测 | 自相关方法 |
| 稳定性分析 | 滑动标准差 |
| 分布分析 | 直方图/偏度/峰度 |

### 嵌入式专用分析

| 分析 | 说明 |
|------|------|
| 频率检测 | 零交越法估算信号频率 |
| 卡值检测 | ADC/传感器值长时间不变 |
| 时序间隙 | 采样间隔不均匀 |
| 心跳解析 | key:value + 寄存器位域自动展开 |
| DMA 状态 | 计数器递减检测、CIRC 位检测 |

## 快速开始

```bash
pip install pyserial
```

```bash
# 数据采集
python serial_loop.py --port COM3 --mode collect --duration 10

# 数据分析
python serial_loop.py --port COM3 --mode analyze --duration 10 --min-val 0 --max-val 100

# 采集前发送诊断命令
python serial_loop.py --port COM3 --mode collect --duration 10 --send-cmd "HB"

# 发送十六进制命令
python serial_loop.py --port COM3 --mode collect --duration 10 --send-hex AA550100FF

# 使用自定义配置
python serial_loop.py --port COM3 --mode collect --config my_config.json

# 闭环调试（采集 → 分析 → 报告 → 编译烧录 → 验证）
python serial_loop.py --port COM3 --mode loop --duration 10 --max-iterations 5

# 闭环 + 复位验证
python serial_loop.py --port COM3 --mode loop --duration 10 \
    --max-iterations 5 --reset-method dtr_rts --verify-reset

# 自动探测最佳复位方法
python serial_loop.py --port COM3 --mode reset --auto-detect
```

## 配置系统

通过 `--config` JSON 文件自定义行为：

```json
{
    "build_marker": "BUILD:",
    "heartbeat_prefixes": ["HB", "STATUS", "DBG"],
    "register_bits": {
        "en":    {"bit": 0,  "width": 1},
        "circ":  {"bit": 8,  "width": 1},
        "psize": {"bit": 11, "width": 2},
        "msize": {"bit": 13, "width": 2}
    },
    "register_name_pattern": "(?:DMA_)?CR|SR|CSR|ISR",
    "issue_rules": [
        {"field": "h",      "op": "<=", "value": 1, "type": "counter_stopped"},
        {"field": "*_circ", "op": "==",  "value": 0, "type": "no_circ"}
    ]
}
```

配置优先级：默认值 → JSON 文件 → CLI 参数

## 心跳解析

自动识别固件输出的诊断信息，解析 key:value 对和寄存器值：

```
固件输出: "HB H:1 C:1 | DAC CR:0x000034B1 NDTR:128"
自动解析: h=1, c=1, dac_cr=0x000034B1, ndtr=128
寄存器位: dac_cr_en=1, dac_cr_circ=1, dac_cr_psize=1, dac_cr_msize=1
```

支持任意前缀（通过配置或 `--heartbeat-prefix` 自定义）。

## 文档集成

- 自动搜索 `docs/` 目录下的问题文档（solutions-log.md、issues.md、problems.md 等）
- 将当前分析结果与已知问题对比
- 每轮分析后自动写入 `docs/debug_logs/`

## 闭环调试流程

```
1. 采集数据
2. 分析 + 报告 + 对比文档 + 写日志
3. 编译烧录 + 复位
4. 重新采集验证（对比前后数据）
   → 改善 → ✅ 修复成功
   → 不变 → ⚠️ 继续下一轮
   → 恶化 → ❌ 停止调试
```

## CLI 参数

```
--port PORT           串口号 (如 COM3)
--baud BAUD           波特率 (默认 115200)
--mode MODE           collect/analyze/loop/report/reset
--duration SECS       采集时长 (秒)
--protocol TYPE       text/hex/vofa
--min-val / --max-val 范围阈值
--jump-threshold      跳变阈值
--expected-interval   预期间隔
--input / --output    文件输入输出
--list                列出可用串口
--send-cmd STR        采集前发送文本命令（可多次使用）
--send-hex HEX        采集前发送十六进制数据
--check-build         检查 BUILD 时间戳
--config FILE         JSON 配置文件
--build-marker STR    编译时间戳前缀
--heartbeat-prefix STR 心跳行前缀（逗号分隔）

闭环:
--max-iterations N    迭代次数 (默认 5)
--timeout SECS        总超时 (默认 300)
--health-check        编译前健康检查
--brick-check         烧录前死机预防

复位:
--reset-method METHOD dtr/rts/dtr_rts/break/break_dtr/custom/bootloader
--verify-reset        复位后验证
--verify-pattern STR  验证匹配字符串
--auto-detect         自动探测最佳复位方法
--reset-log           查看复位日志
--bootloader          进入 STM32 bootloader
```

## 设备复位

| 方法 | 说明 | 适用场景 |
|------|------|----------|
| `dtr` | DTR → NRST | DTR 连接 NRST |
| `rts` | RTS → NRST | RTS 连接 NRST |
| `dtr_rts` | DTR+RTS 组合 | CH340/CP2102 |
| `break` | BREAK 信号 | 支持 BREAK 的模块 |
| `bootloader` | BOOT0 拉高复位 | 进入 STM32 bootloader |

## stm32-keil-workflow 集成

自动集成 [stm32-keil-workflow](https://github.com/pjjuihj/stm32-skills) 工具链：

| 功能 | 触发方式 |
|------|---------|
| 编译烧录 | `compile_and_flash()` |
| 健康检查 | `--health-check` |
| 死机预防 | `--brick-check` |
| 错误总结 | 编译失败自动调用 |
| 错误追踪 | `search_error_history()` |

## 依赖

| 依赖 | 必需 | 说明 |
|------|------|------|
| Python 3.8+ | ✅ | 运行脚本 |
| pyserial | ✅ | 串口通信 |
| stm32-keil-workflow | ⚠️ | 编译烧录（可选，无则跳过） |

## 安全约束

- ✅ 不全片擦除
- ✅ 不写 Option Bytes
- ✅ 不改读保护
- ✅ 烧录前死机预防检查
- ✅ 复位日志可追溯

## 相关项目

- [stm32-keil-workflow](https://github.com/pjjuihj/stm32-skills) - STM32 Keil 工作流自动化

## 许可证

MIT License
