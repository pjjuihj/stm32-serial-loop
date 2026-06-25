# STM32 串口闭环调试

STM32 串口闭环调试自动化工具：数据采集 → 数据分析 → 代码生成 → 代码注入 → 编译烧录 → 设备复位 → 验证修复 → 闭环。

## 功能特性

| 功能 | 说明 |
|------|------|
| 📊 数据采集 | 文本、HEX、VOFA+、Modbus 协议 |
| 🔍 数据分析 | 11 种分析：范围、跳变、连续性、趋势、异常值、周期性、稳定性、分布、统计、自动检测 |
| 📈 数据可视化 | ASCII 图表、直方图、散点图 |
| 🔧 代码生成 | 结构体封装滤波器（线程安全）：中值、滑动平均、EMA、卡尔曼、组合、巴特沃斯、自适应 |
| 💉 代码注入 | 自动注入到 CubeMX USER CODE 标记之间，防重复，自动备份 |
| 🔄 闭环调试 | 单轮或多轮自动迭代（`--max-iterations 20`） |
| 🔌 设备复位 | 7 种方法、bootloader 握手、自动探测、极性配置、复位日志 |
| 🏥 健康检查 | 编译前检查项目健康状态 |
| 🛡️ 死机预防 | 烧录前检查固件/配置安全性 |
| 📋 错误追踪 | 搜索历史、获取建议、记录修复 |
| 🔗 工作流集成 | 自动调用 stm32-keil-workflow 的编译、烧录、分析工具 |

## 快速开始

```bash
pip install pyserial
```

```bash
# 数据采集
python serial_loop.py --port COM3 --mode collect --duration 10

# 数据分析
python serial_loop.py --port COM3 --mode analyze --duration 10 --min-val 0 --max-val 100

# 单轮闭环
python serial_loop.py --port COM3 --mode loop --duration 10 --max-val 100

# 多轮自动闭环（20轮 + 健康检查 + 死机预防）
python serial_loop.py --auto . --port COM3 --mode loop --duration 10 \
    --max-iterations 20 --health-check --brick-check \
    --reset-method dtr_rts --verify-reset

# 自动探测最佳复位方法
python serial_loop.py --port COM3 --mode reset --auto-detect
```

## 工作模式

| 模式 | 说明 | 命令 |
|------|------|------|
| `collect` | 数据采集 | `--mode collect --duration 10` |
| `analyze` | 数据分析 | `--mode analyze --duration 10 --min-val 0 --max-val 100` |
| `loop` | 闭环调试（单轮/多轮） | `--mode loop --max-iterations 20` |
| `report` | 生成 Markdown 报告 | `--mode report --input data.json` |
| `reset` | 设备复位 | `--mode reset --reset-method dtr_rts` |

## CLI 参数

```
--port PORT             串口号 (如 COM3)
--baud BAUD             波特率 (默认 115200)
--mode MODE             collect/analyze/loop/report/reset
--auto DIR              自动检测项目 (如 --auto .)
--duration SECS         采集时长 (秒)
--protocol TYPE         text/hex/vofa
--min-val / --max-val   范围阈值
--jump-threshold        跳变阈值
--expected-interval     预期间隔
--input / --output      文件输入输出
--list                  列出可用串口
--source-file FILE      注入目标源文件
--auto-inject           自动注入修复代码
--max-iterations N      闭环迭代次数 (默认 5)
--timeout SECS          闭环总超时 (默认 300)
--health-check          编译前运行健康检查
--brick-check           烧录前运行死机预防
--reset-method METHOD   复位方法 (dtr/rts/dtr_rts/break/break_dtr/custom/bootloader)
--verify-reset          复位后验证设备响应
--verify-pattern STR    验证匹配的字符串
--max-retries N         复位重试次数 (默认 3)
--signal-delay SECS     复位信号持续时间
--boot-delay SECS       复位后等待启动时间
--invert-dtr            反转 DTR 极性
--invert-rts            反转 RTS 极性
--auto-detect           自动探测最佳复位方法
--reset-log             查看复位日志
--bootloader            进入 STM32 bootloader 模式
```

## 核心流程

```
┌───────────────────────────────────────────────────────────────┐
│                      串口闭环调试流程                          │
└───────────────────────────────────────────────────────────────┘
                                │
                                ▼
                      ┌──────────────────┐
                      │ 1. 串口数据采集   │
                      │    collect_data() │
                      └────────┬─────────┘
                               │
                               ▼
                      ┌──────────────────┐
                      │ 2. 数据分析       │
                      │    11 种分析算法  │
                      └────────┬─────────┘
                               │
                               ▼
                      ┌──────────────────┐
                      │ 3. 代码生成       │
                      │    结构体滤波器   │
                      └────────┬─────────┘
                               │
                               ▼
                      ┌──────────────────┐
                      │ 4. 代码注入       │
                      │    USER CODE 标记 │
                      └────────┬─────────┘
                               │
                               ▼
                      ┌──────────────────┐
                      │ 5. 编译烧录       │
                      │    workflow.py    │
                      └────────┬─────────┘
                               │
                               ▼
                      ┌──────────────────┐
                      │ 6. 设备复位       │
                      │    7 种方法       │
                      └────────┬─────────┘
                               │
                               ▼
                      ┌──────────────────┐
                      │ 7. 验证修复       │
                      │    串口数据采集   │
                      └────────┬─────────┘
                               │
                  ┌────────────┴────────────┐
                  │                         │
                  ▼                         ▼
           问题未解决                   问题解决
           回到步骤 2                   闭环完成
```

## 使用场景

### 传感器数据调试

```bash
# 温度传感器读数偶尔跳变为 0
python serial_loop.py --port COM3 --mode collect --duration 30 --filter "temp"
python serial_loop.py --port COM3 --mode analyze --duration 30 --min-val 0 --max-val 50
python serial_loop.py --port COM3 --mode loop --duration 30 --min-val 0 --max-val 50 \
    --max-iterations 5 --auto-inject --source-file main.c
```

### 电机转速调试

```bash
# 电机转速数据不稳定
python serial_loop.py --port COM3 --mode collect --duration 10 --filter "rpm"
python serial_loop.py --port COM3 --mode analyze --duration 10 --jump-threshold 100
python serial_loop.py --port COM3 --mode loop --duration 10 --max-iterations 5
```

### 协议通信调试

```bash
# 串口数据包丢失
python serial_loop.py --port COM3 --mode collect --duration 10 --protocol hex
python serial_loop.py --port COM3 --mode analyze --duration 10 --expected-interval 0.1
```

### 设备复位调试

```bash
# 自动探测最佳复位方法
python serial_loop.py --port COM3 --mode reset --auto-detect

# 某些 CH340 转接板需要反转极性
python serial_loop.py --port COM3 --mode reset --invert-dtr --verify-reset

# 进入 STM32 bootloader
python serial_loop.py --port COM3 --mode reset --bootloader

# 查看复位历史
python serial_loop.py --port COM3 --mode reset --reset-log
```

## 滤波算法（结构体封装，线程安全）

| 算法 | 结构体 | 适用场景 |
|------|--------|---------|
| 中值滤波 | `MedianFilter` | 去除脉冲噪声 |
| 滑动平均 | `MovingAverage` | 平滑数据 |
| 指数移动平均 | `EMAFilter` | 实时平滑 |
| 卡尔曼滤波 | `KalmanFilter` | 高精度滤波 |
| 加权平均 | `WeightedAverage` | 加权平滑 |
| 组合滤波 | `CombinationFilter` | 中值 + 滑动平均 |
| 巴特沃斯 | `ButterworthFilter` | 低通滤波 |
| 自适应(LMS) | `AdaptiveFilter` | 复杂环境 |

```c
// 示例：中值滤波（线程安全，每个传感器独立实例）
MedianFilter mf;
median_filter_init(&mf);
float filtered = median_filter_update(&mf, raw_value);
```

## 设备复位

| 方法 | 说明 | 适用场景 |
|------|------|----------|
| `dtr` | DTR → NRST | DTR 连接 NRST 的模块 |
| `rts` | RTS → NRST | RTS 连接 NRST 的模块 |
| `dtr_rts` | DTR+RTS 组合 | CH340/CP2102 等常见转接板 |
| `break` | BREAK 信号 | 支持 BREAK 的模块 |
| `break_dtr` | BREAK+DTR | 某些特殊板子 |
| `custom` | DTR+RTS 同时操作 | 自定义硬件 |
| `bootloader` | BOOT0 拉高复位 | 进入 STM32 bootloader（0x7F 握手） |

## stm32-keil-workflow 集成

自动集成 [stm32-keil-workflow](https://github.com/pjjuihj/stm32-skills) 工具链：

| 集成功能 | 调用脚本 | 触发方式 |
|---------|---------|---------|
| 编译烧录 | `workflow.py --auto . --steps compile,flash` | `compile_and_flash()` |
| 健康检查 | `health_check.py --project .` | `--health-check` |
| 死机预防 | `brick_prevention.py --auto .` | `--brick-check` |
| 错误总结 | `error_summary.py --auto . --text` | 编译失败自动调用 |
| 错误追踪 | `error_tracker.py --search/--suggest/--record` | Python API |
| 技术规范 | `tech_spec.py --auto . --text` | Python API |
| 项目检测 | `detect_config.py --scan .` | `--auto .` |

## 依赖

| 依赖 | 必需 | 说明 |
|------|------|------|
| Python 3.8+ | ✅ | 运行脚本 |
| pyserial | ✅ | 串口通信 |
| stm32-keil-workflow | ⚠️ | 编译烧录工作流（可选，无则跳过编译烧录） |

## 安全约束

- ✅ 不全片擦除
- ✅ 不写 Option Bytes
- ✅ 不改读保护
- ✅ 代码修改遵循最小改动原则
- ✅ 烧录前必须验证固件
- ✅ 代码注入前自动备份（`.bak`）
- ✅ 复位日志可追溯（`--reset-log`）
- ✅ 烧录前死机预防检查（`--brick-check`）

## 相关项目

- [stm32-keil-workflow](https://github.com/pjjuihj/stm32-skills) - STM32 Keil 工作流自动化

## 许可证

MIT License
