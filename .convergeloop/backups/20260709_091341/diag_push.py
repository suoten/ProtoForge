#!/usr/bin/env python3
"""ProtoForge-EdgeLite 联调诊断脚本
逐步测试每个环节，精确定位失败点。
用法: python diag_push.py [--url URL] [--user USER] [--pass PASS]
"""
import asyncio
import json
import sys
import os
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="https://edgelite.jjtt.net")
parser.add_argument("--user", default="admin")
parser.add_argument("--pass", dest="password", default="admin123")
args = parser.parse_args()

EDGELITE_URL = args.url
EDGELITE_USER = args.user
EDGELITE_PASS = args.password

import httpx

STEP = 0
def next_step(title):
    global STEP
    STEP += 1
    print(f"\n{'='*60}")
    print(f"步骤 {STEP}: {title}")
    print(f"{'='*60}")

def ok(msg):
    print(f"  [OK] {msg}")

def fail(msg):
    print(f"  [FAIL] {msg}")

def info(msg):
    print(f"  [INFO] {msg}")


async def main():
    results = {}
    client = httpx.AsyncClient(
        base_url=EDGELITE_URL,
        timeout=30.0,
        verify=False,
        follow_redirects=True,
    )

    try:
        # ─── 步骤1: 登录 ───
        next_step("登录 EdgeLite")
        try:
            resp = await client.post("/api/v1/auth/login", json={
                "username": EDGELITE_USER,
                "password": EDGELITE_PASS,
            })
            info(f"HTTP {resp.status_code}")
            if resp.status_code != 200:
                fail(f"登录失败: {resp.text[:300]}")
                return
            login_data = resp.json().get("data", resp.json())
            token = login_data.get("access_token", "")
            csrf_token = login_data.get("csrf_token", "")
            must_change = login_data.get("must_change_password", False)
            ok(f"登录成功, token={token[:30]}..., csrf={csrf_token[:30] if csrf_token else 'N/A'}...")
            info(f"must_change_password={must_change}")
            results["login"] = True
        except Exception as e:
            fail(f"登录异常: {e}")
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if csrf_token:
            headers["X-CSRF-Token"] = csrf_token

        # ─── 步骤2: 检查 must_change_password ───
        next_step("检查 must_change_password")
        try:
            resp = await client.get("/api/v1/auth/me", headers=headers)
            info(f"HTTP {resp.status_code}")
            if resp.status_code == 200:
                me_data = resp.json().get("data", resp.json())
                must_change = me_data.get("must_change_password", False)
                info(f"must_change_password={must_change}")
                if must_change:
                    fail("用户需要修改密码！所有非白名单端点都会返回 403")
                    new_pass = EDGELITE_PASS + "!1A"
                    resp2 = await client.post("/api/v1/auth/change-password", headers=headers, json={
                        "old_password": EDGELITE_PASS,
                        "new_password": new_pass,
                    })
                    info(f"change-password HTTP {resp2.status_code}: {resp2.text[:200]}")
                    if resp2.status_code == 200:
                        ok("密码修改成功，重新登录")
                        resp3 = await client.post("/api/v1/auth/login", json={
                            "username": EDGELITE_USER,
                            "password": new_pass,
                        })
                        if resp3.status_code == 200:
                            login_data = resp3.json().get("data", resp3.json())
                            token = login_data.get("access_token", "")
                            csrf_token = login_data.get("csrf_token", "")
                            headers["Authorization"] = f"Bearer {token}"
                            headers["X-CSRF-Token"] = csrf_token
                            ok("重新登录成功")
                        else:
                            fail(f"重新登录失败: {resp3.text[:200]}")
                            return
                    else:
                        fail("密码修改失败")
                        return
                else:
                    ok("无需修改密码")
            elif resp.status_code == 403:
                fail("GET /auth/me 返回 403 — 可能是 must_change_password=True")
            else:
                fail(f"GET /auth/me 返回 {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            fail(f"检查异常: {e}")

        # ─── 步骤3: 获取协议列表 ───
        next_step("获取 EdgeLite 支持的协议列表")
        try:
            resp = await client.get("/api/v1/drivers/protocols", headers=headers)
            info(f"HTTP {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json().get("data", resp.json())
                protocols = data.get("protocols", [])
                if not protocols:
                    protocols = resp.json().get("protocols", [])
                info(f"协议列表 ({len(protocols)}): {sorted(protocols)}")
                for p in ["s7", "siemens_s7", "mqtt", "mqtt_client", "mc", "mitsubishi_mc", "http", "http_webhook", "fins", "omron_fins", "ab", "allen_bradley", "modbus_tcp"]:
                    status = "✓" if p in protocols else "✗"
                    info(f"  {status} {p}")
                results["protocols"] = protocols
            else:
                fail(f"获取协议列表失败: {resp.text[:200]}")
        except Exception as e:
            fail(f"异常: {e}")

        # ─── 步骤4: 检查集成端点是否就绪 ───
        next_step("检查集成端点 (IntegrationEndpoint)")
        try:
            resp = await client.get("/api/v1/integration/protocols", headers=headers)
            info(f"GET /api/v1/integration/protocols HTTP {resp.status_code}")
            if resp.status_code == 503:
                fail("集成端点未就绪 (503) — push-device 端点不可用！")
                fail("这意味着 EdgeLite 的 IntegrationEndpoint 服务没有启动")
            elif resp.status_code == 200:
                ok("集成端点就绪")
            elif resp.status_code == 404:
                info("集成协议列表端点不存在（可能版本不同）")
            else:
                info(f"响应: {resp.text[:200]}")
        except Exception as e:
            fail(f"异常: {e}")

        # ─── 步骤5: 测试推送设备 (siemens_s7) ───
        next_step("推送测试设备 (protocol=siemens_s7)")
        test_device = {
            "device_id": "diag-test-s7",
            "name": "诊断测试S7设备",
            "protocol": "siemens_s7",
            "config": {
                "ip": "10.0.0.82",
                "port": 102,
                "rack": 0,
                "slot": 1,
            },
            "points": [
                {"name": "test_point", "address": "DB1.DBD0", "data_type": "float32"}
            ],
            "collect_interval": 10,
        }
        try:
            resp = await client.post("/api/v1/integration/push-device", headers=headers, json=test_device)
            info(f"HTTP {resp.status_code}")
            info(f"响应: {resp.text[:500]}")
            if resp.status_code in (200, 201):
                ok("推送成功！")
                results["push_siemens_s7"] = True
            elif resp.status_code == 422:
                body = resp.json()
                msg = body.get("message", body.get("detail", resp.text[:300]))
                fail(f"422 验证失败: {msg}")
            elif resp.status_code == 409:
                body = resp.json()
                msg = str(body)
                if "already exists" in msg.lower():
                    info("设备已存在，先删除")
                    del_resp = await client.delete("/api/v1/devices/diag-test-s7", headers=headers)
                    info(f"DELETE HTTP {del_resp.status_code}")
                    # 重试
                    resp = await client.post("/api/v1/integration/push-device", headers=headers, json=test_device)
                    info(f"重试 HTTP {resp.status_code}: {resp.text[:300]}")
                    if resp.status_code in (200, 201):
                        ok("重试推送成功！")
                        results["push_siemens_s7"] = True
                else:
                    fail(f"409 驱动启动失败: {msg[:300]}")
            elif resp.status_code == 503:
                fail("503 — 集成端点未就绪")
            else:
                fail(f"HTTP {resp.status_code}")
        except Exception as e:
            fail(f"异常: {e}")

        # ─── 步骤6: 测试推送设备 (s7 别名) ───
        next_step("推送测试设备 (protocol=s7 别名)")
        test_device_s7 = dict(test_device)
        test_device_s7["device_id"] = "diag-test-s7-alias"
        test_device_s7["name"] = "诊断测试S7设备(别名)"
        test_device_s7["protocol"] = "s7"
        try:
            resp = await client.post("/api/v1/integration/push-device", headers=headers, json=test_device_s7)
            info(f"HTTP {resp.status_code}")
            info(f"响应: {resp.text[:500]}")
            if resp.status_code in (200, 201):
                ok("s7 别名推送成功！")
                results["push_s7_alias"] = True
            elif resp.status_code == 422:
                body = resp.json()
                msg = body.get("message", body.get("detail", resp.text[:300]))
                fail(f"422 验证失败: {msg}")
                if "not registered" in msg:
                    fail("EdgeLite 不支持 s7 别名 — 只能用 siemens_s7")
            else:
                info(f"HTTP {resp.status_code}: {resp.text[:300]}")
        except Exception as e:
            fail(f"异常: {e}")

        # ─── 步骤7: 测试推送设备 (modbus_tcp) ───
        next_step("推送测试设备 (protocol=modbus_tcp)")
        test_device_modbus = {
            "device_id": "diag-test-modbus",
            "name": "诊断测试Modbus设备",
            "protocol": "modbus_tcp",
            "config": {
                "host": "10.0.0.82",
                "port": 5020,
                "slave_id": 1,
                "timeout": 5.0,
            },
            "points": [
                {"name": "test_point", "address": "HR100", "data_type": "float32"}
            ],
            "collect_interval": 10,
        }
        try:
            resp = await client.post("/api/v1/integration/push-device", headers=headers, json=test_device_modbus)
            info(f"HTTP {resp.status_code}")
            info(f"响应: {resp.text[:500]}")
            if resp.status_code in (200, 201):
                ok("modbus_tcp 推送成功！")
                results["push_modbus"] = True
            else:
                info(f"HTTP {resp.status_code}: {resp.text[:300]}")
        except Exception as e:
            fail(f"异常: {e}")

        # ─── 步骤8: 测试推送设备 (mqtt_client) ───
        next_step("推送测试设备 (protocol=mqtt_client)")
        test_device_mqtt = {
            "device_id": "diag-test-mqtt",
            "name": "诊断测试MQTT设备",
            "protocol": "mqtt_client",
            "config": {
                "broker": "10.0.0.82",
                "port": 1883,
                "subscribe_topic": "protoforge/data",
                "publish_topic": "protoforge/command",
            },
            "points": [
                {"name": "test_point", "address": "topic/protoforge/data", "data_type": "float32"}
            ],
            "collect_interval": 10,
        }
        try:
            resp = await client.post("/api/v1/integration/push-device", headers=headers, json=test_device_mqtt)
            info(f"HTTP {resp.status_code}")
            info(f"响应: {resp.text[:500]}")
            if resp.status_code in (200, 201):
                ok("mqtt_client 推送成功！")
                results["push_mqtt"] = True
            else:
                info(f"HTTP {resp.status_code}: {resp.text[:300]}")
        except Exception as e:
            fail(f"异常: {e}")

        # ─── 步骤9: 清理测试设备 ───
        next_step("清理测试设备")
        for did in ["diag-test-s7", "diag-test-s7-alias", "diag-test-modbus", "diag-test-mqtt"]:
            try:
                resp = await client.delete(f"/api/v1/devices/{did}", headers=headers)
                info(f"DELETE {did}: HTTP {resp.status_code}")
            except Exception as e:
                info(f"DELETE {did}: {e}")

        # ─── 总结 ───
        next_step("诊断总结")
        print(f"\n  登录: {'✓' if results.get('login') else '✗'}")
        print(f"  协议列表: {len(results.get('protocols', []))} 个协议")
        print(f"  推送 siemens_s7: {'✓' if results.get('push_siemens_s7') else '✗'}")
        print(f"  推送 s7 别名: {'✓' if results.get('push_s7_alias') else '✗'}")
        print(f"  推送 modbus_tcp: {'✓' if results.get('push_modbus') else '✗'}")
        print(f"  推送 mqtt_client: {'✓' if results.get('push_mqtt') else '✗'}")

        if not results.get("push_siemens_s7") and not results.get("push_s7_alias"):
            print(f"\n  *** 所有推送都失败！请检查上方的具体错误信息 ***")
            print(f"  常见原因:")
            print(f"  1. EdgeLite 集成端点未初始化 (503)")
            print(f"  2. must_change_password=True (403)")
            print(f"  3. 协议未注册 (422)")
            print(f"  4. 驱动启动失败 (409) — 缺少依赖如 snap7/pymcprotocol/aiomqtt")
            print(f"  5. 设备已存在 (409) — 需要先删除")

    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
