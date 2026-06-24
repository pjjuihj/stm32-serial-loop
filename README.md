# STM32 串口闭环调试

STM32 串口闭环调试自动化工具，通过串口采集数据、分析问题、生成修复代码、编译烧录、验证修复，形成完整的调试闭环。

## 功能特性

| 功能 | 说明 |
|------|------|
| 📊 数据采集 | 支持文本、HEX、VOFA+、Modbus 协议 |
| 🔍 数据分析 | 范围、跳变、连续性、趋势、异常值、周期性、稳定性、分布 |
| 📈 数据可视化 | ASCII 图表、直方图、散点图 |
| 🔧 代码生成 | 中值滤波、滑动平均、卡尔曼滤波等 |
| 🔄 闭环调试 | 采集 → 分析 → 修复 → 烧录 → 验证 |
| 📝 错误追踪 | 搜索历史、获取建议、记录修复 |
| 📋 技术规范 | 项目配置、外设配置、引脚冲突检查 |

## 快速开始

### 安装依赖

```bash
pip install pyserial
```

### 基本使用

```bash
# 数据采集（10秒）
python serial_loop.py --port COM3 --mode collect --duration 10

# 数据分析
python serial_loop.py --port COM3 --mode analyze --duration 10 --min-val 0 --max-val 100

# 完整闭环（采集 → 分析 → 报告）
python serial_loop.py --port COM3 --mode loop --duration 10 --max-val 100

# 自动闭环调试（最多 5 轮）
python serial_loop.py --port COM3 --mode auto-loop --duration 10 --max-iterations 5
```

## 工作模式

| 模式 | 说明 | 命令 |
|------|------|------|
| `collect` | 数据采集 | `--mode collect --duration 10` |
| `analyze` | 数据分析 | `--mode analyze --duration 10` |
| `loop` | 闭环调试 | `--mode loop --duration 10` |
| `auto-loop` | 自动闭环 | `--mode auto-loop --duration 10 --max-iterations 5` |
| `batch` | 批量测试 | `--mode batch --test-file tests.json` |
| `report` | 生成报告 | `--mode report --input data.json` |

## 核心流程

```
┌─────────────────────────────────────────────────────────────┐
│                    串口闭环调试流程                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 1. 串口数据采集  │
                    │    serial_loop  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 2. 数据分析      │
                    │    范围/跳变/连续 │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 3. 问题定位      │
                    │    错误追踪      │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 4. 代码修改      │
                    │    AI 自动修改   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 5. 编译烧录      │
                    │    workflow.py   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 6. 验证修复      │
                    │    串口数据采集  │
                    └────────┬────────┘
                             │
                             └──→ 问题未解决 → 回到步骤 2
                             │
                             └──→ 问题解决 → 闭环完成
```

## 使用场景

### 场景 1：传感器数据调试

```bash
# 温度传感器读数偶尔跳变为 0
python serial_loop.py --port COM3 --mode collect --duration 30 --filter "temp"
python serial_loop.py --port COM3 --mode analyze --duration 30 --min-val 0 --max-val 50
python serial_loop.py --port COM3 --mode auto-loop --duration 30 --min-val 0 --max-val 50
```

### 场景 2：电机转速调试

```bash
# 电机转速数据不稳定
python serial_loop.py --port COM3 --mode collect --duration 10 --filter "rpm"
python serial_loop.py --port COM3 --mode analyze --duration 10 --jump-threshold 100
python serial_loop.py --mode report --input data.json --suggest
```

### 场景 3：协议通信调试

```bash
# 串口数据包丢失
python serial_loop.py --port COM3 --mode collect --duration 10 --protocol hex
python serial_loop.py --port COM3 --mode analyze --duration 10 --protocol hex
python serial_loop.py --port COM3 --mode analyze --duration 10 --expected-interval 0.1
```

## 数据分析功能

| 功能 | 说明 | 命令 |
|------|------|------|
| 范围检查 | 检查数据是否在有效范围内 | `--min-val 0 --max-val 100` |
| 跳变检测 | 检测数据异常跳变 | `--jump-threshold 20` |
| 连续性检查 | 检查数据是否连续 | `--expected-interval 1.0` |
| 趋势分析 | 分析数据趋势 | 自动分析 |
| 异常值检测 | 检测异常值 | 自动分析 |
| 周期性检测 | 检测数据周期性 | 自动分析 |
| 稳定性分析 | 分析数据稳定性 | 自动分析 |
| 分布分析 | 分析数据分布 | 自动分析 |

## 滤波算法

| 算法 | 适用场景 | 代码函数 |
|------|---------|---------|
| 中值滤波 | 去除脉冲噪声 | `median_filter()` |
| 滑动平均 | 平滑数据 | `moving_average()` |
| 指数移动平均 | 实时平滑 | `ema_filter()` |
| 卡尔曼滤波 | 高精度滤波 | `kalman_update()` |
| 自适应滤波 | 复杂环境 | `adaptive_update()` |
| 巴特沃斯滤波 | 低通滤波 | `butterworth_update()` |

## 集成功能

### 错误追踪

```bash
# 搜索错误历史
python serial_loop.py --search "数据跳变"

# 获取修复建议
python serial_loop.py --suggest "数据不稳定"

# 记录修复
python serial_loop.py --record --error "数据跳变" --fix "添加中值滤波"
```

### 技术规范

```bash
# 获取项目配置
python serial_loop.py --config

# 获取外设配置
python serial_loop.py --peripheral USART1

# 检查引脚冲突
python serial_loop.py --check-pins
```

## 依赖

| 依赖 | 必需 | 说明 |
|------|------|------|
| Python 3.8+ | ✅ | 运行脚本 |
| pyserial | ✅ | 串口通信 |
| Keil MDK-ARM | ✅ | 编译工具链 |
| stm32-keil-workflow | ✅ | 编译烧录工作流 |

## 安全约束

- 不全片擦除
- 不写 Option Bytes
- 不改读保护
- 代码修改遵循最小改动原则
- 烧录前必须验证固件

## 相关项目

- [stm32-keil-workflow](https://github.com/pjjuihj/stm32-skills) - STM32 Keil 工作流自动化

## 许可证

MIT License
