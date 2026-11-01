"""性能基准模块（v1.11.0）——给"能扛多少"以官方数字，且用户一条命令可复现。

场景（scenarios.py）：引擎 tick 生成吞吐、Modbus 线级读延迟（真实 socket）、
并发连接/读、API 读。结果含延迟分位（P50/P95/P99）、吞吐、tick 时长、
进程内存（psutil RSS）。

结果持久化在 ``data/benchmarks/<id>.json``（含环境指纹：python/平台/版本/
CPU 核数），``compare_results`` 对同场景两次结果判回退（默认 >10% 标
WARNING），供 CI 性能门禁使用（``protoforge benchmark run --compare-to``）。
"""

from protoforge.benchmark.runner import BenchmarkRunner, benchmark_results_dir
from protoforge.benchmark.scenarios import (
    BUILTIN_SCENARIOS,
    SCENARIO_REGISTRY,
    run_scenario,
)

__all__ = [
    "BenchmarkRunner",
    "benchmark_results_dir",
    "BUILTIN_SCENARIOS",
    "SCENARIO_REGISTRY",
    "run_scenario",
]
