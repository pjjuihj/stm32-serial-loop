#!/usr/bin/env python
"""STM32 串口闭环调试脚本。

功能：
  - 串口数据采集
  - 数据分析（范围、跳变、连续性）
  - 问题报告生成
  - 闭环调试工作流

用法:
  # 数据采集
  python serial_loop.py --port COM3 --mode collect --duration 10

  # 数据分析
  python serial_loop.py --port COM3 --mode analyze --duration 10 --min-val 0 --max-val 100

  # 完整闭环
  python serial_loop.py --port COM3 --mode loop --duration 10 --max-val 100

  # 从文件分析
  python serial_loop.py --mode analyze --input data.json --min-val 0 --max-val 100
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 编码处理
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    logger.error("需要安装 pyserial。运行: pip install pyserial")
    sys.exit(1)


# === 进度跟踪 ===

class ProgressTracker:
    """进度跟踪器。"""

    def __init__(self, total_steps: int, description: str = ""):
        self.total_steps = total_steps
        self.current_step = 0
        self.description = description
        self.start_time = time.time()
        self.history = []

    def update(self, step: int, message: str = ""):
        """更新进度。"""
        self.current_step = step
        elapsed = time.time() - self.start_time
        progress = step / self.total_steps * 100

        # 打印进度条
        bar_length = 40
        filled = int(bar_length * step / self.total_steps)
        bar = "█" * filled + "░" * (bar_length - filled)

        print(f"\r[{bar}] {progress:.1f}% ({step}/{self.total_steps}) {message}", end="", flush=True)

        # 记录历史
        self.history.append({
            "step": step,
            "message": message,
            "elapsed": elapsed,
            "progress": progress,
        })

    def finish(self, message: str = "完成"):
        """完成进度。"""
        elapsed = time.time() - self.start_time
        print(f"\n{message} (耗时: {elapsed:.1f}s)")

    def get_summary(self) -> dict:
        """获取进度摘要。"""
        return {
            "total_steps": self.total_steps,
            "completed_steps": self.current_step,
            "elapsed": time.time() - self.start_time,
            "history": self.history,
        }


# === 常量 ===

MAX_ERRORS = 100  # 最大错误数
PROGRESS_BAR_LENGTH = 40  # 进度条长度
SERIAL_TIMEOUT = 0.1  # 串口超时（秒）
RETRY_DELAY = 1  # 重试延迟（秒）


# === 数据采集 ===

def _process_line(line_buf: bytearray, start_time: float,
                  filter_keyword: str = None) -> dict | None:
    """处理一行数据。

    Args:
        line_buf: 行缓冲区
        start_time: 开始时间
        filter_keyword: 过滤关键字

    Returns:
        数据条目，如果被过滤则返回 None
    """
    try:
        text = bytes(line_buf).decode("utf-8", errors="replace").strip()
    except UnicodeDecodeError:
        return None

    if not text:
        return None

    # 过滤关键字
    if filter_keyword and filter_keyword not in text:
        return None

    ts = time.time() - start_time
    return {
        "timestamp": round(ts, 3),
        "text": text,
        "values": parse_values(text),
    }


def collect_data(port: str, baud: int = 115200, duration: float = 10.0,
                 protocol: str = "text", retry_count: int = 3,
                 filter_keyword: str = None) -> dict:
    """采集串口数据。

    Args:
        port: 串口号
        baud: 波特率
        duration: 采集时长（秒）
        protocol: 协议类型（text/hex/vofa）
        retry_count: 重试次数
        filter_keyword: 过滤关键字

    Returns:
        采集结果
    """
    print(f"数据采集: {port} @ {baud} bps, 时长 {duration}s, 协议 {protocol}")

    # 重试机制
    ser = None
    for attempt in range(retry_count):
        try:
            ser = serial.Serial(port=port, baudrate=baud, timeout=SERIAL_TIMEOUT)
            break
        except serial.SerialException as e:
            if attempt < retry_count - 1:
                print(f"  连接失败，重试 {attempt + 1}/{retry_count}...")
                time.sleep(RETRY_DELAY)
            else:
                return {"success": False, "error": f"无法打开串口: {e}"}

    entries = []
    start = time.time()
    line_buf = bytearray()
    error_count = 0

    try:
        while time.time() - start < duration:
            data = ser.read(1)
            if not data:
                if line_buf:
                    entry = _process_line(line_buf, start, filter_keyword)
                    if entry:
                        entries.append(entry)
                        print(f"[{entry['timestamp']:8.3f}] {entry['text']}")
                    line_buf.clear()
                continue

            for b in data:
                if b == ord("\n"):
                    entry = _process_line(line_buf, start, filter_keyword)
                    if entry:
                        entries.append(entry)
                        print(f"[{entry['timestamp']:8.3f}] {entry['text']}")
                    line_buf.clear()
                elif b == ord("\r"):
                    pass
                else:
                    line_buf.append(b)

            # 检查错误数
            if error_count >= MAX_ERRORS:
                print(f"⚠️ 错误数过多 ({error_count})，停止采集")
                break
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()

    # 提取所有数值
    all_values = []
    for entry in entries:
        all_values.extend(entry["values"])

    result = {
        "success": True,
        "port": port,
        "baud": baud,
        "duration": duration,
        "protocol": protocol,
        "filter_keyword": filter_keyword,
        "entries": entries,
        "values": all_values,
        "value_count": len(all_values),
        "error_count": error_count,
        "timestamp": datetime.now().isoformat(),
    }

    print(f"\n采集完成: {len(entries)} 条数据, {len(all_values)} 个数值")
    return result


def parse_values(text: str) -> list[float]:
    """从文本中提取数值。

    支持格式:
      "temp:25.5,humidity:60.2"
      "25.5,60.2,101.3"
      "ADC:2048"
    """
    values = []
    pattern = r'-?\d+\.?\d*'
    matches = re.findall(pattern, text)
    for match in matches:
        try:
            values.append(float(match))
        except ValueError:
            continue
    return values


def parse_protocol(data: bytes, protocol: str = "text") -> list[dict]:
    """解析协议数据。

    Args:
        data: 原始数据
        protocol: 协议类型 (text/hex/vofa/modbus)

    Returns:
        解析结果
    """
    results = []

    if protocol == "text":
        # 文本协议
        try:
            text = data.decode("utf-8", errors="replace").strip()
            if text:
                results.append({
                    "type": "text",
                    "text": text,
                    "values": parse_values(text),
                })
        except Exception:
            pass

    elif protocol == "hex":
        # HEX 协议
        hex_str = data.hex(" ")
        results.append({
            "type": "hex",
            "hex": hex_str,
            "bytes": len(data),
        })

    elif protocol == "vofa":
        # VOFA+ 协议
        try:
            text = data.decode("utf-8", errors="replace").strip()
            if text.endswith("\n"):
                values = []
                for part in text.strip().split(","):
                    try:
                        values.append(float(part))
                    except ValueError:
                        continue
                if values:
                    results.append({
                        "type": "vofa",
                        "values": values,
                        "raw": text,
                    })
        except Exception:
            pass

    elif protocol == "modbus":
        # Modbus RTU 协议
        if len(data) >= 4:
            # 解析 Modbus 帧
            slave_addr = data[0]
            function_code = data[1]

            results.append({
                "type": "modbus",
                "slave_addr": slave_addr,
                "function_code": function_code,
                "data": data[2:].hex(" "),
                "bytes": len(data),
            })

    return results


def parse_named_values(text: str) -> dict:
    """解析命名值。

    支持格式:
      "temp:25.5,humidity:60.2"
      "ADC1:2048,ADC2:1024"
      "speed=100,angle=45"

    Returns:
        命名值字典
    """
    result = {}

    # 尝试不同的分隔符
    for separator in [",", ";", " ", "\t"]:
        parts = text.split(separator)
        for part in parts:
            part = part.strip()
            if not part:
                continue

            # 尝试不同的键值分隔符
            for kv_sep in [":", "=", "->"]:
                if kv_sep in part:
                    key, value = part.split(kv_sep, 1)
                    key = key.strip()
                    value = value.strip()

                    try:
                        result[key] = float(value)
                    except ValueError:
                        result[key] = value
                    break

    return result


# === 数据分析 ===

def analyze_data(data: dict, min_val: float = None, max_val: float = None,
                 jump_threshold: float = None, expected_interval: float = None) -> dict:
    """分析数据。

    Args:
        data: 采集数据
        min_val: 最小值阈值
        max_val: 最大值阈值
        jump_threshold: 跳变阈值
        expected_interval: 预期间隔

    Returns:
        分析结果
    """
    values = data.get("values", [])
    entries = data.get("entries", [])

    if not values:
        return {"success": False, "error": "没有数据"}

    print(f"\n数据分析: {len(values)} 个数值")

    result = {
        "success": True,
        "value_count": len(values),
        "analysis": {},
    }

    # 范围分析
    range_result = analyze_range(values, min_val, max_val)
    result["analysis"]["range"] = range_result

    # 跳变分析
    jump_result = analyze_jumps(values, jump_threshold)
    result["analysis"]["jump"] = jump_result

    # 连续性分析
    if expected_interval:
        cont_result = analyze_continuity(values, expected_interval)
        result["analysis"]["continuity"] = cont_result

    # 统计分析
    stats_result = analyze_statistics(values)
    result["analysis"]["statistics"] = stats_result

    # 问题汇总
    issues = []
    if range_result.get("out_of_range"):
        issues.extend([{"type": "out_of_range", "index": i["index"], "value": i["value"], "reason": i["reason"]}
                       for i in range_result["out_of_range"]])
    if jump_result.get("jumps"):
        issues.extend([{"type": "jump", "index": i["index"], "from": i["from"], "to": i["to"], "diff": i["diff"]}
                       for i in jump_result["jumps"]])
    if expected_interval and result["analysis"].get("continuity", {}).get("discontinuities"):
        issues.extend([{"type": "discontinuity", "index": i["index"], "diff": i["diff"], "expected": i["expected"]}
                       for i in result["analysis"]["continuity"]["discontinuities"]])

    result["issues"] = issues
    result["issue_count"] = len(issues)

    # 打印分析结果
    print_analysis_result(result)

    return result


def analyze_range(values: list[float], min_val: float = None,
                  max_val: float = None) -> dict:
    """分析数据范围。"""
    result = {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
        "range": max(values) - min(values),
        "out_of_range": [],
    }

    if min_val is not None or max_val is not None:
        for i, v in enumerate(values):
            if min_val is not None and v < min_val:
                result["out_of_range"].append({"index": i, "value": v, "reason": "低于最小值"})
            if max_val is not None and v > max_val:
                result["out_of_range"].append({"index": i, "value": v, "reason": "高于最大值"})

    return result


def analyze_trend(values: list[float]) -> dict:
    """分析数据趋势。

    Returns:
        趋势分析结果
    """
    if len(values) < 3:
        return {"error": "数据不足"}

    # 计算线性回归
    n = len(values)
    x = list(range(n))
    x_mean = sum(x) / n
    y_mean = sum(values) / n

    # 计算斜率和截距
    numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        slope = 0
    else:
        slope = numerator / denominator

    intercept = y_mean - slope * x_mean

    # 计算 R²
    ss_res = sum((values[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
    ss_tot = sum((values[i] - y_mean) ** 2 for i in range(n))
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

    # 判断趋势
    if slope > 0.1:
        trend = "上升"
    elif slope < -0.1:
        trend = "下降"
    else:
        trend = "平稳"

    return {
        "count": n,
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_squared,
        "trend": trend,
        "y_start": slope * 0 + intercept,
        "y_end": slope * (n - 1) + intercept,
    }


def analyze_outliers(values: list[float], threshold: float = 2.0) -> dict:
    """检测异常值。

    Args:
        values: 数值列表
        threshold: 标准差倍数阈值

    Returns:
        异常值检测结果
    """
    if len(values) < 3:
        return {"error": "数据不足"}

    n = len(values)
    mean = sum(values) / n
    std_dev = (sum((x - mean) ** 2 for x in values) / n) ** 0.5

    outliers = []
    for i, v in enumerate(values):
        z_score = abs(v - mean) / std_dev if std_dev != 0 else 0
        if z_score > threshold:
            outliers.append({
                "index": i,
                "value": v,
                "z_score": z_score,
                "deviation": abs(v - mean),
            })

    return {
        "count": n,
        "mean": mean,
        "std_dev": std_dev,
        "threshold": threshold,
        "outliers": outliers,
        "outlier_count": len(outliers),
    }


def analyze_periodicity(values: list[float]) -> dict:
    """检测数据周期性。

    Returns:
        周期性检测结果
    """
    if len(values) < 10:
        return {"error": "数据不足"}

    # 使用自相关函数检测周期
    n = len(values)
    mean = sum(values) / n

    # 计算自相关
    max_lag = min(n // 2, 50)
    autocorr = []

    for lag in range(1, max_lag + 1):
        numerator = sum((values[i] - mean) * (values[i - lag] - mean) for i in range(lag, n))
        denominator = sum((values[i] - mean) ** 2 for i in range(n))
        if denominator != 0:
            autocorr.append(numerator / denominator)
        else:
            autocorr.append(0)

    # 找到峰值
    peaks = []
    for i in range(1, len(autocorr) - 1):
        if autocorr[i] > autocorr[i-1] and autocorr[i] > autocorr[i+1]:
            peaks.append({"lag": i + 1, "value": autocorr[i]})

    # 找到最强周期
    if peaks:
        strongest_peak = max(peaks, key=lambda x: x["value"])
        period = strongest_peak["lag"]
        confidence = strongest_peak["value"]
    else:
        period = None
        confidence = 0

    return {
        "count": n,
        "period": period,
        "confidence": confidence,
        "is_periodic": confidence > 0.5,
        "peaks": peaks[:5],
    }


def analyze_stability(values: list[float], window_size: int = 10) -> dict:
    """分析数据稳定性。

    Args:
        values: 数值列表
        window_size: 窗口大小

    Returns:
        稳定性分析结果
    """
    if len(values) < window_size:
        return {"error": "数据不足"}

    # 计算滑动标准差
    std_devs = []
    for i in range(len(values) - window_size + 1):
        window = values[i:i + window_size]
        mean = sum(window) / window_size
        std_dev = (sum((x - mean) ** 2 for x in window) / window_size) ** 0.5
        std_devs.append(std_dev)

    # 计算稳定性指标
    mean_std = sum(std_devs) / len(std_devs)
    max_std = max(std_devs)
    min_std = min(std_devs)

    # 判断稳定性
    if mean_std < 1.0:
        stability = "稳定"
    elif mean_std < 5.0:
        stability = "较稳定"
    else:
        stability = "不稳定"

    return {
        "count": len(values),
        "window_size": window_size,
        "mean_std": mean_std,
        "max_std": max_std,
        "min_std": min_std,
        "stability": stability,
        "std_devs": std_devs[:20],  # 只返回前 20 个
    }


def analyze_distribution(values: list[float], bins: int = 10) -> dict:
    """分析数据分布。

    Args:
        values: 数值列表
        bins: 分组数

    Returns:
        分布分析结果
    """
    if len(values) < 3:
        return {"error": "数据不足"}

    # 计算直方图
    min_val = min(values)
    max_val = max(values)
    bin_width = (max_val - min_val) / bins if max_val != min_val else 1

    histogram = [0] * bins
    for v in values:
        bin_index = min(int((v - min_val) / bin_width), bins - 1)
        histogram[bin_index] += 1

    # 计算分布指标
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std_dev = variance ** 0.5

    # 计算偏度和峰度
    n = len(values)
    skewness = sum(((x - mean) / std_dev) ** 3 for x in values) / n if std_dev != 0 else 0
    kurtosis = sum(((x - mean) / std_dev) ** 4 for x in values) / n - 3 if std_dev != 0 else 0

    return {
        "count": n,
        "min": min_val,
        "max": max_val,
        "mean": mean,
        "std_dev": std_dev,
        "skewness": skewness,
        "kurtosis": kurtosis,
        "histogram": histogram,
        "bin_width": bin_width,
    }


# === 数据问题自动检测 ===

def auto_detect_issues(values: list[float]) -> dict:
    """自动检测数据问题。

    Args:
        values: 数值列表

    Returns:
        检测结果
    """
    if len(values) < 3:
        return {"success": False, "error": "数据不足"}

    issues = []

    # 检测范围问题
    range_result = analyze_range(values)
    if range_result.get("out_of_range"):
        issues.append({
            "type": "range",
            "description": "数据超出预期范围",
            "count": len(range_result["out_of_range"]),
            "severity": "warning",
        })

    # 检测跳变问题
    jump_result = analyze_jumps(values)
    if jump_result.get("jumps"):
        issues.append({
            "type": "jump",
            "description": "数据存在异常跳变",
            "count": len(jump_result["jumps"]),
            "severity": "error",
        })

    # 检测稳定性问题
    stability_result = analyze_stability(values)
    if stability_result.get("stability") == "不稳定":
        issues.append({
            "type": "stability",
            "description": "数据不稳定",
            "std_dev": stability_result.get("mean_std", 0),
            "severity": "warning",
        })

    # 检测趋势问题
    trend_result = analyze_trend(values)
    if trend_result.get("trend") == "下降" and trend_result.get("r_squared", 0) > 0.7:
        issues.append({
            "type": "trend",
            "description": "数据持续下降",
            "slope": trend_result.get("slope", 0),
            "severity": "warning",
        })

    # 检测异常值
    outlier_result = analyze_outliers(values)
    if outlier_result.get("outliers"):
        issues.append({
            "type": "outlier",
            "description": "数据存在异常值",
            "count": len(outlier_result["outliers"]),
            "severity": "warning",
        })

    # 生成修复建议
    suggestions = generate_fix_suggestions(issues)

    return {
        "success": True,
        "issue_count": len(issues),
        "issues": issues,
        "suggestions": suggestions,
    }


def generate_fix_suggestions(issues: list[dict]) -> list[dict]:
    """生成修复建议。

    Args:
        issues: 问题列表

    Returns:
        修复建议列表
    """
    suggestions = []

    for issue in issues:
        if issue["type"] == "range":
            suggestions.append({
                "issue": "range",
                "action": "添加范围检查和限幅处理",
                "code": "range_check(value, min_val, max_val)",
                "priority": 1,
            })

        elif issue["type"] == "jump":
            suggestions.append({
                "issue": "jump",
                "action": "添加中值滤波",
                "code": "median_filter(value)",
                "priority": 2,
            })

        elif issue["type"] == "stability":
            suggestions.append({
                "issue": "stability",
                "action": "添加滑动平均滤波",
                "code": "moving_average(value)",
                "priority": 3,
            })

        elif issue["type"] == "trend":
            suggestions.append({
                "issue": "trend",
                "action": "检查传感器校准",
                "code": "检查 ADC 参考电压",
                "priority": 4,
            })

        elif issue["type"] == "outlier":
            suggestions.append({
                "issue": "outlier",
                "action": "添加异常值检测",
                "code": "outlier_detection(value, threshold)",
                "priority": 2,
            })

    # 按优先级排序
    suggestions.sort(key=lambda x: x.get("priority", 99))
    return suggestions


def generate_code_modification(analysis: dict, source_code: str = None) -> dict:
    """生成代码修改建议。

    Args:
        analysis: 数据分析结果
        source_code: 源代码（可选）

    Returns:
        代码修改建议
    """
    issues = analysis.get("issues", [])
    if not issues:
        return {"success": False, "error": "没有发现问题"}

    modifications = []

    # 检查范围问题
    if any(i["type"] == "range" for i in issues):
        modifications.append({
            "type": "function_addition",
            "description": "添加范围检查函数",
            "function_name": "range_check",
            "code": generate_range_check_code(),
            "usage": "float filtered = range_check(raw_value, 0.0, 100.0);",
        })

    # 检查跳变问题
    if any(i["type"] == "jump" for i in issues):
        modifications.append({
            "type": "function_addition",
            "description": "添加中值滤波函数",
            "function_name": "median_filter",
            "code": generate_median_filter_code(),
            "usage": "float filtered = median_filter(raw_value);",
        })

    # 检查稳定性问题
    if any(i["type"] == "stability" for i in issues):
        modifications.append({
            "type": "function_addition",
            "description": "添加滑动平均滤波函数",
            "function_name": "moving_average",
            "code": generate_moving_average_code(),
            "usage": "float filtered = moving_average(raw_value);",
        })

    # 检查异常值问题
    if any(i["type"] == "outlier" for i in issues):
        modifications.append({
            "type": "function_addition",
            "description": "添加异常值检测函数",
            "function_name": "outlier_detection",
            "code": generate_outlier_detection_code(),
            "usage": "if (outlier_detection(value, 2.0)) { /* 处理异常值 */ }",
        })

    # 生成修改指南
    guide = generate_modification_guide(modifications)

    return {
        "success": True,
        "modification_count": len(modifications),
        "modifications": modifications,
        "guide": guide,
    }


def generate_outlier_detection_code() -> str:
    """生成异常值检测代码。"""
    return '''
// 异常值检测（Z-score 方法）
typedef struct {
    float mean;
    float std_dev;
    int count;
    float sum;
    float sum_sq;
} Stats;

void stats_init(Stats *s) {
    s->mean = 0;
    s->std_dev = 0;
    s->count = 0;
    s->sum = 0;
    s->sum_sq = 0;
}

void stats_update(Stats *s, float value) {
    s->count++;
    s->sum += value;
    s->sum_sq += value * value;
    s->mean = s->sum / s->count;
    s->std_dev = sqrt(s->sum_sq / s->count - s->mean * s->mean);
}

int is_outlier(Stats *s, float value, float threshold) {
    if (s->count < 10) return 0;  // 数据不足
    float z_score = fabs(value - s->mean) / s->std_dev;
    return z_score > threshold;
}

// 使用示例
// Stats stats;
// stats_init(&stats);
// for (int i = 0; i < n; i++) {
//     stats_update(&stats, values[i]);
//     if (is_outlier(&stats, values[i], 2.0)) {
//         // 处理异常值
//     }
// }
'''


def generate_modification_guide(modifications: list[dict]) -> str:
    """生成修改指南。

    Args:
        modifications: 修改列表

    Returns:
        修改指南
    """
    lines = []

    lines.append("# 代码修改指南")
    lines.append("")
    lines.append("## 修改步骤")
    lines.append("")

    for i, mod in enumerate(modifications, 1):
        lines.append(f"### 步骤 {i}: {mod['description']}")
        lines.append("")
        lines.append(f"1. 在 main.c 中添加以下函数:")
        lines.append("")
        lines.append("```c")
        lines.append(mod["code"])
        lines.append("```")
        lines.append("")
        lines.append(f"2. 在数据采集处使用:")
        lines.append("")
        lines.append("```c")
        lines.append(mod["usage"])
        lines.append("```")
        lines.append("")

    lines.append("## 注意事项")
    lines.append("")
    lines.append("1. 在 CubeMX 重新生成代码后，需要重新添加这些函数")
    lines.append("2. 滤波器参数需要根据实际情况调整")
    lines.append("3. 建议在调试阶段保留原始数据用于对比")
    lines.append("")

    return "\n".join(lines)


# === 测试验证 ===

def verify_fix(before_data: dict, after_data: dict, before_analysis: dict,
               after_analysis: dict) -> dict:
    """验证修复效果。

    Args:
        before_data: 修复前数据
        after_data: 修复后数据
        before_analysis: 修复前分析
        after_analysis: 修复后分析

    Returns:
        验证结果
    """
    before_issues = before_analysis.get("issue_count", 0)
    after_issues = after_analysis.get("issue_count", 0)

    before_values = before_data.get("values", [])
    after_values = after_data.get("values", [])

    # 计算统计变化
    before_mean = sum(before_values) / len(before_values) if before_values else 0
    after_mean = sum(after_values) / len(after_values) if after_values else 0

    before_std = (sum((x - before_mean) ** 2 for x in before_values) / len(before_values)) ** 0.5 if before_values else 0
    after_std = (sum((x - after_mean) ** 2 for x in after_values) / len(after_values)) ** 0.5 if after_values else 0

    # 判断修复效果
    if after_issues < before_issues:
        status = "improved"
        description = f"问题数减少: {before_issues} → {after_issues}"
    elif after_issues == before_issues:
        status = "unchanged"
        description = f"问题数未变: {before_issues}"
    else:
        status = "regressed"
        description = f"问题数增加: {before_issues} → {after_issues}"

    return {
        "success": True,
        "status": status,
        "description": description,
        "before": {
            "issue_count": before_issues,
            "mean": before_mean,
            "std_dev": before_std,
        },
        "after": {
            "issue_count": after_issues,
            "mean": after_mean,
            "std_dev": after_std,
        },
        "improvement": {
            "issue_reduction": before_issues - after_issues,
            "std_dev_reduction": before_std - after_std,
        },
    }


def print_verification_result(result: dict):
    """打印验证结果。"""
    print(f"\n验证结果:")
    print(f"  状态: {result['status']}")
    print(f"  说明: {result['description']}")
    print(f"  修复前: {result['before']['issue_count']} 个问题, 标准差 {result['before']['std_dev']:.2f}")
    print(f"  修复后: {result['after']['issue_count']} 个问题, 标准差 {result['after']['std_dev']:.2f}")

    if result["status"] == "improved":
        print(f"  ✅ 修复成功")
    elif result["status"] == "unchanged":
        print(f"  ⚠️ 修复效果不明显")
    else:
        print(f"  ❌ 修复后问题增加")


# === 错误追踪集成 ===

def search_error_history(keyword: str) -> list[dict]:
    """搜索错误历史。

    Args:
        keyword: 搜索关键词

    Returns:
        搜索结果
    """
    import subprocess

    # 查找 error_tracker.py
    error_tracker_script = Path(__file__).parent.parent.parent / "stm32-keil-workflow" / "scripts" / "error_tracker.py"
    if not error_tracker_script.exists():
        return []

    # 构建命令
    cmd = [sys.executable, str(error_tracker_script), "--search", keyword, "--text"]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            # 解析输出
            results = []
            lines = proc.stdout.splitlines()
            for line in lines:
                if line.startswith("["):
                    # 解析格式: [id] error -> fix
                    parts = line.split("->")
                    if len(parts) == 2:
                        results.append({
                            "error": parts[0].strip(),
                            "fix": parts[1].strip(),
                        })
            return results
    except Exception:
        pass

    return []


def get_fix_suggestions_from_history(error_type: str) -> list[dict]:
    """从历史获取修复建议。

    Args:
        error_type: 错误类型

    Returns:
        修复建议列表
    """
    import subprocess

    # 查找 error_tracker.py
    error_tracker_script = Path(__file__).parent.parent.parent / "stm32-keil-workflow" / "scripts" / "error_tracker.py"
    if not error_tracker_script.exists():
        return []

    # 构建命令
    cmd = [sys.executable, str(error_tracker_script), "--suggest", error_type, "--text"]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            # 解析输出
            results = []
            lines = proc.stdout.splitlines()
            for line in lines:
                if line.startswith("-"):
                    results.append({
                        "suggestion": line[1:].strip(),
                    })
            return results
    except Exception:
        pass

    return []


def record_error_fix(error: str, fix: str, file: str = None) -> bool:
    """记录错误修复。

    Args:
        error: 错误信息
        fix: 修复方法
        file: 关联文件

    Returns:
        是否成功
    """
    import subprocess

    # 查找 error_tracker.py
    error_tracker_script = Path(__file__).parent.parent.parent / "stm32-keil-workflow" / "scripts" / "error_tracker.py"
    if not error_tracker_script.exists():
        return False

    # 构建命令
    cmd = [sys.executable, str(error_tracker_script), "--record", "--error", error, "--fix", fix]
    if file:
        cmd.extend(["--file", file])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return proc.returncode == 0
    except Exception:
        return False


# === 技术规范集成 ===

def get_project_config(project_dir: str) -> dict:
    """获取项目配置。

    Args:
        project_dir: 项目目录

    Returns:
        项目配置
    """
    import subprocess

    # 查找 tech_spec.py
    tech_spec_script = Path(__file__).parent.parent.parent / "stm32-keil-workflow" / "scripts" / "tech_spec.py"
    if not tech_spec_script.exists():
        return {}

    # 构建命令
    cmd = [sys.executable, str(tech_spec_script), "--auto", project_dir, "--text"]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            # 解析输出
            config = {}
            lines = proc.stdout.splitlines()
            for line in lines:
                if ":" in line:
                    key, value = line.split(":", 1)
                    config[key.strip()] = value.strip()
            return config
    except Exception:
        pass

    return {}


def get_peripheral_config(project_dir: str, peripheral: str) -> dict:
    """获取外设配置。

    Args:
        project_dir: 项目目录
        peripheral: 外设名称

    Returns:
        外设配置
    """
    import subprocess

    # 查找 cubemx_guide.py
    cubemx_guide_script = Path(__file__).parent.parent.parent / "stm32-keil-workflow" / "scripts" / "cubemx_guide.py"
    if not cubemx_guide_script.exists():
        return {}

    # 构建命令
    cmd = [sys.executable, str(cubemx_guide_script), "--peripheral", peripheral]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            # 解析输出
            config = {
                "peripheral": peripheral,
                "guide": proc.stdout,
            }
            return config
    except Exception:
        pass

    return {}


def check_pin_conflict(project_dir: str) -> list[dict]:
    """检查引脚冲突。

    Args:
        project_dir: 项目目录

    Returns:
        冲突列表
    """
    import subprocess

    # 查找 pin_checker.py
    pin_checker_script = Path(__file__).parent.parent.parent / "stm32-keil-workflow" / "scripts" / "pin_checker.py"
    if not pin_checker_script.exists():
        return []

    # 查找 ioc 文件
    ioc_files = list(Path(project_dir).glob("*.ioc"))
    if not ioc_files:
        return []

    # 构建命令
    cmd = [sys.executable, str(pin_checker_script), "--ioc", str(ioc_files[0])]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            # 解析输出
            conflicts = []
            lines = proc.stdout.splitlines()
            for line in lines:
                if "conflict" in line.lower():
                    conflicts.append({
                        "description": line.strip(),
                    })
            return conflicts
    except Exception:
        pass

    return []


# === 数据可视化 ===

def plot_ascii_chart(values: list[float], width: int = 60, height: int = 20,
                    title: str = "数据图表") -> str:
    """生成 ASCII 图表。

    Args:
        values: 数值列表
        width: 图表宽度
        height: 图表高度
        title: 图表标题

    Returns:
        ASCII 图表字符串
    """
    if not values:
        return "没有数据"

    # 计算范围
    min_val = min(values)
    max_val = max(values)
    val_range = max_val - min_val if max_val != min_val else 1

    # 采样数据（如果数据太多）
    if len(values) > width:
        step = len(values) / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = values
        width = len(sampled)

    # 生成图表
    lines = []
    lines.append(f"┌{'─' * width}┐")
    lines.append(f"│{title.center(width)}│")
    lines.append(f"├{'─' * width}┤")

    for row in range(height, -1, -1):
        threshold = min_val + (val_range * row / height)
        line = "│"
        for val in sampled:
            if val >= threshold:
                line += "█"
            else:
                line += " "
        line += "│"
        lines.append(line)

    lines.append(f"└{'─' * width}┘")

    # 添加刻度
    lines.append(f"  {min_val:.1f}{' ' * (width - 10)}{max_val:.1f}")

    return "\n".join(lines)


def plot_ascii_histogram(values: list[float], bins: int = 20, width: int = 50) -> str:
    """生成 ASCII 直方图。

    Args:
        values: 数值列表
        bins: 分组数
        width: 最大宽度

    Returns:
        ASCII 直方图字符串
    """
    if not values:
        return "没有数据"

    # 计算直方图
    min_val = min(values)
    max_val = max(values)
    bin_width = (max_val - min_val) / bins if max_val != min_val else 1

    histogram = [0] * bins
    for v in values:
        bin_index = min(int((v - min_val) / bin_width), bins - 1)
        histogram[bin_index] += 1

    # 找到最大计数
    max_count = max(histogram) if histogram else 1

    # 生成直方图
    lines = []
    lines.append("直方图:")
    lines.append("")

    for i, count in enumerate(histogram):
        # 计算条形长度
        bar_length = int(count / max_count * width) if max_count > 0 else 0
        bar = "█" * bar_length

        # 计算区间
        bin_start = min_val + i * bin_width
        bin_end = bin_start + bin_width

        lines.append(f"  {bin_start:6.1f} - {bin_end:6.1f} | {bar} ({count})")

    return "\n".join(lines)


def plot_ascii_scatter(x: list[float], y: list[float], width: int = 60,
                      height: int = 20, title: str = "散点图") -> str:
    """生成 ASCII 散点图。

    Args:
        x: X 轴数据
        y: Y 轴数据
        width: 图表宽度
        height: 图表高度
        title: 图表标题

    Returns:
        ASCII 散点图字符串
    """
    if not x or not y or len(x) != len(y):
        return "数据无效"

    # 计算范围
    x_min, x_max = min(x), max(x)
    y_min, y_max = min(y), max(y)
    x_range = x_max - x_min if x_max != x_min else 1
    y_range = y_max - y_min if y_max != y_min else 1

    # 创建画布
    canvas = [[" " for _ in range(width)] for _ in range(height)]

    # 绘制点
    for i in range(len(x)):
        col = int((x[i] - x_min) / x_range * (width - 1))
        row = int((y[i] - y_min) / y_range * (height - 1))
        row = height - 1 - row  # 翻转 Y 轴
        canvas[row][col] = "●"

    # 生成图表
    lines = []
    lines.append(f"┌{'─' * width}┐")
    lines.append(f"│{title.center(width)}│")
    lines.append(f"├{'─' * width}┤")

    for row in canvas:
        lines.append("│" + "".join(row) + "│")

    lines.append(f"└{'─' * width}┘")
    lines.append(f"  X: {x_min:.1f} - {x_max:.1f}")
    lines.append(f"  Y: {y_min:.1f} - {y_max:.1f}")

    return "\n".join(lines)


# === 数据日志 ===

def save_data_log(data: dict, analysis: dict, output_dir: str = "logs") -> dict:
    """保存数据日志。

    Args:
        data: 采集数据
        analysis: 分析结果
        output_dir: 输出目录

    Returns:
        保存结果
    """
    import os

    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)

    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"data_log_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)

    # 准备日志数据
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "data": {
            "port": data.get("port"),
            "baud": data.get("baud"),
            "duration": data.get("duration"),
            "protocol": data.get("protocol"),
            "value_count": data.get("value_count"),
            "entries": data.get("entries", [])[:100],  # 只保存前 100 条
            "values": data.get("values", [])[:1000],  # 只保存前 1000 个值
        },
        "analysis": analysis,
    }

    # 保存文件
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)

        print(f"数据日志已保存: {filepath}")
        return {"success": True, "filepath": filepath}

    except Exception as e:
        print(f"保存数据日志失败: {e}")
        return {"success": False, "error": str(e)}


def load_data_log(filepath: str) -> dict:
    """加载数据日志。

    Args:
        filepath: 日志文件路径

    Returns:
        日志数据
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        print(f"数据日志已加载: {filepath}")
        return {"success": True, "data": data}

    except Exception as e:
        print(f"加载数据日志失败: {e}")
        return {"success": False, "error": str(e)}


def list_data_logs(output_dir: str = "logs") -> list[dict]:
    """列出数据日志。

    Args:
        output_dir: 日志目录

    Returns:
        日志列表
    """
    import os

    if not os.path.exists(output_dir):
        return []

    logs = []
    for filename in os.listdir(output_dir):
        if filename.startswith("data_log_") and filename.endswith(".json"):
            filepath = os.path.join(output_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logs.append({
                    "filename": filename,
                    "filepath": filepath,
                    "timestamp": data.get("timestamp"),
                    "value_count": data.get("data", {}).get("value_count"),
                })
            except Exception:
                continue

    # 按时间排序
    logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return logs


def compare_with_history(current_data: dict, current_analysis: dict,
                        history_dir: str = "logs") -> dict:
    """与历史数据对比。

    Args:
        current_data: 当前数据
        current_analysis: 当前分析结果
        history_dir: 历史数据目录

    Returns:
        对比结果
    """
    # 加载历史日志
    logs = list_data_logs(history_dir)
    if not logs:
        return {"success": False, "error": "没有历史数据"}

    # 加载最新的历史数据
    latest_log = logs[0]
    history_result = load_data_log(latest_log["filepath"])
    if not history_result.get("success"):
        return {"success": False, "error": "加载历史数据失败"}

    history_data = history_result["data"].get("data", {})
    history_analysis = history_result["data"].get("analysis", {})

    # 对比结果
    comparison = {
        "success": True,
        "current": {
            "timestamp": current_data.get("timestamp"),
            "value_count": current_data.get("value_count"),
            "issues": current_analysis.get("issue_count", 0),
        },
        "history": {
            "timestamp": history_data.get("timestamp"),
            "value_count": history_data.get("value_count"),
            "issues": history_analysis.get("issue_count", 0),
        },
        "changes": [],
    }

    # 对比数值统计
    current_values = current_data.get("values", [])
    history_values = history_data.get("values", [])

    if current_values and history_values:
        current_mean = sum(current_values) / len(current_values)
        history_mean = sum(history_values) / len(history_values)

        comparison["statistics"] = {
            "current_mean": current_mean,
            "history_mean": history_mean,
            "mean_change": current_mean - history_mean,
            "mean_change_percent": ((current_mean - history_mean) / history_mean * 100) if history_mean != 0 else 0,
        }

        # 检查是否有改善
        current_issues = current_analysis.get("issue_count", 0)
        history_issues = history_analysis.get("issue_count", 0)

        if current_issues < history_issues:
            comparison["changes"].append({
                "type": "improvement",
                "description": f"问题数减少: {history_issues} → {current_issues}",
            })
        elif current_issues > history_issues:
            comparison["changes"].append({
                "type": "regression",
                "description": f"问题数增加: {history_issues} → {current_issues}",
            })

    # 打印对比结果
    print_comparison_result(comparison)

    return comparison


def print_comparison_result(comparison: dict):
    """打印对比结果。"""
    print(f"\n历史对比:")
    print(f"  当前数据: {comparison['current']['value_count']} 个数值, {comparison['current']['issues']} 个问题")
    print(f"  历史数据: {comparison['history']['value_count']} 个数值, {comparison['history']['issues']} 个问题")

    if comparison.get("statistics"):
        stats = comparison["statistics"]
        print(f"  平均值变化: {stats['mean_change']:.2f} ({stats['mean_change_percent']:.1f}%)")

    if comparison.get("changes"):
        print(f"  变化:")
        for change in comparison["changes"]:
            if change["type"] == "improvement":
                print(f"    ✅ {change['description']}")
            elif change["type"] == "regression":
                print(f"    ⚠️ {change['description']}")
    else:
        print(f"  无明显变化")


# === 完成通知 ===

def send_notification(title: str, message: str, method: str = "print") -> dict:
    """发送通知。

    Args:
        title: 通知标题
        message: 通知内容
        method: 通知方法 (print/file/sound)

    Returns:
        通知结果
    """
    if method == "print":
        print(f"\n{'='*60}")
        print(f"🔔 {title}")
        print(f"{'='*60}")
        print(message)
        print(f"{'='*60}")

    elif method == "file":
        # 保存到通知文件
        try:
            notification_file = "notifications.log"
            with open(notification_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] {title}\n")
                f.write(f"{message}\n\n")
            print(f"通知已保存到: {notification_file}")
        except Exception as e:
            print(f"保存通知失败: {e}")

    elif method == "sound":
        # 发送声音通知
        try:
            import winsound
            winsound.Beep(1000, 500)  # 1000Hz, 500ms
            print("声音通知已发送")
        except Exception:
            print("声音通知不可用")

    return {"success": True, "method": method}


def generate_completion_report(results: dict, output: str = None) -> str:
    """生成完成报告。

    Args:
        results: 闭环调试结果
        output: 输出文件路径

    Returns:
        报告内容
    """
    lines = []

    lines.append("# 闭环调试完成报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().isoformat()}")
    lines.append("")

    # 摘要
    lines.append("## 摘要")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 总迭代次数 | {results.get('total_iterations', 0)} |")
    lines.append(f"| 成功次数 | {sum(1 for r in results.get('iterations', []) if r.get('success'))} |")
    lines.append(f"| 失败次数 | {sum(1 for r in results.get('iterations', []) if not r.get('success'))} |")
    lines.append(f"| 最终状态 | {'✅ 成功' if results.get('success') else '❌ 失败'} |")
    lines.append("")

    # 迭代详情
    lines.append("## 迭代详情")
    lines.append("")
    lines.append(f"| 轮次 | 状态 | 问题数 | 说明 |")
    lines.append(f"|------|------|--------|------|")
    for iteration in results.get("iterations", []):
        status = "✅" if iteration.get("success") else "❌"
        issues = iteration.get("issues", "N/A")
        error = iteration.get("error", "")
        lines.append(f"| {iteration.get('iteration', 'N/A')} | {status} | {issues} | {error[:50]} |")
    lines.append("")

    # 结论
    lines.append("## 结论")
    lines.append("")
    if results.get("success"):
        lines.append("闭环调试成功完成，所有问题已修复。")
    else:
        lines.append("闭环调试未能完全解决问题，建议手动检查代码。")
    lines.append("")

    report = "\n".join(lines)

    if output:
        try:
            with open(output, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"完成报告已保存: {output}")
        except Exception as e:
            print(f"保存完成报告失败: {e}")

    return report


# === 批量测试 ===

def run_batch_tests(tests: list[dict], output_dir: str = "batch_results") -> dict:
    """运行批量测试。

    Args:
        tests: 测试列表
        output_dir: 输出目录

    Returns:
        批量测试结果
    """
    import os

    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)

    print(f"批量测试: {len(tests)} 个测试")
    print("=" * 60)

    results = []

    for i, test in enumerate(tests, 1):
        print(f"\n测试 {i}/{len(tests)}: {test.get('name', '未命名')}")
        print("-" * 40)

        try:
            # 运行测试
            result = auto_loop(
                port=test.get("port", "COM3"),
                baud=test.get("baud", 115200),
                project_dir=test.get("project_dir", "."),
                duration=test.get("duration", 10),
                min_val=test.get("min_val"),
                max_val=test.get("max_val"),
                jump_threshold=test.get("jump_threshold"),
                max_iterations=test.get("max_iterations", 3),
                reset_method=test.get("reset_method", "dtr"),
            )

            results.append({
                "test_index": i,
                "test_name": test.get("name", "未命名"),
                "success": result.get("success"),
                "iterations": result.get("total_iterations"),
            })

        except Exception as e:
            print(f"测试失败: {e}")
            results.append({
                "test_index": i,
                "test_name": test.get("name", "未命名"),
                "success": False,
                "error": str(e),
            })

    # 生成批量测试报告
    report = generate_batch_report(results, output_dir)

    # 发送通知
    success_count = sum(1 for r in results if r.get("success"))
    send_notification(
        "批量测试完成",
        f"完成 {len(results)} 个测试，成功 {success_count} 个",
    )

    return {
        "success": all(r.get("success") for r in results),
        "total_tests": len(tests),
        "success_count": success_count,
        "results": results,
    }


def generate_batch_report(results: list[dict], output_dir: str = "batch_results") -> str:
    """生成批量测试报告。

    Args:
        results: 测试结果列表
        output_dir: 输出目录

    Returns:
        报告内容
    """
    lines = []

    lines.append("# 批量测试报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().isoformat()}")
    lines.append("")

    # 摘要
    lines.append("## 摘要")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 总测试数 | {len(results)} |")
    lines.append(f"| 成功数 | {sum(1 for r in results if r.get('success'))} |")
    lines.append(f"| 失败数 | {sum(1 for r in results if not r.get('success'))} |")
    lines.append(f"| 成功率 | {sum(1 for r in results if r.get('success')) / len(results) * 100:.1f}% |")
    lines.append("")

    # 测试详情
    lines.append("## 测试详情")
    lines.append("")
    lines.append(f"| 序号 | 名称 | 状态 | 迭代次数 | 说明 |")
    lines.append(f"|------|------|------|----------|------|")
    for result in results:
        status = "✅" if result.get("success") else "❌"
        iterations = result.get("iterations", "N/A")
        error = result.get("error", "")
        lines.append(f"| {result.get('test_index', 'N/A')} | {result.get('test_name', 'N/A')} | {status} | {iterations} | {error[:30]} |")
    lines.append("")

    report = "\n".join(lines)

    # 保存报告
    try:
        report_file = os.path.join(output_dir, "batch_report.md")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"批量测试报告已保存: {report_file}")
    except Exception as e:
        print(f"保存批量测试报告失败: {e}")

    return report


def generate_adaptive_filter_code() -> str:
    """生成自适应滤波代码。"""
    return '''
// 自适应滤波（LMS 算法）
typedef struct {
    float *weights;
    float *buffer;
    int order;
    float mu;  // 步长
} AdaptiveFilter;

void adaptive_init(AdaptiveFilter *af, int order, float mu) {
    af->order = order;
    af->mu = mu;
    af->weights = (float *)calloc(order, sizeof(float));
    af->buffer = (float *)calloc(order, sizeof(float));
}

float adaptive_update(AdaptiveFilter *af, float input, float desired) {
    // 移位缓冲区
    for (int i = af->order - 1; i > 0; i--) {
        af->buffer[i] = af->buffer[i - 1];
    }
    af->buffer[0] = input;

    // 计算输出
    float output = 0;
    for (int i = 0; i < af->order; i++) {
        output += af->weights[i] * af->buffer[i];
    }

    // 计算误差
    float error = desired - output;

    // 更新权重
    for (int i = 0; i < af->order; i++) {
        af->weights[i] += 2 * af->mu * error * af->buffer[i];
    }

    return output;
}

// 使用示例
// AdaptiveFilter af;
// adaptive_init(&af, 10, 0.01);
// float filtered = adaptive_update(&af, raw_value, desired_value);
'''


def generate_butterworth_filter_code() -> str:
    """生成巴特沃斯滤波代码。"""
    return '''
// 一阶巴特沃斯低通滤波
typedef struct {
    float a;  // 滤波系数
    float y;  // 上一次输出
    int initialized;
} ButterworthFilter;

void butterworth_init(ButterworthFilter *bf, float cutoff_freq, float sample_freq) {
    float rc = 1.0 / (2 * 3.14159 * cutoff_freq);
    float dt = 1.0 / sample_freq;
    bf->a = dt / (rc + dt);
    bf->y = 0;
    bf->initialized = 0;
}

float butterworth_update(ButterworthFilter *bf, float input) {
    if (!bf->initialized) {
        bf->y = input;
        bf->initialized = 1;
        return input;
    }

    bf->y = bf->y + bf->a * (input - bf->y);
    return bf->y;
}

// 使用示例
// ButterworthFilter bf;
// butterworth_init(&bf, 10.0, 100.0);  // 截止频率 10Hz，采样频率 100Hz
// float filtered = butterworth_update(&bf, raw_value);
'''


def generate_savitzky_golay_code() -> str:
    """生成 Savitzky-Golay 滤波代码。"""
    return '''
// Savitzky-Golay 滤波（5 点二次多项式）
float savitzky_golay_5(float *buffer) {
    // 5 点二次多项式系数
    float coeffs[] = {-3, 12, 17, 12, -3};
    float sum = 0;

    for (int i = 0; i < 5; i++) {
        sum += coeffs[i] * buffer[i];
    }

    return sum / 35.0;
}

// 使用示例
// float buffer[5] = {v1, v2, v3, v4, v5};
// float filtered = savitzky_golay_5(buffer);
'''


def analyze_jumps(values: list[float], threshold: float = None) -> dict:
    """分析数据跳变。"""
    if len(values) < 2:
        return {"error": "数据不足"}

    diffs = [abs(values[i+1] - values[i]) for i in range(len(values)-1)]
    mean_diff = sum(diffs) / len(diffs)
    max_diff = max(diffs)

    if threshold is None:
        threshold = mean_diff * 3

    jumps = []
    for i, diff in enumerate(diffs):
        if diff > threshold:
            jumps.append({
                "index": i,
                "from": values[i],
                "to": values[i+1],
                "diff": diff,
                "threshold": threshold,
            })

    return {
        "count": len(values),
        "mean_diff": mean_diff,
        "max_diff": max_diff,
        "threshold": threshold,
        "jumps": jumps,
        "jump_count": len(jumps),
    }


def analyze_continuity(values: list[float], expected_interval: float,
                       tolerance: float = 0.1) -> dict:
    """分析数据连续性。"""
    if len(values) < 2:
        return {"error": "数据不足"}

    diffs = [values[i+1] - values[i] for i in range(len(values)-1)]
    mean_diff = sum(diffs) / len(diffs)
    std_diff = (sum((d - mean_diff)**2 for d in diffs) / len(diffs)) ** 0.5

    discontinuities = []
    for i, diff in enumerate(diffs):
        if abs(diff - expected_interval) > expected_interval * tolerance:
            discontinuities.append({
                "index": i,
                "from": values[i],
                "to": values[i+1],
                "diff": diff,
                "expected": expected_interval,
                "deviation": abs(diff - expected_interval),
            })

    return {
        "count": len(values),
        "mean_diff": mean_diff,
        "std_diff": std_diff,
        "expected_interval": expected_interval,
        "discontinuities": discontinuities,
        "discontinuity_count": len(discontinuities),
    }


def analyze_statistics(values: list[float]) -> dict:
    """统计分析。"""
    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean)**2 for x in values) / n
    std_dev = variance ** 0.5

    sorted_values = sorted(values)
    if n % 2 == 0:
        median = (sorted_values[n//2 - 1] + sorted_values[n//2]) / 2
    else:
        median = sorted_values[n//2]

    return {
        "count": n,
        "min": min(values),
        "max": max(values),
        "mean": mean,
        "median": median,
        "std_dev": std_dev,
        "variance": variance,
    }


def print_analysis_result(result: dict):
    """打印分析结果。"""
    analysis = result.get("analysis", {})

    # 范围分析
    if "range" in analysis:
        r = analysis["range"]
        print(f"\n范围分析:")
        print(f"  最小值: {r['min']}")
        print(f"  最大值: {r['max']}")
        print(f"  平均值: {r['mean']:.2f}")
        print(f"  范围: {r['range']:.2f}")
        if r.get("out_of_range"):
            print(f"  ⚠️ 超出范围: {len(r['out_of_range'])} 个")
            for item in r["out_of_range"][:5]:
                print(f"    [{item['index']}] 值: {item['value']} ({item['reason']})")

    # 跳变分析
    if "jump" in analysis:
        j = analysis["jump"]
        print(f"\n跳变分析:")
        print(f"  平均差值: {j['mean_diff']:.2f}")
        print(f"  最大差值: {j['max_diff']:.2f}")
        print(f"  跳变阈值: {j['threshold']:.2f}")
        print(f"  跳变次数: {j['jump_count']}")
        if j.get("jumps"):
            print(f"  ⚠️ 跳变详情:")
            for jump in j["jumps"][:5]:
                print(f"    [{jump['index']}] {jump['from']:.2f} → {jump['to']:.2f} (差值: {jump['diff']:.2f})")

    # 连续性分析
    if "continuity" in analysis:
        c = analysis["continuity"]
        print(f"\n连续性分析:")
        print(f"  预期间隔: {c['expected_interval']}")
        print(f"  实际平均间隔: {c['mean_diff']:.2f}")
        print(f"  标准差: {c['std_diff']:.2f}")
        print(f"  不连续点: {c['discontinuity_count']}")
        if c.get("discontinuities"):
            print(f"  ⚠️ 不连续详情:")
            for disc in c["discontinuities"][:5]:
                print(f"    [{disc['index']}] 间隔: {disc['diff']:.2f} (偏差: {disc['deviation']:.2f})")

    # 统计分析
    if "statistics" in analysis:
        s = analysis["statistics"]
        print(f"\n统计分析:")
        print(f"  中位数: {s['median']:.2f}")
        print(f"  标准差: {s['std_dev']:.2f}")
        print(f"  方差: {s['variance']:.2f}")

    # 问题汇总
    if result.get("issues"):
        print(f"\n⚠️ 发现 {result['issue_count']} 个问题:")
        for issue in result["issues"][:10]:
            if issue["type"] == "out_of_range":
                print(f"  [{issue['index']}] 范围异常: {issue['value']} ({issue['reason']})")
            elif issue["type"] == "jump":
                print(f"  [{issue['index']}] 数据跳变: {issue['from']:.2f} → {issue['to']:.2f}")
            elif issue["type"] == "discontinuity":
                print(f"  [{issue['index']}] 数据不连续: 间隔 {issue['diff']:.2f}")
    else:
        print(f"\n✅ 未发现明显问题")


# === 自动修复代码生成 ===

def generate_fix_code(analysis: dict) -> dict:
    """根据分析结果生成修复代码。

    Args:
        analysis: 数据分析结果

    Returns:
        修复代码
    """
    issues = analysis.get("issues", [])
    if not issues:
        return {"success": False, "error": "没有发现问题"}

    fixes = []

    # 检查范围异常
    if any(i["type"] == "out_of_range" for i in issues):
        fixes.append({
            "type": "range_check",
            "description": "添加范围检查和限幅处理",
            "code": generate_range_check_code(),
        })

    # 检查数据跳变
    if any(i["type"] == "jump" for i in issues):
        fixes.append({
            "type": "median_filter",
            "description": "添加中值滤波",
            "code": generate_median_filter_code(),
        })

    # 检查数据不连续
    if any(i["type"] == "discontinuity" for i in issues):
        fixes.append({
            "type": "moving_average",
            "description": "添加滑动平均滤波",
            "code": generate_moving_average_code(),
        })

    return {
        "success": True,
        "fixes": fixes,
        "fix_count": len(fixes),
    }


def generate_range_check_code() -> str:
    """生成范围检查代码。"""
    return '''
// 范围检查和限幅处理
float range_check(float value, float min_val, float max_val) {
    if (value < min_val) {
        return min_val;
    } else if (value > max_val) {
        return max_val;
    }
    return value;
}

// 使用示例
// float filtered = range_check(raw_value, 0.0, 100.0);
'''


def generate_median_filter_code() -> str:
    """生成中值滤波代码。"""
    return '''
// 中值滤波（窗口大小 5）
float median_filter(float new_value) {
    static float buffer[5] = {0};
    static int index = 0;
    float sorted[5];

    // 更新缓冲区
    buffer[index] = new_value;
    index = (index + 1) % 5;

    // 排序
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

    return sorted[2]; // 返回中值
}

// 使用示例
// float filtered = median_filter(raw_value);
'''


def generate_moving_average_code() -> str:
    """生成滑动平均滤波代码。"""
    return '''
// 滑动平均滤波（窗口大小 10）
float moving_average(float new_value) {
    static float buffer[10] = {0};
    static int index = 0;
    static float sum = 0;

    // 更新缓冲区
    sum -= buffer[index];
    buffer[index] = new_value;
    sum += new_value;
    index = (index + 1) % 10;

    return sum / 10;
}

// 使用示例
// float filtered = moving_average(raw_value);
'''


def generate_limit_filter_code() -> str:
    """生成限幅滤波代码。"""
    return '''
// 限幅滤波
float limit_filter(float new_value, float old_value, float max_delta) {
    float delta = new_value - old_value;
    if (delta > max_delta) {
        return old_value + max_delta;
    } else if (delta < -max_delta) {
        return old_value - max_delta;
    }
    return new_value;
}

// 使用示例
// float filtered = limit_filter(raw_value, last_value, 10.0);
'''


def generate_kalman_filter_code() -> str:
    """生成卡尔曼滤波代码。"""
    return '''
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
    // 预测
    kf->p = kf->p + kf->q;

    // 更新
    kf->k = kf->p / (kf->p + kf->r);
    kf->x = kf->x + kf->k * (measurement - kf->x);
    kf->p = (1 - kf->k) * kf->p;

    return kf->x;
}

// 使用示例
// KalmanFilter kf;
// kalman_init(&kf, 0.01, 0.1, 0.0);
// float filtered = kalman_update(&kf, raw_value);
'''


def generate_ema_filter_code() -> str:
    """生成指数移动平均滤波代码。"""
    return '''
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

// 使用示例
// float filtered = ema_filter(raw_value, 0.1); // alpha 越小，滤波越强
'''


def generate_weighted_average_code() -> str:
    """生成加权平均滤波代码。"""
    return '''
// 加权平均滤波（窗口大小 5）
float weighted_average(float new_value) {
    static float buffer[5] = {0};
    static int index = 0;

    // 更新缓冲区
    buffer[index] = new_value;
    index = (index + 1) % 5;

    // 加权平均（权重：1, 2, 3, 2, 1）
    float weights[] = {1, 2, 3, 2, 1};
    float sum = 0;
    float weight_sum = 0;

    for (int i = 0; i < 5; i++) {
        int idx = (index + i) % 5;
        sum += buffer[idx] * weights[i];
        weight_sum += weights[i];
    }

    return sum / weight_sum;
}

// 使用示例
// float filtered = weighted_average(raw_value);
'''


def generate_combination_filter_code() -> str:
    """生成组合滤波代码。"""
    return '''
// 组合滤波：中值滤波 + 滑动平均
float combination_filter(float new_value) {
    // 第一级：中值滤波去除脉冲噪声
    float median_filtered = median_filter(new_value);

    // 第二级：滑动平均平滑数据
    float final_filtered = moving_average(median_filtered);

    return final_filtered;
}

// 使用示例
// float filtered = combination_filter(raw_value);
'''


# === 工作流集成 ===

def compile_and_flash(project_dir: str, port: str = None, reset: bool = True) -> dict:
    """编译并烧录固件。

    Args:
        project_dir: 项目目录
        port: 串口号（烧录用）
        reset: 烧录后是否复位

    Returns:
        编译烧录结果
    """
    import subprocess

    # 查找 workflow.py
    workflow_script = Path(__file__).parent.parent.parent / "stm32-keil-workflow" / "scripts" / "workflow.py"
    if not workflow_script.exists():
        return {"success": False, "error": "workflow.py 未找到"}

    # 构建命令
    cmd = [sys.executable, str(workflow_script), "--auto", project_dir, "--steps", "compile,flash"]
    if port:
        cmd.extend(["--port", port])

    print(f"编译烧录: {' '.join(cmd)}")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        result = {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }

        # 烧录后复位
        if result["success"] and reset and port:
            print("烧录成功，复位设备...")
            reset_result = reset_device(port)
            result["reset"] = reset_result

        return result
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "编译烧录超时"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def reset_device(port: str, baud: int = 115200, method: str = "dtr") -> dict:
    """复位设备。

    Args:
        port: 串口号
        baud: 波特率
        method: 复位方法 (dtr/rts/break/custom)

    Returns:
        复位结果
    """
    try:
        ser = serial.Serial(port=port, baudrate=baud, timeout=1)

        if method == "dtr":
            # DTR 信号复位
            ser.dtr = False
            time.sleep(0.1)
            ser.dtr = True
            time.sleep(0.1)

        elif method == "rts":
            # RTS 信号复位
            ser.rts = False
            time.sleep(0.1)
            ser.rts = True
            time.sleep(0.1)

        elif method == "break":
            # BREAK 信号复位
            ser.send_break(duration=0.1)
            time.sleep(0.1)

        elif method == "custom":
            # 自定义复位序列
            ser.dtr = False
            ser.rts = False
            time.sleep(0.1)
            ser.dtr = True
            ser.rts = True
            time.sleep(0.1)

        ser.close()

        print(f"设备已复位 (方法: {method})")
        return {"success": True, "method": method}

    except Exception as e:
        print(f"复位失败: {e}")
        return {"success": False, "error": str(e)}


def run_workflow_step(project_dir: str, steps: list[str], port: str = None) -> dict:
    """运行工作流步骤。

    Args:
        project_dir: 项目目录
        steps: 步骤列表
        port: 串口号

    Returns:
        工作流结果
    """
    import subprocess

    # 查找 workflow.py
    workflow_script = Path(__file__).parent.parent.parent / "stm32-keil-workflow" / "scripts" / "workflow.py"
    if not workflow_script.exists():
        return {"success": False, "error": "workflow.py 未找到"}

    # 构建命令
    cmd = [sys.executable, str(workflow_script), "--auto", project_dir, "--steps", ",".join(steps)]
    if port:
        cmd.extend(["--port", port])

    print(f"运行工作流: {' '.join(cmd)}")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "工作流超时"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def auto_loop(port: str, baud: int, project_dir: str, duration: float,
              min_val: float = None, max_val: float = None,
              jump_threshold: float = None, max_iterations: int = 5,
              reset_method: str = "dtr", retry_on_failure: bool = True,
              timeout: int = 300, retry_delay: float = 2.0) -> dict:
    """自动闭环调试。

    Args:
        port: 串口号
        baud: 波特率
        project_dir: 项目目录
        duration: 采集时长
        min_val: 最小值阈值
        max_val: 最大值阈值
        jump_threshold: 跳变阈值
        max_iterations: 最大迭代次数
        reset_method: 复位方法
        retry_on_failure: 失败时是否重试
        timeout: 超时时间（秒）
        retry_delay: 重试延迟（秒）

    Returns:
        闭环调试结果
    """
    print(f"自动闭环调试: 最多 {max_iterations} 轮, 超时 {timeout}s")
    print("=" * 60)

    # 创建进度跟踪器
    progress = ProgressTracker(max_iterations, "自动闭环调试")

    # 超时管理
    start_time = time.time()

    results = []
    consecutive_failures = 0
    max_consecutive_failures = 3

    for iteration in range(1, max_iterations + 1):
        print(f"\n{'='*60}")
        print(f"第 {iteration} 轮调试")
        print(f"{'='*60}")

        # 更新进度
        progress.update(iteration, f"第 {iteration} 轮调试")

        try:
            # 步骤 1：数据采集
            print(f"\n[1/4] 数据采集 ({duration}s)...")
            data = collect_data(port, baud, duration)
            if not data.get("success"):
                print(f"数据采集失败: {data.get('error')}")
                consecutive_failures += 1
                results.append({
                    "iteration": iteration,
                    "success": False,
                    "error": data.get("error"),
                    "consecutive_failures": consecutive_failures,
                })

                # 检查是否连续失败
                if consecutive_failures >= max_consecutive_failures:
                    print(f"连续失败 {consecutive_failures} 次，停止调试")
                    break

                # 重试
                if retry_on_failure:
                    print("等待 2 秒后重试...")
                    time.sleep(2)
                continue

            # 重置连续失败计数
            consecutive_failures = 0

            # 步骤 2：数据分析
            print(f"\n[2/4] 数据分析...")
            analysis = analyze_data(data, min_val, max_val, jump_threshold)

            # 步骤 3：判断是否需要修复
            if not analysis.get("issues"):
                print(f"\n✅ 第 {iteration} 轮：未发现问题，调试完成")
                results.append({
                    "iteration": iteration,
                    "success": True,
                    "issues": 0,
                    "data_summary": {
                        "value_count": data.get("value_count", 0),
                        "duration": duration,
                    },
                })
                break

            print(f"\n[3/4] 发现 {analysis['issue_count']} 个问题，生成修复代码...")
            fix_result = generate_fix_code(analysis)
            if fix_result.get("success"):
                print(f"生成了 {fix_result['fix_count']} 个修复代码:")
                for fix in fix_result["fixes"]:
                    print(f"  - {fix['description']}")

            # 步骤 4：编译烧录
            print(f"\n[4/4] 编译烧录...")
            flash_result = compile_and_flash(project_dir, port, reset=True)
            if flash_result.get("success"):
                print("编译烧录成功")
                results.append({
                    "iteration": iteration,
                    "success": True,
                    "issues": analysis["issue_count"],
                    "flash": True,
                    "reset": flash_result.get("reset", {}),
                    "fixes": fix_result.get("fixes", []),
                })
            else:
                print(f"编译烧录失败: {flash_result.get('error')}")
                consecutive_failures += 1
                results.append({
                    "iteration": iteration,
                    "success": False,
                    "issues": analysis["issue_count"],
                    "flash": False,
                    "error": flash_result.get("error"),
                    "consecutive_failures": consecutive_failures,
                })

                # 检查是否连续失败
                if consecutive_failures >= max_consecutive_failures:
                    print(f"连续失败 {consecutive_failures} 次，停止调试")
                    break

        except Exception as e:
            print(f"第 {iteration} 轮发生异常: {e}")
            consecutive_failures += 1
            results.append({
                "iteration": iteration,
                "success": False,
                "error": str(e),
                "consecutive_failures": consecutive_failures,
            })

            if consecutive_failures >= max_consecutive_failures:
                print(f"连续失败 {consecutive_failures} 次，停止调试")
                break

    # 完成进度
    progress.finish("闭环调试完成")

    # 生成报告
    print(f"\n{'='*60}")
    print("闭环调试完成")
    print(f"{'='*60}")
    print(f"总迭代次数: {len(results)}")
    print(f"成功次数: {sum(1 for r in results if r.get('success'))}")
    print(f"失败次数: {sum(1 for r in results if not r.get('success'))}")

    return {
        "success": any(r.get("success") for r in results),
        "iterations": results,
        "total_iterations": len(results),
    }


# === 报告生成 ===

def generate_report(data: dict, analysis: dict, output: str = None) -> str:
    """生成调试报告。

    Args:
        data: 采集数据
        analysis: 分析结果
        output: 输出文件路径

    Returns:
        报告内容
    """
    lines = []

    lines.append("# STM32 串口闭环调试报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().isoformat()}")
    lines.append("")

    # 数据概览
    lines.append("## 数据概览")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 串口 | {data.get('port', 'N/A')} |")
    lines.append(f"| 波特率 | {data.get('baud', 'N/A')} |")
    lines.append(f"| 采集时长 | {data.get('duration', 'N/A')} 秒 |")
    lines.append(f"| 数据条数 | {len(data.get('entries', []))} |")
    lines.append(f"| 数值个数 | {len(data.get('values', []))} |")
    lines.append("")

    # 分析结果
    if analysis.get("success"):
        a = analysis.get("analysis", {})

        # 范围分析
        if "range" in a:
            r = a["range"]
            lines.append("## 范围分析")
            lines.append("")
            lines.append(f"| 指标 | 值 |")
            lines.append(f"|------|-----|")
            lines.append(f"| 最小值 | {r['min']:.2f} |")
            lines.append(f"| 最大值 | {r['max']:.2f} |")
            lines.append(f"| 平均值 | {r['mean']:.2f} |")
            lines.append(f"| 范围 | {r['range']:.2f} |")
            lines.append(f"| 超出范围 | {len(r.get('out_of_range', []))} 个 |")
            lines.append("")

        # 跳变分析
        if "jump" in a:
            j = a["jump"]
            lines.append("## 跳变分析")
            lines.append("")
            lines.append(f"| 指标 | 值 |")
            lines.append(f"|------|-----|")
            lines.append(f"| 平均差值 | {j['mean_diff']:.2f} |")
            lines.append(f"| 最大差值 | {j['max_diff']:.2f} |")
            lines.append(f"| 跳变阈值 | {j['threshold']:.2f} |")
            lines.append(f"| 跳变次数 | {j['jump_count']} |")
            lines.append("")

        # 统计分析
        if "statistics" in a:
            s = a["statistics"]
            lines.append("## 统计分析")
            lines.append("")
            lines.append(f"| 指标 | 值 |")
            lines.append(f"|------|-----|")
            lines.append(f"| 中位数 | {s['median']:.2f} |")
            lines.append(f"| 标准差 | {s['std_dev']:.2f} |")
            lines.append(f"| 方差 | {s['variance']:.2f} |")
            lines.append("")

    # 问题汇总
    if analysis.get("issues"):
        lines.append("## 问题汇总")
        lines.append("")
        lines.append(f"| 类型 | 位置 | 详情 |")
        lines.append(f"|------|------|------|")
        for issue in analysis["issues"][:20]:
            if issue["type"] == "out_of_range":
                lines.append(f"| 范围异常 | [{issue['index']}] | {issue['value']} ({issue['reason']}) |")
            elif issue["type"] == "jump":
                lines.append(f"| 数据跳变 | [{issue['index']}] | {issue['from']:.2f} → {issue['to']:.2f} |")
            elif issue["type"] == "discontinuity":
                lines.append(f"| 数据不连续 | [{issue['index']}] | 间隔 {issue['diff']:.2f} |")
        lines.append("")

    # 修复建议
    if analysis.get("issues"):
        lines.append("## 修复建议")
        lines.append("")
        lines.append("| 问题类型 | 建议修复方法 |")
        lines.append("|---------|-------------|")
        if any(i["type"] == "out_of_range" for i in analysis["issues"]):
            lines.append("| 范围异常 | 添加范围检查、限幅处理 |")
        if any(i["type"] == "jump" for i in analysis["issues"]):
            lines.append("| 数据跳变 | 添加中值滤波、卡尔曼滤波 |")
        if any(i["type"] == "discontinuity" for i in analysis["issues"]):
            lines.append("| 数据不连续 | 增加缓冲区、优化中断处理 |")
        lines.append("")

    report = "\n".join(lines)

    if output:
        Path(output).write_text(report, encoding="utf-8")
        print(f"报告已保存: {output}")

    return report


# === CLI ===

def main() -> int:
    parser = argparse.ArgumentParser(
        description="STM32 串口闭环调试脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --port COM3 --mode collect --duration 10
  %(prog)s --port COM3 --mode analyze --duration 10 --min-val 0 --max-val 100
  %(prog)s --port COM3 --mode loop --duration 10 --max-val 100
  %(prog)s --mode analyze --input data.json --min-val 0 --max-val 100
        """,
    )

    parser.add_argument("--port", help="串口号 (如 COM3)")
    parser.add_argument("--baud", type=int, default=115200, help="波特率 (默认 115200)")
    parser.add_argument("--mode", choices=["collect", "analyze", "loop", "report"],
                        default="collect", help="工作模式")
    parser.add_argument("--duration", type=float, default=10, help="采集时长 (秒)")
    parser.add_argument("--protocol", choices=["text", "hex", "vofa"], default="text",
                        help="协议类型")
    parser.add_argument("--min-val", type=float, help="最小值阈值")
    parser.add_argument("--max-val", type=float, help="最大值阈值")
    parser.add_argument("--jump-threshold", type=float, help="跳变阈值")
    parser.add_argument("--expected-interval", type=float, help="预期间隔")
    parser.add_argument("--input", help="输入数据文件")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--list", action="store_true", help="列出可用串口")

    args = parser.parse_args()

    if args.list:
        ports = serial.tools.list_ports.comports()
        if not ports:
            print("未找到可用串口")
            return 1
        print("可用串口:")
        for p in ports:
            print(f"  {p.device}: {p.description}")
        return 0

    if args.mode == "collect":
        if not args.port:
            parser.error("collect 模式需要 --port")
        result = collect_data(args.port, args.baud, args.duration, args.protocol)
        if args.output:
            Path(args.output).write_text(
                json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"数据已保存: {args.output}")

    elif args.mode == "analyze":
        if args.input:
            data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        elif args.port:
            data = collect_data(args.port, args.baud, args.duration, args.protocol)
        else:
            parser.error("analyze 模式需要 --input 或 --port")

        result = analyze_data(data, args.min_val, args.max_val,
                             args.jump_threshold, args.expected_interval)
        if args.output:
            Path(args.output).write_text(
                json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"分析结果已保存: {args.output}")

    elif args.mode == "loop":
        if not args.port:
            parser.error("loop 模式需要 --port")

        # 步骤 1：数据采集
        print("=" * 60)
        print("步骤 1: 数据采集")
        print("=" * 60)
        data = collect_data(args.port, args.baud, args.duration, args.protocol)

        if not data.get("success"):
            print(f"数据采集失败: {data.get('error')}")
            return 1

        # 步骤 2：数据分析
        print("\n" + "=" * 60)
        print("步骤 2: 数据分析")
        print("=" * 60)
        analysis = analyze_data(data, args.min_val, args.max_val,
                               args.jump_threshold, args.expected_interval)

        # 步骤 3：生成报告
        print("\n" + "=" * 60)
        print("步骤 3: 生成报告")
        print("=" * 60)
        output = args.output or "loop_report.md"
        generate_report(data, analysis, output)

        # 步骤 4：判断是否需要修复
        if analysis.get("issues"):
            print("\n" + "=" * 60)
            print("⚠️ 发现问题，建议进行代码修复")
            print("=" * 60)
            print("\n修复建议:")
            for issue in analysis["issues"][:5]:
                if issue["type"] == "out_of_range":
                    print(f"  - 范围异常: 添加范围检查和限幅处理")
                elif issue["type"] == "jump":
                    print(f"  - 数据跳变: 添加中值滤波或滑动平均滤波")
                elif issue["type"] == "discontinuity":
                    print(f"  - 数据不连续: 增加缓冲区或优化中断处理")
        else:
            print("\n✅ 未发现明显问题，调试完成")

    elif args.mode == "report":
        if not args.input:
            parser.error("report 模式需要 --input")
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        analysis = analyze_data(data, args.min_val, args.max_val,
                               args.jump_threshold, args.expected_interval)
        generate_report(data, analysis, args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
