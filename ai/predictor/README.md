```bash
ai/predictor/
  ├── __init__.py      # 公开 API：PredictorService, run()
  ├── config.py        # 所有常量，支持环境变量覆盖
  ├── models.py        # BaselineState, MetricProfile 数据类
  ├── discovery.py     # VM 设备/指标发现
  ├── signal.py        # 纯信号处理：平滑、FFT+自相关周期估计、谷底检测
  ├── template.py      # 模板构建、预测、重采样、EMA 融合
  ├── phase_lock.py    # Phase-lock 相位对齐
  ├── anomaly.py       # 异常检测：边界计算、越界统计、三条件判断
  ├── state.py         # 状态机：HEALTHY/ANOMALY/RECOVERING 生命周期
  ├── profiling.py     # 自适应配置推断：infer_metric_profile, refresh_targets
  ├── storage.py       # VM 读写、标签工具、状态持久化
  └── service.py       # PredictorService 主类（run_once / run）

  启动方式：
  from ai.predictor import run
  run()
  # 或
  from ai.predictor import PredictorService
  PredictorService(vm_url="http://vm:8428").run()

  主要改进：
  - 全局变量（BASELINE_STATES、LAST_REAL_TS_WRITTEN、_TARGETS_CACHE）全部移入 PredictorService 实例属性
  - IO 与计算完全分离：signal.py、template.py、anomaly.py 均为纯函数，无网络请求
  - 每个模块顶部有职责说明，每个公开函数有完整 docstring
```
