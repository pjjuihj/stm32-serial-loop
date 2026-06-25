---
name: stm32-serial-loop
description: >
  STM32 串口闭环调试自动化。通过串口采集数据，分析数据问题（范围异常、跳变、不连续），
  自动定位代码问题，修改代码，编译烧录，验证修复效果，形成闭环。
  适用于传感器数据调试、执行器控制调试、协议通信调试等场景。
  支持文本数据、HEX 数据包、VOFA+ 协议等多种格式。
  使用场景：STM32 串口调试、数据流分析、固件调试、闭环测试。
---

# STM32 串口闭环调试

串口数据采集 → 数据分析 → 问题定位 → 代码修改 → 编译烧录 → 验证修复 → 闭环

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

## 快速开始

### 一键闭环调试

```bash
# 串口数据采集（10秒）
python serial_loop.py --port COM3 --mode collect --duration 10

# 数据分析
python serial_loop.py --port COM3 --mode analyze --duration 10 --min-val 0 --max-val 100

# 完整闭环（采集 → 分析 → 报告）
python serial_loop.py --port COM3 --mode loop --duration 10 --max-val 100
```

### 分步调试

```bash
# 步骤 1：数据采集
python serial_loop.py --port COM3 --mode collect --duration 30 --output data.json

# 步骤 2：数据分析
python serial_loop.py --mode analyze --input data.json --min-val 0 --max-val 100

# 步骤 3：查看报告
python serial_loop.py --mode report --input data.json
```

## 脚本说明

| 脚本 | 功能 | 常用命令 |
|------|------|---------|
| `serial_loop.py` | **闭环调试主脚本** | `--port COM3 --mode loop` |
| `workflow.py` | 编译烧录工作流（外部依赖） | `--auto . --steps compile,flash` |
| `error_tracker.py` | 错误追踪（外部依赖） | `--search "关键词"` |
| `tech_spec.py` | 技术规范（外部依赖） | `--auto . --text` |

> 外部依赖脚本位于 `stm32-keil-workflow/scripts/` 目录。

## stm32-keil-workflow 集成

`serial_loop.py` 自动集成 `stm32-keil-workflow` 的工具链：

| 集成功能 | 调用脚本 | 触发条件 |
|---------|---------|---------|
| 编译烧录 | `workflow.py --auto . --steps compile,flash` | `compile_and_flash()` |
| 健康检查 | `health_check.py --project .` | `--health-check` 参数 |
| 死机预防 | `brick_prevention.py --auto .` | `--brick-check` 参数 |
| 错误总结 | `error_summary.py --auto . --text` | 编译失败时自动调用 |
| 错误追踪 | `error_tracker.py --search/--suggest/--record` | `search_error_history()` 等 |
| 技术规范 | `tech_spec.py --auto . --text` | `get_project_config()` |
| CubeMX 指南 | `cubemx_guide.py --peripheral USART1` | `get_peripheral_config()` |
| 引脚检查 | `pin_checker.py --ioc project.ioc` | `check_pin_conflict()` |
| 项目检测 | `detect_config.py --scan .` | `--auto .` 参数 |

### 使用示例

```bash
# 自动检测项目 + 数据采集
python serial_loop.py --auto . --port COM3 --mode collect --duration 10

# 闭环调试 + 烧录前健康检查 + 死机预防
python serial_loop.py --auto . --port COM3 --mode loop --duration 10 --health-check --brick-check

# 编译失败时自动获取错误总结
python serial_loop.py --auto . --port COM3 --mode loop --max-iterations 5
```

## 工作模式

| 模式 | 说明 | 命令 |
|------|------|------|
| `collect` | 数据采集 | `--mode collect --duration 10` |
| `analyze` | 数据分析 | `--mode analyze --duration 10` |
| `loop` | 闭环调试（单轮或多轮） | `--mode loop --duration 10 --max-iterations 20` |
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
--source-file FILE    要注入代码的源文件 (如 main.c)
--auto-inject         自动注入修复代码到源文件
--max-iterations N    闭环最大迭代次数 (默认 5)
--timeout SECONDS     闭环总超时 (默认 300)

复位相关:
--reset-method METHOD 复位方法 (dtr/rts/dtr_rts/break/break_dtr/custom/bootloader)
--verify-reset        复位后验证设备响应
--verify-pattern STR  验证匹配的字符串 (如 'STM32')
--max-retries N       复位最大重试次数 (默认 3)
--signal-delay SECS   信号持续时间 (默认 0.1)
--boot-delay SECS     启动等待时间 (默认 0.5)
--invert-dtr          反转 DTR 极性
--invert-rts          反转 RTS 极性
--auto-detect         自动探测最佳复位方法
--reset-log           查看复位日志
--bootloader          进入 STM32 bootloader 模式
```

## 数据分析功能

### 范围检查

```bash
# 检查数据是否在有效范围内
python serial_loop.py --port COM3 --mode analyze --duration 10 --min-val 0 --max-val 100
```

### 跳变检测

```bash
# 检测数据异常跳变
python serial_loop.py --port COM3 --mode analyze --duration 10 --jump-threshold 20
```

### 连续性检查

```bash
# 检查数据是否连续（等间隔）
python serial_loop.py --port COM3 --mode analyze --duration 10 --expected-interval 1.0
```

### 趋势分析

```bash
# 分析数据趋势（上升/下降/平稳）
python serial_loop.py --port COM3 --mode analyze --duration 30
```

### 异常值检测

```bash
# 检测异常值（基于标准差）
python serial_loop.py --port COM3 --mode analyze --duration 10
```

### 周期性检测

```bash
# 检测数据周期性
python serial_loop.py --port COM3 --mode analyze --duration 30
```

## 闭环调试工作流

### 自动闭环调试

```bash
# 单轮闭环（采集 → 分析 → 报告）
python serial_loop.py --port COM3 --mode loop --duration 10 --max-val 100

# 多轮自动闭环（采集 → 分析 → 注入 → 编译烧录 → 复位 → 验证 → 重复）
python serial_loop.py --port COM3 --mode loop --duration 10 --max-iterations 20 --timeout 600

# 多轮闭环 + 代码注入 + 复位验证
python serial_loop.py --port COM3 --mode loop --duration 10 --max-iterations 5 \
    --auto-inject --source-file main.c \
    --reset-method dtr_rts --verify-reset
```

**单轮流程**（`--max-iterations 1`）：
1. 数据采集
2. 数据分析
3. 生成报告
4. 生成修复代码（可选注入）

**多轮流程**（`--max-iterations > 1`）：
1. 数据采集
2. 数据分析
3. 生成修复代码
4. 注入代码到源文件（如果 `--auto-inject`）
5. 编译烧录
6. 复位设备
7. 验证修复
8. 重复直到问题解决或达到上限

### 场景 1：传感器数据异常

```
问题：温度传感器读数偶尔跳变为 0
流程：
1. 采集数据 → 发现跳变
2. 分析 → 定位跳变时间点
3. 检查代码 → ADC 读取函数
4. 修改 → 添加滤波算法
5. 编译烧录 → 验证修复
```

### 场景 2：执行器响应异常

```
问题：电机转速不稳定
流程：
1. 采集数据 → 发现转速波动大
2. 分析 → 计算标准差
3. 检查代码 → PWM 输出函数
4. 修改 → 调整 PID 参数
5. 编译烧录 → 验证修复
```

### 场景 3：协议通信错误

```
问题：串口数据包丢失
流程：
1. 采集数据 → 发现数据包不连续
2. 分析 → 定位丢失时间点
3. 检查代码 → 串口中断处理
4. 修改 → 增加缓冲区大小
5. 编译烧录 → 验证修复
```

## AI 自动修复

### 自动修复流程

```
1. 分析数据问题
   ↓
2. 查找错误历史
   python error_tracker.py --search "跳变"
   ↓
3. 获取修复建议
   python error_tracker.py --suggest "数据跳变"
   ↓
4. 定位代码问题
   - 检查 ADC 读取函数
   - 检查滤波算法
   - 检查中断处理
   ↓
5. 自动修改代码
   - 添加滤波算法
   - 增加缓冲区
   - 调整参数
   ↓
6. 编译烧录
   python workflow.py --auto . --steps compile,flash
   ↓
7. 验证修复
   python serial_loop.py --port COM3 --mode loop --duration 30
```

### 代码修改策略

| 问题类型 | 修改策略 |
|---------|---------|
| 数据跳变 | 添加中值滤波、卡尔曼滤波 |
| 数据范围异常 | 添加范围检查、限幅处理 |
| 数据不连续 | 增加缓冲区、优化中断处理 |
| 数据延迟 | 优化代码效率、降低采样率 |
| 数据丢失 | 增加 FIFO 缓冲、优化 DMA 配置 |

## 自动修复代码生成

根据数据分析结果，自动生成修复代码：

```bash
# 完整闭环（采集 → 分析 → 生成修复代码）
python serial_loop.py --port COM3 --mode loop --duration 10 --max-val 100
```

### 支持的修复代码

| 问题类型 | 修复代码 | 说明 |
|---------|---------|------|
| 范围异常 | `range_check()` | 限幅处理 |
| 数据跳变 | `median_filter()` | 中值滤波 |
| 数据不连续 | `moving_average()` | 滑动平均 |
| 脉冲噪声 | `combination_filter()` | 组合滤波 |
| 数据平滑 | `ema_filter()` | 指数移动平均 |
| 加权平均 | `weighted_average()` | 加权平均 |
| 卡尔曼滤波 | `kalman_update()` | 卡尔曼滤波 |

## 滤波算法模板（结构体封装，线程安全）

### 中值滤波

```c
#define MEDIAN_FILTER_SIZE 5

typedef struct {
    float buffer[MEDIAN_FILTER_SIZE];
    int index;
} MedianFilter;

void median_filter_init(MedianFilter *mf) {
    for (int i = 0; i < MEDIAN_FILTER_SIZE; i++) mf->buffer[i] = 0;
    mf->index = 0;
}

float median_filter_update(MedianFilter *mf, float new_value) {
    float sorted[MEDIAN_FILTER_SIZE];
    mf->buffer[mf->index] = new_value;
    mf->index = (mf->index + 1) % MEDIAN_FILTER_SIZE;
    memcpy(sorted, mf->buffer, sizeof(mf->buffer));
    for (int i = 0; i < MEDIAN_FILTER_SIZE - 1; i++)
        for (int j = i + 1; j < MEDIAN_FILTER_SIZE; j++)
            if (sorted[i] > sorted[j]) { float t = sorted[i]; sorted[i] = sorted[j]; sorted[j] = t; }
    return sorted[MEDIAN_FILTER_SIZE / 2];
}
// 使用: MedianFilter mf; median_filter_init(&mf); float v = median_filter_update(&mf, raw);
```

### 滑动平均滤波

```c
#define MOVING_AVERAGE_SIZE 10

typedef struct {
    float buffer[MOVING_AVERAGE_SIZE];
    int index;
    float sum;
} MovingAverage;

void moving_average_init(MovingAverage *ma) {
    for (int i = 0; i < MOVING_AVERAGE_SIZE; i++) ma->buffer[i] = 0;
    ma->index = 0; ma->sum = 0;
}

float moving_average_update(MovingAverage *ma, float new_value) {
    ma->sum -= ma->buffer[ma->index];
    ma->buffer[ma->index] = new_value;
    ma->sum += new_value;
    ma->index = (ma->index + 1) % MOVING_AVERAGE_SIZE;
    return ma->sum / MOVING_AVERAGE_SIZE;
}
// 使用: MovingAverage ma; moving_average_init(&ma); float v = moving_average_update(&ma, raw);
```

### 指数移动平均滤波

```c
typedef struct {
    float last_value;
    float alpha;
    int initialized;
} EMAFilter;

void ema_filter_init(EMAFilter *ef, float alpha) {
    ef->last_value = 0; ef->alpha = alpha; ef->initialized = 0;
}

float ema_filter_update(EMAFilter *ef, float new_value) {
    if (!ef->initialized) { ef->last_value = new_value; ef->initialized = 1; return new_value; }
    ef->last_value = ef->alpha * new_value + (1 - ef->alpha) * ef->last_value;
    return ef->last_value;
}
// 使用: EMAFilter ef; ema_filter_init(&ef, 0.1); float v = ema_filter_update(&ef, raw);
```

### 卡尔曼滤波

```c
typedef struct {
    float q, r, x, p, k;
} KalmanFilter;

void kalman_init(KalmanFilter *kf, float q, float r, float initial_value) {
    kf->q = q; kf->r = r; kf->x = initial_value; kf->p = 1.0; kf->k = 0;
}

float kalman_update(KalmanFilter *kf, float measurement) {
    kf->p += kf->q;
    kf->k = kf->p / (kf->p + kf->r);
    kf->x += kf->k * (measurement - kf->x);
    kf->p *= (1 - kf->k);
    return kf->x;
}
// 使用: KalmanFilter kf; kalman_init(&kf, 0.01, 0.1, 0.0); float v = kalman_update(&kf, raw);
```

### 组合滤波（中值 + 滑动平均）

```c
typedef struct {
    MedianFilter mf;
    MovingAverage ma;
} CombinationFilter;

void combination_filter_init(CombinationFilter *cf) {
    median_filter_init(&cf->mf);
    moving_average_init(&cf->ma);
}

float combination_filter_update(CombinationFilter *cf, float new_value) {
    return moving_average_update(&cf->ma, median_filter_update(&cf->mf, new_value));
}
// 使用: CombinationFilter cf; combination_filter_init(&cf); float v = combination_filter_update(&cf, raw);
```

## 设备复位

### 复位方法

| 方法 | 说明 | 适用场景 |
|------|------|----------|
| `dtr` | DTR 信号复位 | DTR 连接 NRST 的模块 |
| `rts` | RTS 信号复位 | RTS 连接 NRST 的模块 |
| `dtr_rts` | DTR+RTS 组合 | CH340/CP2102 等常见 USB 转串口 |
| `break` | BREAK 信号复位 | 支持 BREAK 的模块 |
| `break_dtr` | BREAK+DTR 组合 | 某些特殊板子 |
| `custom` | DTR+RTS 同时操作 | 自定义硬件 |
| `bootloader` | 进入 STM32 bootloader | BOOT0 拉高后复位 |

### 复位示例

```bash
# 普通复位
python serial_loop.py --port COM3 --mode reset

# 自动探测最佳复位方法
python serial_loop.py --port COM3 --mode reset --auto-detect

# DTR+RTS 组合复位 + 验证
python serial_loop.py --port COM3 --mode reset --reset-method dtr_rts --verify-reset

# 反转极性（某些 CH340 转接板）
python serial_loop.py --port COM3 --mode reset --invert-dtr --verify-reset

# 进入 bootloader 模式（发送 0x7F 握手）
python serial_loop.py --port COM3 --mode reset --bootloader

# 调整时序（慢速设备）
python serial_loop.py --port COM3 --mode reset --signal-delay 0.3 --boot-delay 2.0

# 查看复位日志
python serial_loop.py --port COM3 --mode reset --reset-log
```

### 复位验证

复位后自动检测设备启动标志：
- 高置信度：`STM32`, `Ready`, `Boot_OK`, `SystemInit`, `running`
- 低置信度（需更多数据）：`OK`, `Init`, `start`
- bootloader 模式：检测 `0x79` ACK 响应
- 自定义：`--verify-pattern "YourBanner"`

### 自动探测

```bash
python serial_loop.py --port COM3 --mode reset --auto-detect
```

依次尝试 dtr → rts → dtr_rts → break → custom，找到第一个能成功的方法。

## 代码注入

支持将生成的修复代码自动注入到 STM32 源文件中（CubeMX `USER CODE` 标记之间）。

```bash
# 单轮闭环 + 代码注入
python serial_loop.py --port COM3 --mode loop --duration 10 --auto-inject --source-file main.c

# 多轮闭环 + 代码注入
python serial_loop.py --port COM3 --mode loop --duration 10 --max-iterations 5 --auto-inject --source-file Src/main.c
```

注入规则：
- 查找 `/* USER CODE BEGIN 0 */` 和 `/* USER CODE END 0 */` 标记
- 自动检测重复（函数名已存在则跳过）
- 自动备份原文件为 `.bak`
- CubeMX 重新生成代码时不会丢失注入的代码

## 集成功能

### Python API

```python
from serial_loop import (
    collect_data, analyze_data, generate_fix_code,
    inject_code_to_source, compile_and_flash,
    reset_device, reset_with_retry, auto_detect_reset_method,
    enter_bootloader, exit_bootloader, stm32_system_reset,
    get_reset_log,
)

# 数据采集
data = collect_data(port="COM3", duration=10)

# 数据分析
analysis = analyze_data(data, min_val=0, max_val=100)

# 生成修复代码
fixes = generate_fix_code(analysis)

# 注入代码到源文件
inject_code_to_source("main.c", fixes["fixes"][0]["code"])

# 复位设备
reset_device("COM3", method="dtr_rts", verify=True)

# 自动探测
result = auto_detect_reset_method("COM3")
print(result["recommended_method"])
```

## 依赖

| 依赖 | 必需 | 说明 |
|------|------|------|
| Python 3.8+ | ✅ | 运行脚本 |
| pyserial | ✅ | 串口通信 |
| Keil MDK-ARM | ✅ | 编译工具链 |
| stm32-keil-workflow | ✅ | 编译烧录工作流 |

## 函数参考

### 数据采集

| 函数 | 说明 |
|------|------|
| `collect_data()` | 采集串口数据（支持 text/hex/vofa 协议） |
| `parse_values()` | 从文本中提取数值（优先匹配 key:value 格式） |
| `parse_protocol()` | 解析协议数据（text/hex/vofa/modbus） |
| `parse_named_values()` | 解析命名值（如 `temp:25.5,humidity:60`） |

### 数据分析

| 函数 | 说明 |
|------|------|
| `analyze_data()` | 综合分析（范围+跳变+连续性+统计） |
| `analyze_range()` | 范围分析（空列表安全） |
| `analyze_jumps()` | 跳变分析（空列表安全） |
| `analyze_continuity()` | 连续性分析 |
| `analyze_trend()` | 趋势分析（线性回归 + R²） |
| `analyze_outliers()` | 异常值检测（Z-score） |
| `analyze_periodicity()` | 周期性检测（自相关） |
| `analyze_stability()` | 稳定性分析（滑动标准差） |
| `analyze_distribution()` | 分布分析（偏度/峰度） |
| `analyze_statistics()` | 统计分析（均值/中位数/方差） |
| `auto_detect_issues()` | 自动检测问题 + 生成修复建议 |

### 数据可视化

| 函数 | 说明 |
|------|------|
| `plot_ascii_chart()` | ASCII 图表 |
| `plot_ascii_histogram()` | ASCII 直方图 |
| `plot_ascii_scatter()` | ASCII 散点图 |

### 代码生成（结构体封装，线程安全）

| 函数 | 说明 |
|------|------|
| `generate_fix_code()` | 根据分析结果生成修复代码 |
| `generate_range_check_code()` | 范围检查代码 |
| `generate_median_filter_code()` | 中值滤波代码（`MedianFilter` 结构体） |
| `generate_moving_average_code()` | 滑动平均代码（`MovingAverage` 结构体） |
| `generate_ema_filter_code()` | 指数移动平均代码（`EMAFilter` 结构体） |
| `generate_kalman_filter_code()` | 卡尔曼滤波代码（`KalmanFilter` 结构体） |
| `generate_weighted_average_code()` | 加权平均代码（`WeightedAverage` 结构体） |
| `generate_combination_filter_code()` | 组合滤波代码（`CombinationFilter` 结构体） |
| `generate_limit_filter_code()` | 限幅滤波代码 |
| `generate_adaptive_filter_code()` | 自适应滤波代码（LMS 算法） |
| `generate_butterworth_filter_code()` | 巴特沃斯滤波代码 |
| `generate_savitzky_golay_code()` | Savitzky-Golay 滤波代码 |
| `generate_outlier_detection_code()` | 异常值检测代码（Z-score） |
| `inject_code_to_source()` | 将代码注入到源文件（CubeMX USER CODE 标记） |

### 设备复位

| 函数 | 说明 |
|------|------|
| `reset_device()` | 复位设备（支持 7 种方法、极性配置、验证） |
| `reset_with_retry()` | 带重试的复位（失败自动切换方法） |
| `auto_detect_reset_method()` | 自动探测最佳复位方法 |
| `enter_bootloader()` | 进入 STM32 bootloader 模式（0x7F 握手） |
| `exit_bootloader()` | 退出 bootloader（正常复位） |
| `stm32_system_reset()` | 通过 bootloader Go 命令复位 |
| `get_reset_log()` | 获取复位日志 |
| `_verify_reset()` | 验证复位是否成功 |
| `_check_port_available()` | 检查串口是否可用 |

### 工作流集成

| 函数 | 说明 |
|------|------|
| `compile_and_flash()` | 编译烧录 + 复位（支持复位方法和验证） |
| `auto_loop()` | 自动闭环（支持代码注入） |
| `run_workflow_step()` | 运行工作流步骤 |

### 数据日志

| 函数 | 说明 |
|------|------|
| `save_data_log()` | 保存数据日志 |
| `load_data_log()` | 加载数据日志 |
| `list_data_logs()` | 列出数据日志 |
| `compare_with_history()` | 与历史数据对比 |

### 集成功能

| 函数 | 说明 |
|------|------|
| `search_error_history()` | 搜索错误历史（调用 error_tracker.py） |
| `get_fix_suggestions_from_history()` | 获取修复建议 |
| `record_error_fix()` | 记录修复 |
| `get_project_config()` | 获取项目配置（调用 tech_spec.py） |
| `get_peripheral_config()` | 获取外设配置 |
| `check_pin_conflict()` | 检查引脚冲突 |

## 示例

### 示例 1：传感器数据调试

```bash
# 采集温度传感器数据
python serial_loop.py --port COM3 --mode collect --duration 30 --filter "temp"

# 分析数据
python serial_loop.py --port COM3 --mode analyze --duration 30 --min-val 0 --max-val 50

# 自动闭环调试
python serial_loop.py --port COM3 --mode auto-loop --duration 30 --min-val 0 --max-val 50 --max-iterations 5
```

### 示例 2：电机转速调试

```bash
# 采集转速数据
python serial_loop.py --port COM3 --mode collect --duration 10 --filter "rpm"

# 分析稳定性
python serial_loop.py --port COM3 --mode analyze --duration 10 --jump-threshold 100

# 生成修复代码
python serial_loop.py --mode report --input data.json --suggest
```

### 示例 3：协议通信调试

```bash
# 采集协议数据
python serial_loop.py --port COM3 --mode collect --duration 10 --protocol hex

# 分析数据包
python serial_loop.py --port COM3 --mode analyze --duration 10 --protocol hex

# 检查连续性
python serial_loop.py --port COM3 --mode analyze --duration 10 --expected-interval 0.1
```

## 故障排除

| 问题 | 解决方案 |
|------|---------|
| 串口连接失败 | `--list` 查看可用串口；检查 USB 连接和驱动 |
| 串口被占用 | 关闭其他串口监视器；检查设备管理器 |
| 数据采集超时 | 增加 `--duration`；检查设备是否在发送数据 |
| 分析结果不准确 | 调整 `--min-val`/`--max-val`/`--jump-threshold` |
| 编译烧录失败 | 检查项目配置、Keil 安装、ST-LINK 连接 |
| 复位失败 | `--auto-detect` 自动探测；尝试 `--invert-dtr`/`--invert-rts` |
| 复位验证失败 | 增加 `--boot-delay 2.0`；`--verify-pattern` 匹配你的启动信息 |
| bootloader 进入失败 | 检查 BOOT0 引脚连接；尝试 `--signal-delay 0.3` |
| 代码注入失败 | 确认源文件有 `/* USER CODE BEGIN */` 标记 |
| 闭环调试卡住 | 减少 `--max-iterations`；设置 `--timeout` |

## 安全约束

- **不全片擦除** — 只烧录指定固件
- **不写 Option Bytes** — 避免锁定芯片
- **不改读保护** — 保持原有 RDP 级别
- **代码修改遵循最小改动原则** — 只添加必要的滤波/检查代码
- **烧录前必须验证固件** — 编译成功后才烧录
- **代码注入前自动备份** — 原文件保存为 `.bak`
- **复位日志可追溯** — `--reset-log` 查看历史
