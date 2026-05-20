# -*- coding: utf-8 -*-

import requests
import numpy as np
from datetime import datetime, timedelta

VM_URL = "http://localhost:8428"
DEVICE_ID = "fanuc-cnc"
METRIC = f'feed_rate{{device_id="{DEVICE_ID}"}}'

def fetch_history(minutes=30):
    """从VM拉取历史数据"""
    end = datetime.now()
    start = end - timedelta(minutes=minutes)
    resp = requests.get(f"{VM_URL}/api/v1/query_range", params={
        "query": METRIC,
        "start": start.timestamp(),
        "end": end.timestamp(),
        "step": "1s",
    })
    result = resp.json()["data"]["result"]
    if not result:
        return [], []
    values = result[0]["values"]
    ts = [float(v[0]) for v in values]
    ys = [float(v[1]) for v in values]
    return ts, ys

def predict_next(ts, ys, horizon=60):
    """
    用FFT检测主频，拟合正弦波，外推未来horizon秒
    适合周期性信号
    """
    if len(ys) < 60:
        return [], []

    ys = np.array(ys)
    n = len(ys)
    dt = 1.0  # 1秒采样

    # FFT找主频
    fft = np.fft.rfft(ys - ys.mean())
    freqs = np.fft.rfftfreq(n, d=dt)
    dominant_idx = np.argmax(np.abs(fft[1:])) + 1
    dominant_freq = freqs[dominant_idx]
    period = 1.0 / dominant_freq if dominant_freq > 0 else 60

    # 拟合：y = A*sin(2π/T * t + φ) + offset
    from scipy.optimize import curve_fit
    t_rel = np.arange(n, dtype=float)
    offset = ys.mean()
    amplitude = (ys.max() - ys.min()) / 2

    def sine_model(t, A, T, phi, C):
        return A * np.sin(2 * np.pi / T * t + phi) + C

    try:
        popt, _ = curve_fit(
            sine_model, t_rel, ys,
            p0=[amplitude, period, 0, offset],
            maxfev=5000
        )
        # 外推
        t_future = np.arange(n, n + horizon, dtype=float)
        y_pred = sine_model(t_future, *popt)
        ts_future = [ts[-1] + i + 1 for i in range(horizon)]
        return ts_future, y_pred.tolist()
    except Exception:
        # 拟合失败降级为线性
        slope = (ys[-1] - ys[-10]) / 10
        ts_future = [ts[-1] + i + 1 for i in range(horizon)]
        y_pred = [ys[-1] + slope * (i + 1) for i in range(horizon)]
        return ts_future, y_pred

def write_predictions(ts_future, y_pred, metric_name="protoforge_feed_rate_predicted"):
    """写回VictoriaMetrics"""
    lines = []
    for t, y in zip(ts_future, y_pred):
        ts_ms = int(t * 1000)
        lines.append(f'{metric_name}{{device_id="{DEVICE_ID}"}} {y:.2f} {ts_ms}')
    payload = "\n".join(lines)
    requests.post(f"{VM_URL}/api/v1/import/prometheus", data=payload)

def run_once():
    ts, ys = fetch_history(minutes=30)
    if len(ys) < 60:
        print("数据不足")
        return
    ts_future, y_pred = predict_next(ts, ys, horizon=120)
    write_predictions(ts_future, y_pred)
    print(f"写入 {len(y_pred)} 个预测点，预测到 +{len(y_pred)}s")

if __name__ == "__main__":
    import time
    while True:
        run_once()
        time.sleep(30)  # 每30秒重新预测一次
