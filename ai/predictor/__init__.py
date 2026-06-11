# -*- coding: utf-8 -*-
"""
predictor
~~~~~~~~~
ProtoForge 预测服务 package。

对外暴露：
- ``PredictorService``：预测服务主类，支持 run() 一键启动
- ``run()``：便捷入口，使用默认配置启动服务

快速启动::

    from ai.predictor import run
    run()

或自定义配置::

    from ai.predictor import PredictorService
    svc = PredictorService(vm_url="http://vm:8428", poll_interval=60)
    svc.run()
"""

from .service import PredictorService

__all__ = ["PredictorService", "run"]


def run() -> None:
    """使用默认配置启动预测服务（一行启动）。"""
    PredictorService().run()
