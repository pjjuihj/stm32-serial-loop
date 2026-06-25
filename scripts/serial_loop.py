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
import fnmatch
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


# === stm32-keil-workflow 集成 ===

# 查找 stm32-keil-workflow 的 shared.py
_SKILL_DIR = Path(__file__).parent.parent.parent
_SHARED_PY = _SKILL_DIR / "stm32-keil-workflow" / "scripts" / "shared.py"
_WORKFLOW_PY = _SKILL_DIR / "stm32-keil-workflow" / "scripts" / "workflow.py"
_ERROR_TRACKER_PY = _SKILL_DIR / "stm32-keil-workflow" / "scripts" / "error_tracker.py"
_ERROR_SUMMARY_PY = _SKILL_DIR / "stm32-keil-workflow" / "scripts" / "error_summary.py"
_TECH_SPEC_PY = _SKILL_DIR / "stm32-keil-workflow" / "scripts" / "tech_spec.py"
_HEALTH_CHECK_PY = _SKILL_DIR / "stm32-keil-workflow" / "scripts" / "health_check.py"
_BRICK_PREVENTION_PY = _SKILL_DIR / "stm32-keil-workflow" / "scripts" / "brick_prevention.py"
_DETECT_CONFIG_PY = _SKILL_DIR / "stm32-keil-workflow" / "scripts" / "detect_config.py"

# 导入 shared.py（如果存在）
_shared = None
if _SHARED_PY.exists():
    sys.path.insert(0, str(_SHARED_PY.parent))
    try:
        import shared as _shared
    except ImportError:
        pass


def _find_script(name: str) -> Path | None:
    """查找 stm32-keil-workflow 中的脚本。"""
    path = _SKILL_DIR / "stm32-keil-workflow" / "scripts" / name
    return path if path.exists() else None


def _run_workflow_script(script_path: Path, args: list[str],
                         timeout: int = 300) -> dict:
    """运行 stm32-keil-workflow 脚本。

    Args:
        script_path: 脚本路径
        args: 命令行参数
        timeout: 超时时间（秒）

    Returns:
        执行结果
    """
    import subprocess

    cmd = [sys.executable, str(script_path)] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"脚本超时 ({timeout}s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def detect_project(project_dir: str = ".") -> dict:
    """自动检测项目配置。

    Args:
        project_dir: 项目目录

    Returns:
        项目配置
    """
    project_path = Path(project_dir).resolve()
    result = {
        "project_dir": str(project_path),
        "uvprojx": None,
        "ioc": None,
        "axf": None,
        "workflow_result": None,
    }

    # 查找 .uvprojx
    uvprojx_files = list(project_path.glob("**/*.uvprojx"))
    if uvprojx_files:
        result["uvprojx"] = str(uvprojx_files[0])

    # 查找 .ioc
    ioc_files = list(project_path.glob("**/*.ioc"))
    if ioc_files:
        result["ioc"] = str(ioc_files[0])

    # 查找 .axf
    axf_files = list(project_path.glob("**/*.axf"))
    if axf_files:
        result["axf"] = str(axf_files[0])

    # 查找 workflow_result.json
    workflow_result = project_path / "workflow_result.json"
    if workflow_result.exists():
        try:
            result["workflow_result"] = json.loads(
                workflow_result.read_text(encoding="utf-8"))
        except Exception:
            pass

    return result


def run_health_check(project_dir: str = ".") -> dict:
    """运行项目健康检查。

    Args:
        project_dir: 项目目录

    Returns:
        健康检查结果
    """
    if not _HEALTH_CHECK_PY.exists():
        return {"success": False, "error": "health_check.py 未找到"}

    return _run_workflow_script(
        _HEALTH_CHECK_PY,
        ["--project", project_dir],
        timeout=60,
    )


def run_brick_check(project_dir: str = ".") -> dict:
    """运行死机预防检查。

    Args:
        project_dir: 项目目录

    Returns:
        死机检查结果
    """
    if not _BRICK_PREVENTION_PY.exists():
        return {"success": False, "error": "brick_prevention.py 未找到"}

    return _run_workflow_script(
        _BRICK_PREVENTION_PY,
        ["--auto", project_dir],
        timeout=60,
    )


def run_error_summary(project_dir: str = ".") -> dict:
    """运行错误总结。

    Args:
        project_dir: 项目目录

    Returns:
        错误总结结果
    """
    if not _ERROR_SUMMARY_PY.exists():
        return {"success": False, "error": "error_summary.py 未找到"}

    return _run_workflow_script(
        _ERROR_SUMMARY_PY,
        ["--auto", project_dir, "--text"],
        timeout=60,
    )


def run_tech_spec(project_dir: str = ".") -> dict:
    """生成技术规范。

    Args:
        project_dir: 项目目录

    Returns:
        技术规范结果
    """
    if not _TECH_SPEC_PY.exists():
        return {"success": False, "error": "tech_spec.py 未找到"}

    return _run_workflow_script(
        _TECH_SPEC_PY,
        ["--auto", project_dir, "--text"],
        timeout=60,
    )


def detect_config(project_dir: str = ".") -> dict:
    """检测项目配置。

    Args:
        project_dir: 项目目录

    Returns:
        配置检测结果
    """
    if not _DETECT_CONFIG_PY.exists():
        return {"success": False, "error": "detect_config.py 未找到"}

    return _run_workflow_script(
        _DETECT_CONFIG_PY,
        ["--scan", project_dir],
        timeout=30,
    )


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


# === 配置系统 ===

# 默认配置（可通过 --config JSON 文件或 CLI 参数覆盖）
DEFAULT_CONFIG = {
    "build_marker": "BUILD:",
    "heartbeat_prefixes": ["HB", "STATUS", "DBG", "DIAG"],
    "register_bits": {
        "en":    {"bit": 0,  "width": 1},
        "circ":  {"bit": 8,  "width": 1},
        "minc":  {"bit": 10, "width": 1},
        "psize": {"bit": 11, "width": 2},
        "msize": {"bit": 13, "width": 2},
    },
    "register_name_pattern": r"(?:DMA_)?CR|SR|CSR|ISR",
    "issue_rules": [
        {"field": "h",      "op": "<=", "value": 1, "type": "counter_stopped"},
        {"field": "c",      "op": "<=", "value": 1, "type": "counter_stopped"},
        {"field": "*_circ", "op": "==",  "value": 0, "type": "no_circ"},
    ],
}

_config = dict(DEFAULT_CONFIG)


def _rule_match(value, op: str, threshold) -> bool:
    """通用规则匹配。支持 ==, !=, <, <=, >, >=。"""
    try:
        if op == "==":  return value == threshold
        if op == "!=":  return value != threshold
        if op == "<":   return value < threshold
        if op == "<=":  return value <= threshold
        if op == ">":   return value > threshold
        if op == ">=":  return value >= threshold
    except TypeError:
        pass
    return False


def _rule_match_field(pattern: str, key: str) -> bool:
    """字段名通配符匹配。支持 * 和 ?（如 dma_*, *_circ, *_cr_*）。"""
    if pattern.startswith("*"):
        return fnmatch.fnmatch(key, pattern)
    return key == pattern


def _validate_config(cfg: dict) -> list[str]:
    """验证配置格式，返回错误列表。"""
    errors = []
    if "heartbeat_prefixes" in cfg and not isinstance(cfg["heartbeat_prefixes"], list):
        errors.append("heartbeat_prefixes 必须是字符串数组")
    if "register_bits" in cfg:
        if not isinstance(cfg["register_bits"], dict):
            errors.append("register_bits 必须是对象")
        else:
            for name, defn in cfg["register_bits"].items():
                if not isinstance(defn, dict) or "bit" not in defn:
                    errors.append(f"register_bits.{name} 必须包含 bit 字段")
    if "issue_rules" in cfg:
        if not isinstance(cfg["issue_rules"], list):
            errors.append("issue_rules 必须是数组")
        else:
            for i, rule in enumerate(cfg["issue_rules"]):
                for key in ("field", "op", "value", "type"):
                    if key not in rule:
                        errors.append(f"issue_rules[{i}] 缺少 {key} 字段")
    return errors


def load_config(config_path: str = None, cli_overrides: dict = None) -> dict:
    """加载配置。JSON 文件 + CLI 覆盖。"""
    global _config
    _config = dict(DEFAULT_CONFIG)
    if config_path:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
            errors = _validate_config(file_cfg)
            if errors:
                for err in errors:
                    print(f"⚠️ 配置错误: {err}")
                print("使用默认配置")
            else:
                _config.update(file_cfg)
                print(f"配置已加载: {config_path}")
        except json.JSONDecodeError as e:
            print(f"⚠️ 配置文件 JSON 格式错误: {e}")
        except Exception as e:
            print(f"⚠️ 配置加载失败: {e}")
    if cli_overrides:
        for k, v in cli_overrides.items():
            if v is not None:
                if k == "heartbeat_prefix" and isinstance(v, str):
                    _config["heartbeat_prefixes"] = [p.strip() for p in v.split(",")]
                elif k == "build_marker" and isinstance(v, str):
                    _config["build_marker"] = v
                else:
                    _config[k] = v
    return _config


# === 常量 ===

MAX_ERRORS = 100  # 最大错误数
PROGRESS_BAR_LENGTH = 40  # 进度条长度
SERIAL_TIMEOUT = 0.1  # 串口超时（秒）
RETRY_DELAY = 1  # 重试延迟（秒）
SUBPROCESS_TIMEOUT_SHORT = 30  # subprocess 短超时（秒）
SUBPROCESS_TIMEOUT_COMPILE = 300  # 编译烧录超时（秒）
SUBPROCESS_TIMEOUT_WORKFLOW = 600  # 工作流超时（秒）
RESET_TIMEOUT = 5.0  # 串口复位打开超时（秒）
MAX_CONSECUTIVE_FAILURES = 3  # 最大连续失败次数
RESET_SIGNAL_DELAY = 0.1  # 复位信号持续时间（秒）
RESET_BOOT_DELAY = 0.5    # 复位后等待设备启动时间（秒）
TREND_SLOPE_THRESHOLD = 0.1  # 趋势斜率阈值
R_SQUARED_THRESHOLD = 0.7  # R² 阈值
OUTLIER_Z_THRESHOLD = 2.0  # 异常值 Z-score 阈值
STABILITY_THRESHOLD_LOW = 1.0  # 稳定性阈值（低）
STABILITY_THRESHOLD_HIGH = 5.0  # 稳定性阈值（高）
PERIODICITY_CONFIDENCE_THRESHOLD = 0.5  # 周期性置信度阈值


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
    entry = {
        "timestamp": round(ts, 3),
        "text": text,
        "values": parse_values(text),
    }

    # 检测编译时间戳（前缀从配置读取）
    build_marker = _config.get("build_marker", "BUILD:")
    if text.startswith(build_marker):
        entry["build_info"] = text[len(build_marker):].strip()

    return entry


def collect_data(port: str, baud: int = 115200, duration: float = 10.0,
                 protocol: str = "text", retry_count: int = 3,
                 filter_keyword: str = None, send_cmds: list[str] = None,
                 send_hex: str = None) -> dict:
    """采集串口数据。

    Args:
        port: 串口号
        baud: 波特率
        duration: 采集时长（秒）
        protocol: 协议类型（text/hex/vofa）
        retry_count: 重试次数
        filter_keyword: 过滤关键字
        send_cmds: 采集前发送的诊断命令列表

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

    # 清空串口缓冲区，避免积压数据混入
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    # 采集前发送诊断命令
    if send_cmds:
        print(f"  发送文本命令: {send_cmds}")
        for cmd in send_cmds:
            ser.write((cmd + "\r\n").encode("utf-8"))
            time.sleep(0.1)
        time.sleep(0.5)

    # 采集前发送十六进制数据
    if send_hex:
        hex_bytes = bytes.fromhex(send_hex.replace(" ", ""))
        print(f"  发送 HEX: {hex_bytes.hex(' ').upper()}")
        ser.write(hex_bytes)
        time.sleep(0.5)

    entries = []
    start = time.time()
    line_buf = bytearray()
    error_count = 0

    build_info = None

    try:
        while time.time() - start < duration:
            # 批量读取：一次读所有可用字节，减少 Python 调用开销
            waiting = ser.in_waiting
            data = ser.read(waiting if waiting > 0 else 1)
            if not data:
                if line_buf:
                    entry = _process_line(line_buf, start, filter_keyword)
                    if entry:
                        entries.append(entry)
                        if entry.get("build_info"):
                            build_info = entry["build_info"]
                        print(f"[{entry['timestamp']:8.3f}] {entry['text']}")
                    line_buf.clear()
                continue

            for b in data:
                if b == ord("\n"):
                    entry = _process_line(line_buf, start, filter_keyword)
                    if entry:
                        entries.append(entry)
                        if entry.get("build_info"):
                            build_info = entry["build_info"]
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
        if ser and ser.is_open:
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
        "build_info": build_info,
        "timestamp": datetime.now().isoformat(),
    }

    # 输出固件版本确认
    if build_info:
        print(f"\n✅ 固件编译时间: {build_info}")
    else:
        print(f"\n⚠️ 未检测到 BUILD 时间戳 — 可能是旧固件")

    print(f"采集完成: {len(entries)} 条数据, {len(all_values)} 个数值")
    return result


def parse_values(text: str) -> list[float]:
    """从文本中提取数值。

    支持格式:
      "temp:25.5,humidity:60.2"
      "25.5,60.2,101.3"
      "ADC:2048"
    """
    values = []

    # 优先匹配 "key:value" 或 "key=value" 格式中的数值
    kv_pattern = r'[:=]\s*(-?\d+\.?\d*)'
    kv_matches = re.findall(kv_pattern, text)
    if kv_matches:
        for match in kv_matches:
            try:
                values.append(float(match))
            except ValueError:
                continue
        return values

    # 回退到通用匹配（要求前后是逗号、空格、行首/行尾或括号）
    pattern = r'(?:^|[,;\s\(])(-?\d+\.?\d*)(?:$|[,;\s\)])'
    matches = re.findall(pattern, text)
    for match in matches:
        try:
            values.append(float(match))
        except ValueError:
            continue
    return values


def parse_heartbeat(text: str, prefix: str = None) -> dict | None:
    """通用心跳解析 — 提取所有 key:value 和 key:0xHEX 对。

    适用于任意嵌入式项目的诊断输出，不限于特定格式。
    寄存器位定义从配置中读取，可自定义。

    Args:
        text: 一行串口文本
        prefix: 心跳行前缀，None 时使用配置中的 heartbeat_prefixes

    Returns:
        解析结果字典，非心跳行返回 None
    """
    cfg = _config
    prefixes = [prefix] if prefix else cfg.get("heartbeat_prefixes", ["HB"])

    matched_prefix = None
    for p in prefixes:
        if text.startswith(p):
            matched_prefix = p
            break
    if not matched_prefix:
        return None

    result = {"raw": text, "prefix": matched_prefix}

    # 解析所有 key:value 对（支持十进制和十六进制）
    kv_pattern = r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(0x[0-9A-Fa-f]+|-?\d+\.?\d*)'
    reg_bits = cfg.get("register_bits", {})
    reg_pattern = cfg.get("register_name_pattern", r"CR|SR")

    for match in re.finditer(kv_pattern, text):
        key = match.group(1).lower()
        val_str = match.group(2)

        if val_str.startswith("0x") or val_str.startswith("0X"):
            val = int(val_str, 16)
            result[key] = val
            # 检查是否匹配寄存器名模式，自动解析位域
            if re.search(reg_pattern, key, re.IGNORECASE):
                for bit_name, bit_def in reg_bits.items():
                    bit_pos = bit_def["bit"]
                    bit_width = bit_def.get("width", 1)
                    mask = (1 << bit_width) - 1
                    result[f"{key}_{bit_name}"] = (val >> bit_pos) & mask
        else:
            try:
                result[key] = float(val_str)
            except ValueError:
                result[key] = val_str

    if len(result) <= 2:
        return None

    return result


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

    # 频率分析（零交越检测）
    freq_result = analyze_frequency(values)
    result["analysis"]["frequency"] = freq_result

    # ADC 卡值检测
    stuck_result = analyze_stuck_at(values)
    result["analysis"]["stuck_at"] = stuck_result

    # 时序分析（如果有时间戳）
    timestamps = [e["timestamp"] for e in entries if "timestamp" in e]
    if len(timestamps) >= 3:
        timing_result = analyze_timing(timestamps)
        result["analysis"]["timing"] = timing_result

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

    # ADC 卡值问题
    if stuck_result.get("stuck_count", 0) > 0:
        for seg in stuck_result["stuck_segments"]:
            issues.append({
                "type": "stuck_at",
                "value": seg["value"],
                "start": seg["start"],
                "length": seg["length"],
                "description": f"ADC 卡在 {seg['value']} 长达 {seg['length']} 个采样点",
            })
    if stuck_result.get("missing_codes"):
        issues.append({
            "type": "missing_codes",
            "unique": stuck_result["unique_values"],
            "total": stuck_result["count"],
            "description": f"只有 {stuck_result['unique_values']} 种值（共 {stuck_result['count']} 个采样点）— ADC 可能缺码",
        })

    # 时序间隙问题
    timing_result = result["analysis"].get("timing", {})
    if timing_result.get("gap_count", 0) > 0:
        for gap in timing_result["gaps"][:5]:
            issues.append({
                "type": "timing_gap",
                "index": gap["index"],
                "interval": gap["interval"],
                "expected": gap["expected"],
                "description": f"采样间隙 {gap['interval']*1000:.1f}ms（预期 {gap['expected']*1000:.1f}ms）",
            })

    # 心跳分析（通用 key:value 解析，规则从配置读取）
    heartbeats = []
    for entry in entries:
        hb = parse_heartbeat(entry["text"])
        if hb:
            heartbeats.append(hb)

    if heartbeats:
        latest = heartbeats[-1]
        # 提取原始字段（排除内部标记和位域展开）
        bit_suffixes = tuple(f"_{name}" for name in _config.get("register_bits", {}))
        fields = {k: v for k, v in latest.items()
                  if k not in ("raw", "prefix") and not k.endswith(bit_suffixes)}
        result["analysis"]["heartbeat"] = {
            "count": len(heartbeats),
            "latest": latest,
            "fields": fields,
        }

        # 使用配置中的 issue_rules 检测问题（支持通配符）
        for rule in _config.get("issue_rules", []):
            field_pattern = rule["field"]
            op = rule["op"]
            threshold = rule["value"]
            issue_type = rule["type"]

            matched_keys = [k for k in latest if _rule_match_field(field_pattern, k)]
            for key in matched_keys:
                val = latest[key]
                if _rule_match(val, op, threshold):
                    issue = {"type": issue_type, "field": key, "value": val}
                    # 尝试关联寄存器原始值
                    for suffix in ("_en", "_circ", "_minc", "_psize", "_msize"):
                        if key.endswith(suffix):
                            issue["register"] = hex(latest.get(key[:-len(suffix)], 0))
                            break
                    issues.append(issue)

    # 无心跳时提示
    if not heartbeats:
        result["analysis"]["heartbeat"] = {
            "count": 0,
            "hint": f"未检测到心跳格式 — 确认固件输出包含前缀 {_config.get('heartbeat_prefixes', ['HB'])}",
        }

    result["issues"] = issues
    result["issue_count"] = len(issues)

    # 打印分析结果
    print_analysis_result(result)

    return result


def analyze_range(values: list[float], min_val: float = None,
                  max_val: float = None) -> dict:
    """分析数据范围。"""
    if not values:
        return {"count": 0, "min": 0, "max": 0, "mean": 0, "range": 0, "out_of_range": []}

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
    if slope > TREND_SLOPE_THRESHOLD:
        trend = "上升"
    elif slope < -TREND_SLOPE_THRESHOLD:
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


def analyze_outliers(values: list[float], threshold: float = OUTLIER_Z_THRESHOLD) -> dict:
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
        "is_periodic": confidence > PERIODICITY_CONFIDENCE_THRESHOLD,
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
    if mean_std < STABILITY_THRESHOLD_LOW:
        stability = "稳定"
    elif mean_std < STABILITY_THRESHOLD_HIGH:
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


def analyze_frequency(values: list[float], sample_rate: float = None) -> dict:
    """零交越频率检测 — 从 ADC 数据估算信号频率。

    Args:
        values: ADC 数值列表
        sample_rate: 采样率 (Hz)，None 时从时间戳估算

    Returns:
        频率分析结果
    """
    if len(values) < 10:
        return {"error": "数据不足"}

    mean = sum(values) / len(values)

    # 零交越检测（相对于均值）
    crossings = []
    for i in range(1, len(values)):
        if (values[i-1] < mean and values[i] >= mean) or \
           (values[i-1] >= mean and values[i] < mean):
            crossings.append(i)

    if len(crossings) < 2:
        return {
            "count": len(values),
            "crossings": len(crossings),
            "frequency": 0,
            "note": "无交越点 — 可能是直流信号或数据不足",
        }

    # 计算平均周期（采样点数）
    intervals = [crossings[i+1] - crossings[i] for i in range(len(crossings)-1)]
    avg_period_samples = sum(intervals) / len(intervals)

    # 计算频率
    frequency = 0
    if sample_rate and sample_rate > 0:
        frequency = sample_rate / avg_period_samples
    else:
        # 无采样率信息，只输出周期（采样点数）
        frequency = None

    return {
        "count": len(values),
        "crossings": len(crossings),
        "avg_period_samples": avg_period_samples,
        "frequency": frequency,
        "intervals": intervals[:10],
        "interval_std": (sum((x - avg_period_samples)**2 for x in intervals) / len(intervals)) ** 0.5,
    }


def analyze_stuck_at(values: list[float], threshold: int = 5) -> dict:
    """ADC 卡值检测 — 检测值是否长时间不变。

    Args:
        values: ADC 数值列表
        threshold: 连续相同值的最小数量

    Returns:
        卡值检测结果
    """
    if len(values) < threshold:
        return {"error": "数据不足"}

    # 检测连续相同值
    stuck_segments = []
    current_val = values[0]
    current_start = 0
    current_count = 1

    for i in range(1, len(values)):
        if values[i] == current_val:
            current_count += 1
        else:
            if current_count >= threshold:
                stuck_segments.append({
                    "value": current_val,
                    "start": current_start,
                    "length": current_count,
                })
            current_val = values[i]
            current_start = i
            current_count = 1

    # 检查最后一段
    if current_count >= threshold:
        stuck_segments.append({
            "value": current_val,
            "start": current_start,
            "length": current_count,
        })

    # 检测值只有 N 种（ADC 缺码）
    unique_values = sorted(set(values))
    unique_ratio = len(unique_values) / len(values)

    return {
        "count": len(values),
        "stuck_segments": stuck_segments,
        "stuck_count": len(stuck_segments),
        "unique_values": len(unique_values),
        "unique_ratio": unique_ratio,
        "missing_codes": unique_ratio < 0.01 and len(values) > 100,
    }


def analyze_timing(timestamps: list[float]) -> dict:
    """时序分析 — 检测采样间隔是否均匀。

    Args:
        timestamps: 时间戳列表（秒）

    Returns:
        时序分析结果
    """
    if len(timestamps) < 3:
        return {"error": "数据不足"}

    intervals = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
    # 过滤掉明显异常的间隔（>10x 中位数）
    sorted_intervals = sorted(intervals)
    median_interval = sorted_intervals[len(sorted_intervals) // 2]
    valid_intervals = [x for x in intervals if x < median_interval * 10]

    if not valid_intervals:
        return {"error": "无有效间隔"}

    mean_interval = sum(valid_intervals) / len(valid_intervals)
    std_interval = (sum((x - mean_interval)**2 for x in valid_intervals) / len(valid_intervals)) ** 0.5
    cv = std_interval / mean_interval if mean_interval > 0 else 0  # 变异系数

    # 检测时序间隙（间隔 > 3x 平均值）
    gaps = []
    for i, interval in enumerate(intervals):
        if interval > mean_interval * 3:
            gaps.append({
                "index": i,
                "interval": interval,
                "expected": mean_interval,
                "ratio": interval / mean_interval,
            })

    # 估算采样率
    sample_rate = 1.0 / mean_interval if mean_interval > 0 else 0

    return {
        "count": len(timestamps),
        "mean_interval": mean_interval,
        "std_interval": std_interval,
        "cv": cv,
        "sample_rate": sample_rate,
        "gaps": gaps[:10],
        "gap_count": len(gaps),
        "jitter_ms": std_interval * 1000,
    }


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

    before_std = (sum((x - before_mean) ** 2 for x in before_values) / len(before_values)) ** 0.5 if len(before_values) > 1 else 0
    after_std = (sum((x - after_mean) ** 2 for x in after_values) / len(after_values)) ** 0.5 if len(after_values) > 1 else 0

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
    script = _find_script("error_tracker.py")
    if not script:
        return []

    result = _run_workflow_script(script, ["--search", keyword, "--text"])
    if not result.get("success"):
        return []

    results = []
    for line in result["stdout"].splitlines():
        if line.startswith("["):
            parts = line.split("->")
            if len(parts) == 2:
                results.append({"error": parts[0].strip(), "fix": parts[1].strip()})
    return results


def get_fix_suggestions_from_history(error_type: str) -> list[dict]:
    """从历史获取修复建议。

    Args:
        error_type: 错误类型

    Returns:
        修复建议列表
    """
    script = _find_script("error_tracker.py")
    if not script:
        return []

    result = _run_workflow_script(script, ["--suggest", error_type, "--text"])
    if not result.get("success"):
        return []

    return [{"suggestion": line[1:].strip()}
            for line in result["stdout"].splitlines()
            if line.startswith("-")]


def record_error_fix(error: str, fix: str, file: str = None) -> bool:
    """记录错误修复。

    Args:
        error: 错误信息
        fix: 修复方法
        file: 关联文件

    Returns:
        是否成功
    """
    script = _find_script("error_tracker.py")
    if not script:
        return False

    args = ["--record", "--error", error, "--fix", fix]
    if file:
        args.extend(["--file", file])

    result = _run_workflow_script(script, args)
    return result.get("success", False)


# === 文档读写 ===

def read_markdown_issues(filepath: str) -> list[dict]:
    """通用 markdown 问题解析器 — 从任意 markdown 文件提取问题条目。

    支持格式:
      ## 1. 标题
      ## 标题（无编号）
      ### 标题
      **问题：** ...
      **根本原因：** ... / **Root Cause：** ...
      **解决方案：** ... / **Fix：** ... / **修复方案：** ...

    Args:
        filepath: markdown 文件路径

    Returns:
        问题条目列表 [{number, title, section_text, keywords}]
    """
    path = Path(filepath)
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    issues = []

    # 匹配任意 ## 或 ### 标题
    heading_pattern = r'^(#{2,3})\s+(?:(\d+)\.\s+)?(.+?)(?:\n|$)'
    headings = list(re.finditer(heading_pattern, content, re.MULTILINE))

    for i, match in enumerate(headings):
        level = len(match.group(1))
        number = int(match.group(2)) if match.group(2) else i + 1
        title = match.group(3).strip()

        # 跳过非问题标题（如"总结"、"概述"等）
        skip_keywords = ("总结", "概述", "目录", "附录", "summary", "overview", "toc", "appendix")
        if any(kw in title.lower() for kw in skip_keywords):
            continue

        # 提取该条目的正文
        start = match.end()
        if i + 1 < len(headings):
            end = headings[i + 1].start()
        else:
            end = len(content)
        body = content[start:end].strip()

        if len(body) < 20:  # 太短的条目跳过
            continue

        # 提取关键词（加粗文本中的关键信息）
        keywords = []
        for kw_match in re.finditer(r'\*\*(.+?)[:：]\*\*', body):
            keywords.append(kw_match.group(1).strip())

        issues.append({
            "number": number,
            "title": title,
            "section_text": body[:500],
            "keywords": keywords,
        })

    return issues


def read_solutions_log(project_dir: str) -> list[dict]:
    """读取项目文档中的已知问题。

    自动搜索 docs/ 目录下的 solutions-log.md、issues.md、problems.md 等文件。

    Args:
        project_dir: 项目目录

    Returns:
        已知问题列表
    """
    docs_dir = Path(project_dir) / "docs"
    if not docs_dir.exists():
        return []

    # 搜索所有可能的问题文档
    issue_files = []
    for name in ("solutions-log.md", "issues.md", "problems.md", "debug-log.md",
                 "troubleshooting.md", "known-issues.md"):
        path = docs_dir / name
        if path.exists():
            issue_files.append(path)

    # 也搜索 docs/ 下所有 .md 文件中包含 "问题" 或 "issue" 的
    for md_file in docs_dir.glob("*.md"):
        if md_file not in issue_files:
            try:
                head = md_file.read_text(encoding="utf-8")[:500]
                if any(kw in head.lower() for kw in ("问题", "issue", "bug", "fix", "solution")):
                    issue_files.append(md_file)
            except Exception:
                continue

    all_issues = []
    for filepath in issue_files:
        issues = read_markdown_issues(str(filepath))
        for issue in issues:
            issue["source_file"] = filepath.name
        all_issues.extend(issues)

    return all_issues


def read_technical_spec(project_dir: str) -> dict:
    """读取 technical-spec.md 中的关键配置。

    Args:
        project_dir: 项目目录

    Returns:
        技术规范关键信息
    """
    spec_path = Path(project_dir) / "docs" / "technical-spec.md"
    if not spec_path.exists():
        return {}

    content = spec_path.read_text(encoding="utf-8")
    result = {"raw_sections": []}

    # 提取已知问题部分
    known_issues_match = re.search(
        r'## CubeMX.*?已知问题.*?\n(.*?)(?=\n## |\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    if known_issues_match:
        result["known_issues"] = known_issues_match.group(1).strip()

    # 提取 DMA 配置
    dma_match = re.search(r'\|\s*DMA.*?\|.*?\|.*?\|.*?\|', content)
    if dma_match:
        result["dma_config"] = dma_match.group(0).strip()

    return result


def check_against_docs(project_dir: str, analysis: dict) -> list[dict]:
    """将分析结果与文档中的已知问题对比。

    Args:
        project_dir: 项目目录
        analysis: 数据分析结果

    Returns:
        匹配的已知问题
    """
    known = read_solutions_log(project_dir)
    if not known:
        return []

    matches = []
    issues = analysis.get("issues", [])

    for issue in issues:
        issue_type = issue.get("type", "")

        for known_issue in known:
            title_lower = known_issue["title"].lower()
            text_lower = known_issue.get("section_text", "").lower()
            keywords = [k.lower() for k in known_issue.get("keywords", [])]
            all_text = title_lower + " " + text_lower + " " + " ".join(keywords)

            # DMA 停止问题
            if issue_type == "counter_stopped" and "dma" in all_text and ("停止" in all_text or "stop" in all_text):
                matches.append({"issue": issue, "known": known_issue})
            # CIRC 位问题
            elif issue_type == "no_circ" and "circ" in all_text:
                matches.append({"issue": issue, "known": known_issue})
            # 数据范围异常 + PSIZE/MSIZE
            elif issue_type == "out_of_range" and ("psize" in all_text or "msize" in all_text):
                matches.append({"issue": issue, "known": known_issue})
            # 计数器不递增 + MasterSlaveMode
            elif issue_type == "counter_stopped" and "masterslavemode" in all_text:
                matches.append({"issue": issue, "known": known_issue})
            # 通用匹配：问题类型关键词出现在标题中
            elif issue_type.replace("_", " ") in title_lower:
                matches.append({"issue": issue, "known": known_issue})

    return matches


def write_debug_log(project_dir: str, iteration: int, analysis: dict,
                    verify_result: dict = None) -> str:
    """将调试结果写入日志文件。

    Args:
        project_dir: 项目目录
        iteration: 迭代轮次
        analysis: 数据分析结果
        verify_result: 验证结果

    Returns:
        日志文件路径
    """
    log_dir = Path(project_dir) / "docs" / "debug_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"debug_{timestamp}_iter{iteration}.md"

    lines = [
        f"# 调试日志 — 第 {iteration} 轮",
        f"",
        f"> 时间: {datetime.now().isoformat()}",
        f"",
    ]

    # 问题列表
    if analysis.get("issues"):
        lines.append("## 发现的问题")
        lines.append("")
        for issue in analysis["issues"]:
            lines.append(f"- **{issue['type']}**: {issue.get('field', '?')}={issue.get('value', '?')}")
        lines.append("")

    # 统计数据
    stats = analysis.get("analysis", {}).get("statistics", {})
    if stats:
        lines.append("## 统计数据")
        lines.append("")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 均值 | {stats.get('mean', 0):.2f} |")
        lines.append(f"| 标准差 | {stats.get('std_dev', 0):.2f} |")
        lines.append(f"| 最小值 | {stats.get('min', 0):.2f} |")
        lines.append(f"| 最大值 | {stats.get('max', 0):.2f} |")
        lines.append("")

    # 验证结果
    if verify_result:
        lines.append("## 验证结果")
        lines.append("")
        lines.append(f"- 状态: {verify_result.get('status', 'N/A')}")
        lines.append(f"- 说明: {verify_result.get('description', 'N/A')}")
        lines.append("")

    content = "\n".join(lines)
    log_file.write_text(content, encoding="utf-8")
    print(f"调试日志已写入: {log_file}")
    return str(log_file)


# === 技术规范集成 ===

def get_project_config(project_dir: str) -> dict:
    """获取项目配置。

    Args:
        project_dir: 项目目录

    Returns:
        项目配置
    """
    script = _find_script("tech_spec.py")
    if not script:
        return {}

    result = _run_workflow_script(script, ["--auto", project_dir, "--text"])
    if not result.get("success"):
        return {}

    config = {}
    for line in result["stdout"].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            config[key.strip()] = value.strip()
    return config


def get_peripheral_config(project_dir: str, peripheral: str) -> dict:
    """获取外设配置。

    Args:
        project_dir: 项目目录
        peripheral: 外设名称

    Returns:
        外设配置
    """
    script = _find_script("cubemx_guide.py")
    if not script:
        return {}

    result = _run_workflow_script(script, ["--peripheral", peripheral])
    if not result.get("success"):
        return {}

    return {"peripheral": peripheral, "guide": result["stdout"]}


def check_pin_conflict(project_dir: str) -> list[dict]:
    """检查引脚冲突。

    Args:
        project_dir: 项目目录

    Returns:
        冲突列表
    """
    script = _find_script("pin_checker.py")
    if not script:
        return []

    ioc_files = list(Path(project_dir).glob("*.ioc"))
    if not ioc_files:
        return []

    result = _run_workflow_script(script, ["--ioc", str(ioc_files[0])])
    if not result.get("success"):
        return []

    return [{"description": line.strip()}
            for line in result["stdout"].splitlines()
            if "conflict" in line.lower()]


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
    try:
        os.makedirs(output_dir, exist_ok=True)
    except PermissionError:
        return {"success": False, "error": f"无权限创建目录: {output_dir}"}
    except OSError as e:
        return {"success": False, "error": f"创建目录失败: {e}"}

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

    except PermissionError:
        print(f"保存数据日志失败: 无权限写入 {filepath}")
        return {"success": False, "error": f"无权限写入: {filepath}"}
    except OSError as e:
        print(f"保存数据日志失败: {e}")
        return {"success": False, "error": f"文件系统错误: {e}"}


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
        # 发送声音通知（跨平台）
        try:
            if sys.platform == "win32":
                import winsound
                winsound.Beep(1000, 500)  # 1000Hz, 500ms
            else:
                print("\a", end="", flush=True)  # BEL 字符
            print("声音通知已发送")
        except ImportError:
            print("声音通知不可用 (winsound 模块缺失)")
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


def analyze_jumps(values: list[float], threshold: float = None) -> dict:
    """分析数据跳变。"""
    if not values:
        return {"count": 0, "mean_diff": 0, "max_diff": 0, "threshold": 0, "jumps": [], "jump_count": 0}
    if len(values) < 2:
        return {"count": len(values), "mean_diff": 0, "max_diff": 0, "threshold": 0, "jumps": [], "jump_count": 0}

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

    # 频率分析
    if "frequency" in analysis:
        f = analysis["frequency"]
        if f.get("frequency") is not None and f["frequency"] > 0:
            print(f"\n频率分析:")
            print(f"  检测频率: {f['frequency']:.1f} Hz")
            print(f"  交越点: {f['crossings']}")
            print(f"  平均周期: {f['avg_period_samples']:.1f} 采样点")
            if f.get("interval_std"):
                print(f"  周期抖动: {f['interval_std']:.2f} 采样点")
        elif f.get("crossings", 0) == 0:
            print(f"\n频率分析: 无交越点 — 直流信号或数据不足")

    # ADC 卡值检测
    if "stuck_at" in analysis:
        sa = analysis["stuck_at"]
        if sa.get("stuck_count", 0) > 0:
            print(f"\n⚠️ ADC 卡值检测:")
            for seg in sa["stuck_segments"][:5]:
                print(f"  值 {seg['value']} 持续 {seg['length']} 个采样点 (起始 [{seg['start']}])")
        if sa.get("missing_codes"):
            print(f"\n⚠️ ADC 缺码: 只有 {sa['unique_values']} 种值（共 {sa['count']} 个采样点）")

    # 时序分析
    if "timing" in analysis:
        t = analysis["timing"]
        print(f"\n时序分析:")
        print(f"  平均间隔: {t['mean_interval']*1000:.3f} ms")
        print(f"  估算采样率: {t['sample_rate']:.1f} Hz")
        print(f"  抖动: {t['jitter_ms']:.3f} ms")
        if t.get("gap_count", 0) > 0:
            print(f"  ⚠️ 时序间隙: {t['gap_count']} 个")
            for gap in t["gaps"][:3]:
                print(f"    [{gap['index']}] {gap['interval']*1000:.1f}ms (预期 {gap['expected']*1000:.1f}ms)")

    # 心跳分析（通用输出）
    if "heartbeat" in analysis:
        hb = analysis["heartbeat"]
        latest = hb["latest"]
        print(f"\n心跳分析 ({latest.get('prefix', '?')}):")
        print(f"  心跳数: {hb['count']}")
        if "dma_running" in hb:
            print(f"  运行状态: {'✅ 运行中' if hb['dma_running'] else '❌ 已停止'}")
        # 输出所有 key:value 字段
        for key, val in hb.get("fields", {}).items():
            if isinstance(val, float) and val == int(val):
                val = int(val)
            if isinstance(val, int):
                if val > 0xFFFF:
                    print(f"  {key.upper()}: 0x{val:08X}")
                else:
                    print(f"  {key.upper()}: {val}")
            else:
                print(f"  {key.upper()}: {val}")
        # 输出寄存器位解析
        for key in latest:
            if key.endswith("_en"):
                base = key[:-3]
                print(f"  {base.upper()}: 0x{latest.get(base, 0):08X} "
                      f"(EN={latest.get(f'{base}_en', '?')} "
                      f"CIRC={latest.get(f'{base}_circ', '?')} "
                      f"PSIZE={latest.get(f'{base}_psize', '?')} "
                      f"MSIZE={latest.get(f'{base}_msize', '?')})")

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
            elif issue["type"] == "counter_stopped":
                print(f"  计数器停止: {issue.get('field', '?')}={issue.get('value', '?')}")
            elif issue["type"] == "no_circ":
                print(f"  CIRC 未设置: {issue.get('register', '?')}")
            elif issue["type"] == "stuck_at":
                print(f"  ADC 卡值: {issue.get('value', '?')} 持续 {issue.get('length', '?')} 点")
            elif issue["type"] == "missing_codes":
                print(f"  ADC 缺码: {issue.get('unique', '?')} 种值 / {issue.get('total', '?')} 采样点")
            elif issue["type"] == "timing_gap":
                print(f"  时序间隙: [{issue.get('index', '?')}] {issue.get('interval', 0)*1000:.1f}ms")
            else:
                print(f"  {issue['type']}: {issue.get('field', '?')}={issue.get('value', '?')}")
    else:
        print(f"\n✅ 未发现明显问题")


# === 工作流集成 ===

def compile_and_flash(project_dir: str, port: str = None, reset: bool = True,
                      reset_method: str = "dtr", verify_reset: bool = False,
                      verify_pattern: str = None,
                      health_check: bool = False,
                      brick_check: bool = False) -> dict:
    """编译并烧录固件。

    Args:
        project_dir: 项目目录
        port: 串口号（烧录用）
        reset: 烧录后是否复位
        reset_method: 复位方法 (dtr/rts/dtr_rts/break/custom/bootloader)
        verify_reset: 复位后是否验证设备响应
        verify_pattern: 验证匹配的字符串模式
        health_check: 编译前是否运行健康检查
        brick_check: 烧录前是否运行死机预防检查

    Returns:
        编译烧录结果
    """
    # 烧录前健康检查
    if health_check:
        print("运行项目健康检查...")
        health_result = run_health_check(project_dir)
        if not health_result.get("success"):
            print(f"⚠️ 健康检查失败: {health_result.get('error', '未知')}")
        else:
            print("✅ 健康检查通过")

    # 查找 workflow.py
    workflow_script = _find_script("workflow.py")
    if not workflow_script:
        return {"success": False, "error": "workflow.py 未找到，请检查 stm32-keil-workflow 安装"}

    # 构建命令
    args = ["--auto", project_dir, "--steps", "compile,flash"]
    if port:
        args.extend(["--port", port])

    print(f"编译烧录: workflow.py {' '.join(args)}")

    result = _run_workflow_script(workflow_script, args, timeout=SUBPROCESS_TIMEOUT_COMPILE)

    # 烧录前死机预防检查
    if result["success"] and brick_check:
        print("运行死机预防检查...")
        brick_result = run_brick_check(project_dir)
        if not brick_result.get("success"):
            print(f"⚠️ 死机预防检查失败: {brick_result.get('error', '未知')}")
            print("建议先检查配置再烧录")

    # 烧录后复位
    if result["success"] and reset and port:
        print(f"烧录成功，复位设备 (方法: {reset_method})...")
        reset_result = reset_device(
            port=port,
            method=reset_method,
            verify=verify_reset,
            verify_pattern=verify_pattern,
        )
        result["reset"] = reset_result

        if not reset_result["success"]:
            print(f"⚠️ 复位失败: {reset_result.get('error')}，尝试带重试复位...")
            reset_result = reset_with_retry(
                port=port,
                method=reset_method,
                max_retries=3,
                verify=verify_reset,
                verify_pattern=verify_pattern,
            )
            result["reset"] = reset_result

    # 编译失败时输出错误总结
    if not result["success"]:
        print("编译失败，获取错误总结...")
        summary = run_error_summary(project_dir)
        if summary.get("success") and summary.get("stdout"):
            print(summary["stdout"][:500])

    return result


RESET_METHODS = [
    "dtr",           # DTR 信号复位（连接 NRST）
    "rts",           # RTS 信号复位（连接 NRST）
    "dtr_rts",       # DTR+RTS 组合复位（交叉连接 BOOT0/NRST）
    "break",         # BREAK 信号复位
    "break_dtr",     # BREAK + DTR 组合复位
    "custom",        # 自定义复位序列（DTR+RTS 同时拉低再拉高）
    "bootloader",    # 进入 bootloader 模式（BOOT0 拉高后复位）
]

# 复位日志
_reset_log: list[dict] = []

# STM32 bootloader 握手字节
_BOOTLOADER_ACK = 0x79
_BOOTLOADER_NACK = 0x1F
_BOOTLOADER_INIT = 0x7F

# 默认启动标志（高置信度）
DEFAULT_BOOT_MARKERS = ["STM32", "Ready", "Boot_OK", "SystemInit", "running"]

# 低置信度标志（需更多数据佐证）
LOW_CONFIDENCE_MARKERS = ["OK", "Init", "start"]


def _check_port_available(port: str) -> dict:
    """检查串口是否可用。

    Args:
        port: 串口号

    Returns:
        检查结果
    """
    import serial.tools.list_ports

    available_ports = [p.device for p in serial.tools.list_ports.comports()]

    if port not in available_ports:
        # 提供诊断信息
        if not available_ports:
            return {
                "available": False,
                "error": f"串口 {port} 不可用，系统无可用串口",
                "hint": "请检查 USB 连接和驱动安装",
            }
        return {
            "available": False,
            "error": f"串口 {port} 不可用",
            "available_ports": available_ports,
            "hint": f"可用串口: {', '.join(available_ports)}",
        }

    return {"available": True}


def _log_reset(port: str, method: str, success: bool, error: str = None,
               duration: float = 0, details: dict = None):
    """记录复位日志。

    Args:
        port: 串口号
        method: 复位方法
        success: 是否成功
        error: 错误信息
        duration: 耗时（秒）
        details: 额外详情
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "port": port,
        "method": method,
        "success": success,
        "error": error,
        "duration": round(duration, 3),
        "details": details or {},
    }
    _reset_log.append(entry)

    # 限制日志大小
    if len(_reset_log) > 100:
        _reset_log.pop(0)


def get_reset_log(last_n: int = 10) -> list[dict]:
    """获取复位日志。

    Args:
        last_n: 返回最近 N 条

    Returns:
        日志列表
    """
    return _reset_log[-last_n:]


def reset_device(port: str, baud: int = 115200, method: str = "dtr",
                  timeout: float = 5.0, verify: bool = False,
                  verify_timeout: float = 3.0,
                  verify_pattern: str = None,
                  signal_delay: float = None,
                  boot_delay: float = None,
                  invert_dtr: bool = False,
                  invert_rts: bool = False) -> dict:
    """复位设备。

    Args:
        port: 串口号
        baud: 波特率
        method: 复位方法 (dtr/rts/dtr_rts/break/break_dtr/custom/bootloader)
        timeout: 串口打开超时时间（秒）
        verify: 复位后是否验证设备响应
        verify_timeout: 验证超时时间（秒）
        verify_pattern: 验证匹配的字符串模式（如 "STM32", "Ready"）
        signal_delay: 信号持续时间（秒），None 使用默认值
        boot_delay: 复位后等待启动时间（秒），None 使用默认值
        invert_dtr: 反转 DTR 极性（适配某些转接板）
        invert_rts: 反转 RTS 极性（适配某些转接板）

    Returns:
        复位结果
    """
    import threading

    start_time = time.time()

    # 迭代3: 延迟可配置
    sig_delay = signal_delay if signal_delay is not None else RESET_SIGNAL_DELAY
    boot_wait = boot_delay if boot_delay is not None else RESET_BOOT_DELAY

    # 迭代6: 复位前串口预检测
    port_check = _check_port_available(port)
    if not port_check["available"]:
        _log_reset(port, method, False, error=port_check["error"])
        return {"success": False, "error": port_check["error"], "hint": port_check.get("hint")}

    ser = None
    try:
        # 使用线程实现打开超时（迭代1: 确保超时后资源清理）
        ser_result = [None]
        ser_error = [None]

        def open_serial():
            try:
                ser_result[0] = serial.Serial(port=port, baudrate=baud, timeout=1)
            except serial.SerialException as e:
                ser_error[0] = str(e)

        thread = threading.Thread(target=open_serial, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            # 迭代1: 线程仍在运行，但串口可能已被打开
            # 等待一小段时间让线程完成
            thread.join(timeout=0.5)
            if thread.is_alive():
                _log_reset(port, method, False, error="串口打开超时")
                return {"success": False, "error": f"串口打开超时 ({timeout}s)"}

        ser = ser_result[0]
        if ser is None:
            # 迭代18: 提供诊断信息
            error_msg = ser_error[0] or f"无法打开串口: {port}"
            hint = ""
            if "PermissionError" in str(type(ser_error[0])) or "Access" in str(ser_error[0]):
                hint = "串口可能被其他程序占用，请关闭串口监视器后重试"
            elif "FileNotFoundError" in str(type(ser_error[0])):
                hint = "串口设备不存在，请检查 USB 连接"
            _log_reset(port, method, False, error=error_msg)
            return {"success": False, "error": error_msg, "hint": hint}

        # 迭代7: 复位前清空接收缓冲区
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # 迭代11: 极性处理
        dtr_low = not invert_dtr
        dtr_high = invert_dtr
        rts_low = not invert_rts
        rts_high = invert_rts

        # 执行复位序列
        if method == "dtr":
            # DTR 信号复位（DTR 连接到 NRST）
            ser.dtr = dtr_low   # NRST 拉低
            time.sleep(sig_delay)
            ser.dtr = dtr_high  # NRST 释放
            time.sleep(boot_wait)

        elif method == "rts":
            # RTS 信号复位（RTS 连接到 NRST）
            ser.rts = rts_low   # NRST 拉低
            time.sleep(sig_delay)
            ser.rts = rts_high  # NRST 释放
            time.sleep(boot_wait)

        elif method == "dtr_rts":
            # DTR+RTS 组合复位（常见于 USB 转串口模块）
            # DTR 控制 NRST，RTS 控制 BOOT0
            ser.dtr = dtr_low   # NRST 拉低
            ser.rts = rts_high  # BOOT0 拉高（确保从 Flash 启动）
            time.sleep(sig_delay)
            ser.dtr = dtr_high  # NRST 释放
            ser.rts = rts_low   # BOOT0 拉低
            time.sleep(boot_wait)

        elif method == "break":
            # BREAK 信号复位
            ser.send_break(duration=sig_delay)
            time.sleep(boot_wait)

        elif method == "break_dtr":
            # 迭代14: BREAK + DTR 组合（某些板子需要）
            ser.send_break(duration=sig_delay)
            time.sleep(sig_delay)
            ser.dtr = dtr_low
            time.sleep(sig_delay)
            ser.dtr = dtr_high
            time.sleep(boot_wait)

        elif method == "custom":
            # 自定义复位序列（DTR+RTS 同时操作）
            ser.dtr = dtr_low
            ser.rts = rts_low
            time.sleep(sig_delay)
            ser.dtr = dtr_high
            ser.rts = rts_high
            time.sleep(boot_wait)

        elif method == "bootloader":
            # 进入 STM32 bootloader 模式
            # 序列：BOOT0 拉高 → NRST 拉低 → NRST 释放 → 等待
            ser.rts = rts_high   # BOOT0 拉高
            time.sleep(sig_delay)
            ser.dtr = dtr_low    # NRST 拉低
            time.sleep(sig_delay)
            ser.dtr = dtr_high   # NRST 释放
            time.sleep(boot_wait * 2)  # bootloader 启动需要更长时间

            # 迭代13: 发送 0x7F 握手字节
            ser.write(bytes([_BOOTLOADER_INIT]))
            time.sleep(0.1)

            # 读取握手响应
            handshake_data = ser.read(2)
            if handshake_data and _BOOTLOADER_ACK in handshake_data:
                print("STM32 bootloader 握手成功 (收到 0x79)")
            elif handshake_data:
                print(f"bootloader 响应: {handshake_data.hex(' ')}")
            else:
                print("bootloader 未响应握手（可能已进入 bootloader，等待命令）")

        else:
            _log_reset(port, method, False, error=f"未知复位方法: {method}")
            return {"success": False, "error": f"未知复位方法: {method}"}

        duration = time.time() - start_time
        print(f"设备已复位 (方法: {method}, 耗时: {duration:.2f}s)")

        # 验证复位是否成功
        if verify:
            verify_result = _verify_reset(
                ser, verify_timeout, verify_pattern,
                is_bootloader=(method == "bootloader"),
            )
            _log_reset(port, method, verify_result["success"],
                       error=verify_result.get("error"),
                       duration=duration, details=verify_result)
            if not verify_result["success"]:
                return {
                    "success": False,
                    "method": method,
                    "error": f"复位验证失败: {verify_result['error']}",
                    "duration": duration,
                }
            return {
                "success": True,
                "method": method,
                "verify": verify_result,
                "duration": duration,
            }

        _log_reset(port, method, True, duration=duration)
        return {"success": True, "method": method, "duration": duration}

    except serial.SerialException as e:
        duration = time.time() - start_time
        _log_reset(port, method, False, error=str(e), duration=duration)
        print(f"复位失败: {e}")
        return {"success": False, "error": f"串口错误: {e}", "duration": duration}
    except Exception as e:
        duration = time.time() - start_time
        _log_reset(port, method, False, error=str(e), duration=duration)
        print(f"复位失败: {e}")
        return {"success": False, "error": str(e), "duration": duration}
    finally:
        if ser and ser.is_open:
            ser.close()


def _verify_reset(ser: serial.Serial, timeout: float = 3.0,
                  pattern: str = None, is_bootloader: bool = False) -> dict:
    """验证复位是否成功。

    Args:
        ser: 已打开的串口对象
        timeout: 验证超时时间（秒）
        pattern: 匹配的字符串模式
        is_bootloader: 是否为 bootloader 模式

    Returns:
        验证结果
    """
    start_time = time.time()
    received_data = bytearray()
    min_data_len = 2  # 迭代10: 最小数据长度，避免噪声误判

    # 迭代8: 预编译匹配模式
    pattern_compiled = None
    if pattern:
        try:
            pattern_compiled = re.compile(re.escape(pattern), re.IGNORECASE)
        except re.error:
            pattern_compiled = None

    # 读取启动信息
    while time.time() - start_time < timeout:
        data = ser.read(64)  # 迭代7: 使用较小的读取块，响应更快
        if data:
            received_data.extend(data)
            text = bytes(received_data).decode("utf-8", errors="replace")

            # 迭代10: 数据量不足时跳过匹配
            if len(received_data) < min_data_len:
                continue

            # 迭代13: bootloader 模式检查 0x79 ACK
            if is_bootloader:
                if _BOOTLOADER_ACK in received_data:
                    return {
                        "success": True,
                        "matched": "bootloader_ack_0x79",
                        "data": received_data.hex(" "),
                    }
                if _BOOTLOADER_NACK in received_data:
                    return {
                        "success": False,
                        "error": "bootloader 返回 NACK (0x1F)",
                        "data": received_data.hex(" "),
                    }

            # 迭代8: 检查是否匹配指定模式（大小写不敏感）
            if pattern_compiled and pattern_compiled.search(text):
                return {
                    "success": True,
                    "matched": pattern,
                    "data": text[:200],
                }

            # 迭代4: 高置信度启动标志
            for marker in DEFAULT_BOOT_MARKERS:
                if marker.lower() in text.lower():
                    return {
                        "success": True,
                        "matched": marker,
                        "confidence": "high",
                        "data": text[:200],
                    }

            # 迭代4: 低置信度标志需要更多数据
            if len(received_data) >= 10:
                for marker in LOW_CONFIDENCE_MARKERS:
                    if marker.lower() in text.lower():
                        return {
                            "success": True,
                            "matched": marker,
                            "confidence": "low",
                            "data": text[:200],
                        }

    # 超时但可能已收到数据
    # 迭代10: 收到足够数据才算成功
    if received_data and len(received_data) >= min_data_len:
        text = bytes(received_data).decode("utf-8", errors="replace")
        return {
            "success": True,
            "matched": "data_received",
            "confidence": "low",
            "data": text[:200],
            "bytes": len(received_data),
        }

    return {
        "success": False,
        "error": "未收到设备响应",
        "bytes": len(received_data),
    }


def reset_with_retry(port: str, baud: int = 115200, method: str = "dtr",
                      max_retries: int = 3, retry_delay: float = 1.0,
                      verify: bool = True, verify_pattern: str = None) -> dict:
    """带重试的设备复位。

    Args:
        port: 串口号
        baud: 波特率
        method: 复位方法
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）
        verify: 是否验证复位
        verify_pattern: 验证匹配模式

    Returns:
        复位结果
    """
    current_method = method  # 迭代5: 使用独立变量跟踪当前方法

    for attempt in range(1, max_retries + 1):
        print(f"复位尝试 {attempt}/{max_retries} (方法: {current_method})...")

        result = reset_device(
            port=port,
            baud=baud,
            method=current_method,
            verify=verify,
            verify_pattern=verify_pattern,
        )

        if result["success"]:
            if attempt > 1:
                print(f"复位成功 (第 {attempt} 次尝试)")
            return result

        print(f"复位失败: {result.get('error')}")
        if attempt < max_retries:
            # 迭代5: 正确切换回退方法
            fallback_methods = ["dtr", "rts", "dtr_rts", "break", "custom"]
            if current_method in fallback_methods:
                fallback_methods.remove(current_method)
            if fallback_methods:
                next_method = fallback_methods[0]
                print(f"切换复位方法: {current_method} → {next_method}")
                current_method = next_method

            time.sleep(retry_delay)

    return {"success": False, "error": f"复位失败 (已尝试 {max_retries} 次)"}


def enter_bootloader(port: str, baud: int = 115200) -> dict:
    """进入 STM32 bootloader 模式。

    Args:
        port: 串口号
        baud: 波特率

    Returns:
        操作结果
    """
    print("进入 STM32 bootloader 模式...")
    return reset_device(port, baud, method="bootloader", verify=True)


def exit_bootloader(port: str, baud: int = 115200) -> dict:
    """退出 STM32 bootloader 模式（正常复位）。

    Args:
        port: 串口号
        baud: 波特率

    Returns:
        操作结果
    """
    print("退出 bootloader 模式（正常复位）...")
    return reset_device(port, baud, method="dtr_rts", verify=True)


def stm32_system_reset(port: str, baud: int = 115200) -> dict:
    """通过 bootloader 协议发送系统复位命令 (0x07)。

    Args:
        port: 串口号
        baud: 波特率

    Returns:
        操作结果
    """
    # 迭代19: 先进入 bootloader
    result = enter_bootloader(port, baud)
    if not result["success"]:
        return result

    # 发送 Get 命令 (0x00) 验证 bootloader
    ser = None
    try:
        ser = serial.Serial(port=port, baudrate=baud, timeout=2)
        ser.reset_input_buffer()

        # 发送 Get 命令
        ser.write(bytes([0x00, 0xFF]))
        time.sleep(0.2)
        resp = ser.read(10)

        if resp and resp[0] == _BOOTLOADER_ACK:
            print("bootloader 通信正常，发送系统复位...")
            # 发送 Go 命令 (0x21) 跳转到 0x08000000（Flash 起始地址）
            addr = bytes([0x08, 0x00, 0x00, 0x00])
            addr_complement = bytes([0x07, 0xFF, 0xFF, 0xFF])
            ser.write(bytes([0x21]) + addr + addr_complement)
            time.sleep(0.2)
            go_resp = ser.read(2)
            if go_resp and _BOOTLOADER_ACK in go_resp:
                print("系统复位成功")
                return {"success": True, "method": "bootloader_go"}
            else:
                # 备选：直接拉低 NRST 复位
                print("Go 命令未响应，使用 DTR 复位...")
                ser.close()
                return reset_device(port, baud, method="dtr", verify=True)
        else:
            print("bootloader 未响应，使用普通复位...")
            ser.close()
            return reset_device(port, baud, method="dtr", verify=True)

    except Exception as e:
        return {"success": False, "error": f"系统复位失败: {e}"}
    finally:
        if ser and ser.is_open:
            ser.close()


def auto_detect_reset_method(port: str, baud: int = 115200) -> dict:
    """自动探测最佳复位方法。

    Args:
        port: 串口号
        baud: 波特率

    Returns:
        探测结果
    """
    # 迭代17: 依次尝试各种方法，找到能成功的
    methods_to_try = ["dtr", "rts", "dtr_rts", "break", "custom"]

    print(f"自动探测复位方法: {port}")
    print("=" * 40)

    results = []
    for method in methods_to_try:
        print(f"\n尝试 {method}...")
        result = reset_device(
            port=port,
            baud=baud,
            method=method,
            verify=True,
            verify_timeout=2.0,
        )
        results.append({
            "method": method,
            "success": result["success"],
            "duration": result.get("duration", 0),
            "verify": result.get("verify", {}),
        })

        if result["success"]:
            print(f"✅ {method} 成功!")
            return {
                "success": True,
                "recommended_method": method,
                "all_results": results,
            }
        else:
            print(f"❌ {method} 失败: {result.get('error')}")

    # 所有方法都失败
    print("\n所有复位方法均失败")
    return {
        "success": False,
        "recommended_method": None,
        "all_results": results,
        "hint": "请检查硬件连接：DTR/RTS 是否连接到 NRST/BOOT0",
    }


def run_workflow_step(project_dir: str, steps: list[str], port: str = None) -> dict:
    """运行工作流步骤。

    Args:
        project_dir: 项目目录
        steps: 步骤列表 (compile/analyze/optimize/flash/health/brick_check/report)
        port: 串口号

    Returns:
        工作流结果
    """
    workflow_script = _find_script("workflow.py")
    if not workflow_script:
        return {"success": False, "error": "workflow.py 未找到，请检查 stm32-keil-workflow 安装"}

    args = ["--auto", project_dir, "--steps", ",".join(steps)]
    if port:
        args.extend(["--port", port])

    print(f"运行工作流: workflow.py {' '.join(args)}")

    return _run_workflow_script(workflow_script, args, timeout=SUBPROCESS_TIMEOUT_WORKFLOW)


def auto_loop(port: str, baud: int, project_dir: str, duration: float,
              min_val: float = None, max_val: float = None,
              jump_threshold: float = None, max_iterations: int = 5,
              reset_method: str = "dtr", verify_reset: bool = False,
              retry_on_failure: bool = True,
              timeout: int = 300, retry_delay: float = 2.0,
              send_cmds: list[str] = None, send_hex: str = None) -> dict:
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
    max_consecutive_failures = MAX_CONSECUTIVE_FAILURES

    # 读取已知问题文档
    known_issues = read_solutions_log(project_dir)
    if known_issues:
        sources = set(k.get("source_file", "?") for k in known_issues)
        print(f"已读取文档: {', '.join(sources)} — {len(known_issues)} 个已知问题")
    else:
        print("未找到问题文档（docs/ 下无 solutions-log.md 等）")

    for iteration in range(1, max_iterations + 1):
        # 检查超时
        if time.time() - start_time > timeout:
            print(f"\n超时 ({timeout}s)，停止调试")
            break

        print(f"\n{'='*60}")
        print(f"第 {iteration} 轮调试")
        print(f"{'='*60}")

        # 更新进度
        progress.update(iteration, f"第 {iteration} 轮调试")

        try:
            # 步骤 1：数据采集
            print(f"\n[1/4] 数据采集 ({duration}s)...")
            data = collect_data(port, baud, duration, send_cmds=send_cmds, send_hex=send_hex)
            if not data.get("success"):
                print(f"数据采集失败: {data.get('error')}")
                consecutive_failures += 1
                results.append({
                    "iteration": iteration,
                    "success": False,
                    "error": data.get("error"),
                    "consecutive_failures": consecutive_failures,
                })
                if consecutive_failures >= max_consecutive_failures:
                    print(f"连续失败 {consecutive_failures} 次，停止调试")
                    break
                if retry_on_failure:
                    print(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                continue

            consecutive_failures = 0

            # 步骤 2：数据分析
            print(f"\n[2/4] 数据分析...")
            analysis = analyze_data(data, min_val, max_val, jump_threshold)

            # 对比已知问题文档
            doc_matches = check_against_docs(project_dir, analysis)
            if doc_matches:
                print(f"\n📋 匹配到 {len(doc_matches)} 个已知问题:")
                for m in doc_matches:
                    src = m['known'].get('source_file', '?')
                    print(f"  → [{src}] #{m['known']['number']} {m['known']['title']}")
                analysis["doc_matches"] = doc_matches

            # 写调试日志
            write_debug_log(project_dir, iteration, analysis)

            # 步骤 3：判断是否需要修复
            if not analysis.get("issues"):
                print(f"\n✅ 第 {iteration} 轮：未发现问题，调试完成")
                results.append({
                    "iteration": iteration,
                    "success": True,
                    "issues": 0,
                    "verified": True,
                    "data_summary": {
                        "value_count": data.get("value_count", 0),
                        "duration": duration,
                    },
                })
                break

            print(f"\n[3/4] 发现 {analysis['issue_count']} 个问题，输出报告...")
            report = generate_report(data, analysis)
            print(report)

            # 步骤 3：编译烧录
            print(f"\n[3/4] 编译烧录...")
            flash_result = compile_and_flash(project_dir, port, reset=True,
                                              reset_method=reset_method,
                                              verify_reset=verify_reset)
            if not flash_result.get("success"):
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
                if consecutive_failures >= max_consecutive_failures:
                    print(f"连续失败 {consecutive_failures} 次，停止调试")
                    break
                continue

            print("编译烧录成功，等待设备启动...")

            # 步骤 4：验证修复 — 重新采集数据对比
            print(f"\n[4/4] 验证修复...")
            time.sleep(2.0)  # 等待设备启动
            after_data = collect_data(port, baud, duration, send_cmds=send_cmds, send_hex=send_hex)
            if not after_data.get("success"):
                print(f"验证采集失败: {after_data.get('error')}")
                results.append({
                    "iteration": iteration,
                    "success": False,
                    "issues": analysis["issue_count"],
                    "flash": True,
                    "verified": False,
                    "error": "验证采集失败",
                })
                continue

            after_analysis = analyze_data(after_data, min_val, max_val, jump_threshold)
            verify_result = verify_fix(data, after_data, analysis, after_analysis)
            print_verification_result(verify_result)

            # 写验证日志
            write_debug_log(project_dir, iteration, after_analysis, verify_result)

            if verify_result["status"] == "improved":
                print(f"\n✅ 第 {iteration} 轮：修复成功！问题数 {analysis['issue_count']} → {after_analysis['issue_count']}")
                results.append({
                    "iteration": iteration,
                    "success": True,
                    "issues": after_analysis["issue_count"],
                    "flash": True,
                    "verified": True,
                    "verify": verify_result,
                    "fixes": fix_result.get("fixes", []),
                    "inject": inject_result,
                })
                break
            elif verify_result["status"] == "unchanged":
                print(f"\n⚠️ 第 {iteration} 轮：问题未改善，继续下一轮")
                results.append({
                    "iteration": iteration,
                    "success": False,
                    "issues": after_analysis["issue_count"],
                    "flash": True,
                    "verified": False,
                    "verify": verify_result,
                })
            else:
                print(f"\n❌ 第 {iteration} 轮：问题恶化！停止调试")
                results.append({
                    "iteration": iteration,
                    "success": False,
                    "issues": after_analysis["issue_count"],
                    "flash": True,
                    "verified": False,
                    "verify": verify_result,
                })
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
  # 数据采集
  %(prog)s --port COM3 --mode collect --duration 10

  # 数据分析
  %(prog)s --port COM3 --mode analyze --duration 10 --min-val 0 --max-val 100
  %(prog)s --mode analyze --input data.json --min-val 0 --max-val 100

  # 闭环调试
  %(prog)s --port COM3 --mode loop --duration 10 --max-val 100
  %(prog)s --port COM3 --mode loop --duration 10 --max-iterations 20 --timeout 600

  # 设备复位
  %(prog)s --port COM3 --mode reset
  %(prog)s --port COM3 --mode reset --reset-method dtr_rts --verify-reset
  %(prog)s --port COM3 --mode reset --bootloader

  # 烧录后自动复位（在 loop 模式中）
  %(prog)s --port COM3 --mode loop --duration 10 --reset-method dtr_rts --verify-reset
        """,
    )

    parser.add_argument("--port", help="串口号 (如 COM3)")
    parser.add_argument("--baud", type=int, default=115200, help="波特率 (默认 115200)")
    parser.add_argument("--mode", choices=["collect", "analyze", "loop", "report", "reset"],
                        default="collect", help="工作模式")
    parser.add_argument("--auto", metavar="DIR",
                        help="自动检测项目配置 (如 --auto .)")
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
    parser.add_argument("--send-cmd", action="append", default=[],
                        help="采集前发送的文本命令（可多次使用，如 --send-cmd HB --send-cmd REG）")
    parser.add_argument("--send-hex", metavar="HEX",
                        help="采集前发送的十六进制数据（如 --send-hex AA550100FF）")
    parser.add_argument("--check-build", action="store_true",
                        help="采集后检查 BUILD 时间戳确认是新固件")
    parser.add_argument("--config", metavar="FILE",
                        help="JSON 配置文件（自定义心跳前缀、寄存器位、问题规则等）")
    parser.add_argument("--build-marker", help="编译时间戳前缀（默认 BUILD:）")
    parser.add_argument("--heartbeat-prefix", help="心跳行前缀，逗号分隔（默认 HB,STATUS,DBG,DIAG）")
    parser.add_argument("--reset-method", choices=RESET_METHODS, default="dtr",
                        help="复位方法 (默认 dtr)")
    parser.add_argument("--verify-reset", action="store_true",
                        help="复位后验证设备响应")
    parser.add_argument("--verify-pattern", help="复位验证匹配的字符串 (如 'STM32')")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="复位最大重试次数 (默认 3)")
    parser.add_argument("--bootloader", action="store_true",
                        help="进入 STM32 bootloader 模式")
    parser.add_argument("--signal-delay", type=float, default=None,
                        help="复位信号持续时间/秒 (默认 0.1)")
    parser.add_argument("--boot-delay", type=float, default=None,
                        help="复位后等待启动时间/秒 (默认 0.5)")
    parser.add_argument("--invert-dtr", action="store_true",
                        help="反转 DTR 极性 (适配某些转接板)")
    parser.add_argument("--invert-rts", action="store_true",
                        help="反转 RTS 极性 (适配某些转接板)")
    parser.add_argument("--auto-detect", action="store_true",
                        help="自动探测最佳复位方法")
    parser.add_argument("--reset-log", action="store_true",
                        help="显示复位日志")
    parser.add_argument("--max-iterations", type=int, default=5,
                        help="自动闭环最大迭代次数 (默认 5)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="闭环调试总超时时间/秒 (默认 300)")
    parser.add_argument("--health-check", action="store_true",
                        help="编译前运行项目健康检查")
    parser.add_argument("--brick-check", action="store_true",
                        help="烧录前运行死机预防检查")

    args = parser.parse_args()

    # 加载配置
    load_config(
        config_path=args.config,
        cli_overrides={
            "build_marker": args.build_marker,
            "heartbeat_prefix": args.heartbeat_prefix,
        },
    )

    if args.list:
        ports = serial.tools.list_ports.comports()
        if not ports:
            print("未找到可用串口")
            return 1
        print("可用串口:")
        for p in ports:
            print(f"  {p.device}: {p.description}")
        return 0

    # --auto: 自动检测项目配置
    project_info = None
    if args.auto:
        project_info = detect_project(args.auto)
        print(f"项目检测: {project_info['project_dir']}")
        if project_info["uvprojx"]:
            print(f"  工程文件: {project_info['uvprojx']}")
        if project_info["ioc"]:
            print(f"  CubeMX: {project_info['ioc']}")
        if project_info["axf"]:
            print(f"  编译产物: {project_info['axf']}")
        if project_info["workflow_result"]:
            print(f"  工作流结果: workflow_result.json")

    if args.mode == "collect":
        if not args.port:
            parser.error("collect 模式需要 --port")
        result = collect_data(args.port, args.baud, args.duration, args.protocol,
                              send_cmds=args.send_cmd or None,
                              send_hex=args.send_hex)
        if args.output:
            Path(args.output).write_text(
                json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"数据已保存: {args.output}")

    elif args.mode == "analyze":
        if args.input:
            data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        elif args.port:
            data = collect_data(args.port, args.baud, args.duration, args.protocol,
                                send_cmds=args.send_cmd or None,
                                send_hex=args.send_hex)
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

        # 多轮迭代模式：调用 auto_loop()
        if args.max_iterations > 1:
            print(f"自动闭环调试: 最多 {args.max_iterations} 轮")
            result = auto_loop(
                port=args.port,
                baud=args.baud,
                project_dir=".",
                duration=args.duration,
                min_val=args.min_val,
                max_val=args.max_val,
                jump_threshold=args.jump_threshold,
                max_iterations=args.max_iterations,
                reset_method=args.reset_method,
                verify_reset=args.verify_reset,
                timeout=args.timeout,
                send_cmds=args.send_cmd or None,
                send_hex=args.send_hex,
            )

            if args.output:
                Path(args.output).write_text(
                    json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"结果已保存: {args.output}")

            if not result.get("success"):
                return 1

        # 单轮模式：原有流程
        else:
            # 步骤 1：数据采集
            print("=" * 60)
            print("步骤 1: 数据采集")
            print("=" * 60)
            data = collect_data(args.port, args.baud, args.duration, args.protocol,
                                send_cmds=args.send_cmd or None)

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

                # 生成修复代码
                fix_result = generate_fix_code(analysis)
                if fix_result.get("success"):
                    print(f"\n生成了 {fix_result['fix_count']} 个修复代码:")
                    for fix in fix_result["fixes"]:
                        print(f"  - {fix['description']}")

                    # 代码注入（如果启用）
                    if args.auto_inject and args.source_file:
                        print(f"\n注入修复代码到 {args.source_file}...")
                        for fix in fix_result["fixes"]:
                            inject_result = inject_code_to_source(args.source_file, fix["code"])
                            if inject_result.get("success"):
                                print(f"  ✅ 注入成功: {fix['type']}")
                            else:
                                print(f"  ❌ 注入失败: {inject_result.get('error')}")
                    elif args.auto_inject and not args.source_file:
                        print("\n⚠️ --auto-inject 需要配合 --source-file 使用")
                    else:
                        print("\n提示: 使用 --auto-inject --source-file main.c 可自动注入代码")

                # 打印修复建议
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

    elif args.mode == "reset":
        if not args.port:
            parser.error("reset 模式需要 --port")

        # 显示复位日志
        if args.reset_log:
            logs = get_reset_log(20)
            if not logs:
                print("无复位日志")
            else:
                print("复位日志 (最近 20 条):")
                print("-" * 70)
                for entry in logs:
                    status = "✅" if entry["success"] else "❌"
                    err = f" ({entry['error']})" if entry.get("error") else ""
                    print(f"  {status} [{entry['timestamp'][:19]}] {entry['port']} "
                          f"method={entry['method']} duration={entry['duration']:.3f}s{err}")
            return 0

        # 自动探测复位方法
        if args.auto_detect:
            print("=" * 60)
            print("自动探测复位方法")
            print("=" * 60)
            result = auto_detect_reset_method(args.port, args.baud)
            if result["success"]:
                print(f"\n✅ 推荐方法: {result['recommended_method']}")
            else:
                print(f"\n❌ 所有方法均失败")
                if result.get("hint"):
                    print(f"   提示: {result['hint']}")
                return 1
            return 0

        # bootloader 模式
        if args.bootloader:
            print("=" * 60)
            print("进入 STM32 bootloader 模式")
            print("=" * 60)
            result = enter_bootloader(args.port, args.baud)
            if result["success"]:
                print("✅ 已进入 bootloader 模式")
                if result.get("verify"):
                    print(f"   验证: {result['verify'].get('matched', 'N/A')}")
            else:
                print(f"❌ 进入 bootloader 失败: {result.get('error')}")
                return 1
        else:
            # 普通复位
            print("=" * 60)
            print(f"设备复位 (方法: {args.reset_method})")
            print("=" * 60)

            reset_kwargs = {
                "port": args.port,
                "baud": args.baud,
                "method": args.reset_method,
                "verify": args.verify_reset,
                "verify_pattern": args.verify_pattern,
                "signal_delay": args.signal_delay,
                "boot_delay": args.boot_delay,
                "invert_dtr": args.invert_dtr,
                "invert_rts": args.invert_rts,
            }

            if args.max_retries > 1:
                result = reset_with_retry(
                    port=args.port,
                    baud=args.baud,
                    method=args.reset_method,
                    max_retries=args.max_retries,
                    verify=args.verify_reset,
                    verify_pattern=args.verify_pattern,
                )
            else:
                result = reset_device(**reset_kwargs)

            if result["success"]:
                print(f"✅ 设备复位成功 (方法: {result.get('method', 'N/A')})")
                if result.get("duration"):
                    print(f"   耗时: {result['duration']:.2f}s")
                if result.get("verify"):
                    v = result["verify"]
                    conf = f" (置信度: {v.get('confidence', 'N/A')})" if v.get("confidence") else ""
                    print(f"   验证: 匹配 '{v.get('matched', 'N/A')}'{conf}")
                    if v.get("data"):
                        print(f"   响应: {v['data'][:100]}")
            else:
                print(f"❌ 复位失败: {result.get('error')}")
                if result.get("hint"):
                    print(f"   提示: {result['hint']}")
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
