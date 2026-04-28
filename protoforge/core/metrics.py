import time
from typing import Any


class MetricsCollector:
    def __init__(self):
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._start_time = time.time()

    def inc_counter(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        key = self._make_key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + value

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._make_key(name, labels)
        self._gauges[key] = value

    def observe_histogram(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._make_key(name, labels)
        if key not in self._histograms:
            self._histograms[key] = []
        self._histograms[key].append(value)
        if len(self._histograms[key]) > 1000:
            self._histograms[key] = self._histograms[key][-500:]

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = self._make_key(name, labels)
        return self._counters.get(key, 0)

    def get_gauge(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = self._make_key(name, labels)
        return self._gauges.get(key, 0)

    def collect_from_engine(self, engine: Any) -> None:
        self.set_gauge("protoforge_devices_total", len(engine._devices))
        online = sum(1 for d in engine._devices.values()
                     if d.status.value == "online")
        self.set_gauge("protoforge_devices_online", online)
        self.set_gauge("protoforge_scenarios_total", len(engine._scenarios))
        running = sum(1 for s in engine._scenario_status.values()
                      if s.value == "running")
        self.set_gauge("protoforge_scenarios_running", running)
        protocols_running = sum(1 for p in engine._protocol_servers.values()
                                if p.status.value == "running")
        self.set_gauge("protoforge_protocols_running", protocols_running)

    def collect_from_test_runner(self, runner: Any) -> None:
        self.set_gauge("protoforge_test_cases_total", len(runner._test_cases))
        self.set_gauge("protoforge_test_suites_total", len(runner._test_suites))
        self.set_gauge("protoforge_test_reports_total", len(runner._reports))

    def generate_prometheus_output(self) -> str:
        lines = []
        lines.append(f"# HELP protoforge_uptime_seconds Server uptime in seconds")
        lines.append(f"# TYPE protoforge_uptime_seconds gauge")
        lines.append(f"protoforge_uptime_seconds {time.time() - self._start_time:.2f}")

        seen_names = set()
        for key, value in sorted(self._gauges.items()):
            name, labels = self._parse_key(key)
            if name not in seen_names:
                lines.append(f"# HELP {name} {name}")
                lines.append(f"# TYPE {name} gauge")
                seen_names.add(name)
            if labels:
                label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
                lines.append(f"{name}{{{label_str}}} {value:.2f}")
            else:
                lines.append(f"{name} {value:.2f}")

        seen_names = set()
        for key, value in sorted(self._counters.items()):
            name, labels = self._parse_key(key)
            if name not in seen_names:
                lines.append(f"# HELP {name}_total {name} total")
                lines.append(f"# TYPE {name}_total counter")
                seen_names.add(name)
            if labels:
                label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
                lines.append(f"{name}_total{{{label_str}}} {value:.2f}")
            else:
                lines.append(f"{name}_total {value:.2f}")

        seen_names = set()
        for key, values in sorted(self._histograms.items()):
            name, labels = self._parse_key(key)
            if not values:
                continue
            if name not in seen_names:
                lines.append(f"# HELP {name} {name}")
                lines.append(f"# TYPE {name} summary")
                seen_names.add(name)
            sorted_vals = sorted(values)
            count = len(sorted_vals)
            total = sum(sorted_vals)
            quantiles = [0.5, 0.9, 0.95, 0.99]
            label_prefix = ""
            if labels:
                label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
                label_prefix = f"{{{label_str},"
            else:
                label_prefix = "{"
            for q in quantiles:
                idx = min(int(count * q), count - 1)
                lines.append(f"{name}{label_prefix}quantile=\"{q}\"}} {sorted_vals[idx]:.6f}")
            lines.append(f"{name}_sum {total:.6f}")
            lines.append(f"{name}_count {count}")

        return "\n".join(lines) + "\n"

    @staticmethod
    def _make_key(name: str, labels: dict[str, str] | None = None) -> str:
        if not labels:
            return name
        label_parts = sorted(f"{k}={v}" for k, v in labels.items())
        return f"{name}|{'|'.join(label_parts)}"

    @staticmethod
    def _parse_key(key: str) -> tuple[str, dict[str, str] | None]:
        if "|" not in key:
            return key, None
        parts = key.split("|", 1)
        name = parts[0]
        labels = {}
        for part in parts[1].split("|"):
            if "=" in part:
                k, v = part.split("=", 1)
                labels[k] = v
        return name, labels


metrics = MetricsCollector()
