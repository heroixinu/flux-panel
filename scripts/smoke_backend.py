#!/usr/bin/env python3
"""Exercise the real HTTP/WebSocket protocol and database against a disposable backend.

Run only with the dedicated CI test PostgreSQL database (not production).
Uses the same checks for both JVM and Native images.
"""
import argparse
import base64
import concurrent.futures
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from websocket import create_connection, WebSocketBadStatusException

BASE = os.environ.get("FLUX_TEST_URL", "http://127.0.0.1:6365")


def sql(query):
    return subprocess.check_output(
        ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", query], text=True
    ).strip()


def request(path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = token
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode()


def post(path, data=None, token=None, expected=0):
    result = json.loads(request("/api/v1/" + path, {} if data is None else data, token))
    if expected is None:
        assert result["code"] != 0, (path, result["code"], result.get("msg"))
    else:
        assert result["code"] == expected, (path, result["code"], result.get("msg"))
    return result.get("data")


def login(user, password, expected=0):
    return post("user/login", {"username": user, "password": password, "captchaId": "legacy-ignored"}, expected=expected)


def eventually(predicate, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.2)
    raise AssertionError("Timed out waiting for backend state")


def envelope(value, secret):
    nonce = os.urandom(12)
    key = hashlib.sha256(secret.encode()).digest()
    data = AESGCM(key).encrypt(nonce, json.dumps(value).encode(), None)
    return json.dumps({"encrypted": True, "data": base64.b64encode(nonce + data).decode(),
                       "timestamp": int(time.time() * 1000)})


def open_envelope(message, secret):
    wrapper = json.loads(message)
    assert wrapper["encrypted"] is True
    raw = base64.b64decode(wrapper["data"])
    key = hashlib.sha256(secret.encode()).digest()
    return json.loads(AESGCM(key).decrypt(raw[:12], raw[12:], None))


def ws(secret, kind, **params):
    url = BASE.replace("http://", "ws://").replace("https://", "wss://")
    return create_connection(url + "/system-info?" + urllib.parse.urlencode(
        {"secret": secret, "type": kind, **params}), timeout=15)


def verify_initial_schema():
    assert sql("SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema() AND table_name IN ('forward','node','speed_limit','statistics_flow','tunnel','app_user','user_tunnel','vite_config')") == "8"
    assert sql("SELECT count(*) FROM app_user WHERE username='admin_user'") == "1"
    assert sql("SELECT value FROM vite_config WHERE name='app_name'") == "flux"


def main():
    verify_initial_schema()
    sql("INSERT INTO vite_config(name,value,time) VALUES ('captcha_enabled','true',1) ON CONFLICT DO NOTHING")
    assert post("captcha/check") == 0
    assert login("ADMIN_USER", "admin_user")["requirePasswordChange"] is True
    admin = login("admin_user", "admin_user")["token"]
    login("admin_user", "wrong", expected=None)
    post("user/login", {"username": "", "password": ""}, expected=None)
    post("node/list", expected=401)
    post("node/list", token=admin + "invalid", expected=401)
    assert post("config/get", {"name": "captcha_enabled"})["value"] == "false"
    post("config/update-single", {"name": "captcha_enabled", "value": "true"}, admin, expected=None)
    post("config/update", {"app_name": "native-smoke", "captcha_enabled": "true"}, admin)
    assert post("config/list", token=admin)["captcha_enabled"] == "false"
    assert post("config/get", {"name": "app_name"})["value"] == "native-smoke"

    # Exercise validation, BeanUtils, PostgreSQL generated keys, entity serialization, role checks.
    user = {"user": "ci_smoke_user", "pwd": "ci-smoke-password", "flow": 100, "num": 10,
            "expTime": 2727251700000, "flowResetTime": 0, "status": 1}
    post("user/create", user, admin)
    uid = int(sql("SELECT id FROM app_user WHERE username='ci_smoke_user'"))
    ordinary = login("ci_smoke_user", "ci-smoke-password")["token"]
    post("node/list", token=ordinary, expected=403)
    post("user/updatePassword", {"newUsername": "ci_smoke_user", "currentPassword": "ci-smoke-password",
          "newPassword": "ci-smoke-new-password", "confirmPassword": "ci-smoke-new-password"}, ordinary)
    login("ci_smoke_user", "ci-smoke-password", expected=None)
    ordinary = login("ci_smoke_user", "ci-smoke-new-password")["token"]
    assert any(item["id"] == uid for item in post("user/list", token=admin))

    node = {"name": "ci-smoke-node", "ip": "127.0.0.1", "serverIp": "127.0.0.1",
            "portSta": 1000, "portEnd": 2000}
    post("node/create", node, admin)
    nid = int(sql("SELECT id FROM node WHERE name='ci-smoke-node'"))
    secret = sql(f"SELECT secret FROM node WHERE id={nid}")
    assert secret
    assert any(item["id"] == nid for item in post("node/list", token=admin))

    # Real WebSocket handshake and encrypted bidirectional GOST command exchange.
    try:
        bad = ws("invalid-ci-secret", "1")
    except WebSocketBadStatusException:
        pass
    else:
        bad.close()
        raise AssertionError("Invalid node secret was accepted")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        monitor = ws(admin, "2")
        peer = None
        try:
            peer = ws(secret, "1", version="ci-smoke", http=0, tls=0, socks=0)
            eventually(lambda: sql(f"SELECT status FROM node WHERE id={nid}") == "1")
            peer.send(envelope({"memory_usage": 12.5, "cpu_usage": 1.0}, secret))
            assert open_envelope(peer.recv(), secret)["type"] == "call"
            change = dict(node, id=nid, http=1, tls=0, socks=0)
            pending = pool.submit(post, "node/update", change, admin)
            command = open_envelope(peer.recv(), secret)
            assert command["type"] == "SetProtocol" and command["data"]["http"] == 1
            peer.send(envelope({"requestId": command["requestId"], "message": "OK",
                                "type": "Response"}, secret))
            pending.result(timeout=20)
            assert sql(f"SELECT http FROM node WHERE id={nid}") == "1"
        finally:
            if peer is not None:
                peer.close()
            monitor.close()
    eventually(lambda: sql(f"SELECT status FROM node WHERE id={nid}") == "0")
    peer = ws(secret, "1", version="ci-smoke-reconnect", http=1, tls=0, socks=0)
    try:
        eventually(lambda: sql(f"SELECT version FROM node WHERE id={nid}") == "ci-smoke-reconnect")
    finally:
        peer.close()
    eventually(lambda: sql(f"SELECT status FROM node WHERE id={nid}") == "0")

    # Prepare deterministic relational fixtures without needing a real external GOST process.
    tid = int(sql(f"INSERT INTO tunnel(name,in_node_id,in_ip,out_node_id,out_ip,type,flow,created_time,updated_time,status) VALUES ('ci-smoke-tunnel',{nid},'127.0.0.1',{nid},'127.0.0.1',1,1,1,1,1) RETURNING id"))
    fid = int(sql(f"INSERT INTO forward(user_id,user_name,name,tunnel_id,in_port,remote_addr,created_time,updated_time,status) VALUES ({uid},'ci_smoke_user','ci-smoke-forward',{tid},1234,'example:80',1,1,1) RETURNING id"))
    pid = int(sql(f"INSERT INTO user_tunnel(user_id,tunnel_id,num,flow,flow_reset_time,exp_time,status) VALUES ({uid},{tid},10,100,0,2727251700000,1) RETURNING id"))
    assert any(item["id"] == fid for item in post("forward/list", token=ordinary))
    post("tunnel/list", token=admin)
    post("speed-limit/list", token=admin)
    path = "/flow/upload?" + urllib.parse.urlencode({"secret": secret})
    flow = {"n": f"{fid}_{uid}_{pid}_tcp", "u": 3, "d": 5}
    assert request(path, flow) == "ok"
    # request() serializes objects; use the envelope object so the body is not double-encoded.
    assert request(path, json.loads(envelope(flow, secret))) == "ok"
    assert sql(f"SELECT in_flow || ',' || out_flow FROM forward WHERE id={fid}") == "10,6"
    assert sql(f"SELECT in_flow || ',' || out_flow FROM app_user WHERE id={uid}") == "10,6"
    assert sql(f"SELECT in_flow || ',' || out_flow FROM user_tunnel WHERE id={pid}") == "10,6"

    # Scheduled statistics and flow reset run every five seconds in the disposable CI container.
    eventually(lambda: sql(f"SELECT count(*) FROM statistics_flow WHERE user_id={uid} AND total_flow=16") != "0", timeout=25)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).day
    sql(f"UPDATE app_user SET flow_reset_time={today} WHERE id={uid}")
    sql(f"UPDATE user_tunnel SET flow_reset_time={today} WHERE id={pid}")
    eventually(lambda: sql(f"SELECT in_flow || ',' || out_flow FROM app_user WHERE id={uid}") == "0,0", timeout=25)
    eventually(lambda: sql(f"SELECT in_flow || ',' || out_flow FROM user_tunnel WHERE id={pid}") == "0,0", timeout=25)
    sql(f"UPDATE app_user SET flow_reset_time=0 WHERE id={uid}")
    sql(f"UPDATE user_tunnel SET flow_reset_time=0 WHERE id={pid}")

    # Replace default credentials to prove initialization preserves the existing database on restart.
    post("user/updatePassword", {"newUsername": "ci_smoke_admin", "currentPassword": "admin_user",
          "newPassword": "ci-admin-new-password", "confirmPassword": "ci-admin-new-password"}, admin)
    assert login("ci_smoke_admin", "ci-admin-new-password")["requirePasswordChange"] is False
    print("HTTP, validation, role, SQL mapping, WebSocket, AES-GCM, JWT, flow and credential tests passed")


def verify_restart():
    assert sql("SELECT count(*) FROM app_user WHERE username='admin_user'") == "0"
    assert sql("SELECT count(*) FROM app_user WHERE username='ci_smoke_admin'") == "1"
    assert sql("SELECT count(*) FROM forward WHERE name='ci-smoke-forward'") == "1"
    assert sql("SELECT value FROM vite_config WHERE name='app_name'") == "native-smoke"
    assert post("captcha/check") == 0
    login("ci_smoke_admin", "ci-admin-new-password")
    login("ci_smoke_user", "ci-smoke-new-password")
    print("Existing database and password changes preserved after restart")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    if args.restart:
        verify_restart()
    else:
        main()
