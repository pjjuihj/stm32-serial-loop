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
| `serial_debug.py` | 串口调试助手 | `--port COM3 --mode analyze` |
| `serial_monitor.py` | 串口监控 | `--port COM3 --mode monitor` |
| `workflow.py` | 编译烧录工作流 | `--auto . --steps compile,flash` |
| `error_tracker.py` | 错误追踪 | `--search "关键词"` |
| `tech_spec.py` | 技术规范 | `--auto . --text` |

## 工作模式

| 模式 | 说明 | 命令 |
|------|------|------|
| `collect` | 数据采集 | `--mode collect --duration 10` |
| `analyze` | 数据分析 | `--mode analyze --duration 10` |
| `loop` | 闭环调试 | `--mode loop --duration 10` |
| `auto-loop` | 自动闭环 | `--mode auto-loop --duration 10 --max-iterations 5` |
| `batch` | 批量测试 | `--mode batch --test-file tests.json` |
| `report` | 生成报告 | `--mode report --input data.json` |

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
# 自动闭环调试（采集 → 分析 → 修复 → 烧录 → 复位 → 验证）
python serial_loop.py --port COM3 --mode auto-loop --duration 10 --max-val 100 --max-iterations 5
```

**流程**：
1. 数据采集
2. 数据分析
3. 生成修复代码
4. 编译烧录
5. 复位设备
6. 验证修复
7. 重复直到问题解决

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

## 滤波算法模板

### 中值滤波

```c
// 中值滤波（窗口大小 5）
float median_filter(float new_value) {
    static float buffer[5] = {0};
    static int index = 0;
    float sorted[5];

    buffer[index] = new_value;
    index = (index + 1) % 5;

    memcpy(sorted, buffer, sizeof(buffer));
    for (int i = 0; i < 4; i++) {
        for (int j = i + 1; j < 5; j++) {
            if (sorted[i] > sorted[j]) {
                float temp = sorted[i];
                sorted[i] = sorted[j];
                sorted[j] = temp;
            }
        }
    }

    return sorted[2];
}
```

### 滑动平均滤波

```c
// 滑动平均滤波（窗口大小 10）
float moving_average(float new_value) {
    static float buffer[10] = {0};
    static int index = 0;
    static float sum = 0;

    sum -= buffer[index];
    buffer[index] = new_value;
    sum += new_value;
    index = (index + 1) % 10;

    return sum / 10;
}
```

### 指数移动平均滤波

```c
// 指数移动平均滤波 (EMA)
float ema_filter(float new_value, float alpha) {
    static float last_value = 0;
    static int initialized = 0;

    if (!initialized) {
        last_value = new_value;
        initialized = 1;
        return new_value;
    }

    last_value = alpha * new_value + (1 - alpha) * last_value;
    return last_value;
}
```

### 卡尔曼滤波

```c
// 卡尔曼滤波
typedef struct {
    float q; // 过程噪声协方差
    float r; // 测量噪声协方差
    float x; // 估计值
    float p; // 估计误差协方差
    float k; // 卡尔曼增益
} KalmanFilter;

void kalman_init(KalmanFilter *kf, float q, float r, float initial_value) {
    kf->q = q;
    kf->r = r;
    kf->x = initial_value;
    kf->p = 1.0;
    kf->k = 0;
}

float kalman_update(KalmanFilter *kf, float measurement) {
    kf->p = kf->p + kf->q;
    kf->k = kf->p / (kf->p + kf->r);
    kf->x = kf->x + kf->k * (measurement - kf->x);
    kf->p = (1 - kf->k) * kf->p;
    return kf->x;
}
```

## 集成功能

### 错误追踪集成

```bash
# 搜索错误历史
python serial_loop.py --search "数据跳变"

# 获取修复建议
python serial_loop.py --suggest "数据不稳定"

# 记录修复
python serial_loop.py --record --error "数据跳变" --fix "添加中值滤波"
```

### 技术规范集成

```bash
# 获取项目配置
python serial_loop.py --config

# 获取外设配置
python serial_loop.py --peripheral USART1

# 检查引脚冲突
python serial_loop.py --check-pins
```

### 数据可视化

```bash
# ASCII 图表
python serial_loop.py --mode analyze --duration 10 --plot

# 直方图
python serial_loop.py --mode analyze --duration 10 --histogram

# 散点图
python serial_loop.py --mode analyze --duration 10 --scatter
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
| `collect_data()` | 采集串口数据 |
| `parse_values()` | 解析数值 |
| `parse_protocol()` | 解析协议 |
| `parse_named_values()` | 解析命名值 |

### 数据分析

| 函数 | 说明 |
|------|------|
| `analyze_range()` | 范围分析 |
| `analyze_jumps()` | 跳变分析 |
| `analyze_continuity()` | 连续性分析 |
| `analyze_trend()` | 趋势分析 |
| `analyze_outliers()` | 异常值检测 |
| `analyze_periodicity()` | 周期性检测 |
| `analyze_stability()` | 稳定性分析 |
| `analyze_distribution()` | 分布分析 |
| `auto_detect_issues()` | 自动检测问题 |

### 数据可视化

| 函数 | 说明 |
|------|------|
| `plot_ascii_chart()` | ASCII 图表 |
| `plot_ascii_histogram()` | ASCII 直方图 |
| `plot_ascii_scatter()` | ASCII 散点图 |

### 代码生成

| 函数 | 说明 |
|------|------|
| `generate_fix_code()` | 生成修复代码 |
| `generate_range_check_code()` | 范围检查代码 |
| `generate_median_filter_code()` | 中值滤波代码 |
| `generate_moving_average_code()` | 滑动平均代码 |
| `generate_ema_filter_code()` | 指数移动平均代码 |
| `generate_kalman_filter_code()` | 卡尔曼滤波代码 |
| `generate_adaptive_filter_code()` | 自适应滤波代码 |
| `generate_butterworth_filter_code()` | 巴特沃斯滤波代码 |

### 工作流集成

| 函数 | 说明 |
|------|------|
| `compile_and_flash()` | 编译烧录 |
| `reset_device()` | 复位设备 |
| `auto_loop()` | 自动闭环 |
| `run_batch_tests()` | 批量测试 |

### 集成功能

| 函数 | 说明 |
|------|------|
| `search_error_history()` | 搜索错误历史 |
| `get_fix_suggestions_from_history()` | 获取修复建议 |
| `record_error_fix()` | 记录修复 |
| `get_project_config()` | 获取项目配置 |
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
| 串口连接失败 | 检查串口号、波特率、USB 连接 |
| 数据采集超时 | 增加 `--duration` 参数 |
| 分析结果不准确 | 调整阈值参数 |
| 编译烧录失败 | 检查项目配置、Keil 安装 |
| 复位失败 | 尝试不同的复位方法 |

## 安全约束

- 不全片擦除
- 不写 Option Bytes
- 不改读保护
- 代码修改遵循最小改动原则
- 烧录前必须验证固件
