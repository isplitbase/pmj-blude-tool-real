# -*- coding: utf-8 -*-
"""pmj-blude-tool : ファイル自動更新の中継API (Cloud Run)

  配信先サーバ(149/148、試験中は test1)は社内ネットワークから
  run.app と oauth2.googleapis.com にしか出られない。
  そこで、配信キューを持つ EC2(test1.aitask.biz) との橋渡しをこのサービスが行う。

      配信先(cron) → pmj-door(-real) → [このサービス] → test1 の deploy_api.php → dbblude

  エンドポイント:
    GET  /          … ヘルスチェック
    POST /fetch     … 未実施を1件取り出す(doing にする)   { target_server, worker_id }
    POST /done      … 完了にする                          { id, backup_path? }
    POST /error     … 失敗にする                          { id, error_message }
    POST /release   … doing を pending に戻す              { id }

  環境変数 (Cloud Run に設定):
    BLUDE_API_URL  … 例 https://test1.aitask.biz/xxxxxxxx/deploy_api.php
    BLUDE_API_KEY  … EC2 の /data/blude_api.conf.php の api_key と同じ値
    BLUDE_TIMEOUT  … 任意。既定 60(秒)
    BLUDE_CLIENT_SECRET … 任意。設定すると、配信先からの呼び出しに
                          payload.client_secret の一致を要求する(合言葉)
"""

import hmac
import os

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

API_URL = os.environ.get("BLUDE_API_URL", "").rstrip()
API_KEY = os.environ.get("BLUDE_API_KEY", "")
TIMEOUT = int(os.environ.get("BLUDE_TIMEOUT", "60"))

# 配信先サーバとの合言葉。設定されている場合のみ照合する(未設定なら素通し)。
# サービスアカウント鍵とは別に持たせ、鍵だけが漏れても配信経路を触れないようにする。
CLIENT_SECRET = os.environ.get("BLUDE_CLIENT_SECRET", "")

# 配信先として受け付ける名前(想定外の値を EC2 へ渡さない)
ALLOWED_TARGETS = ("149", "148", "test1")


def _call_api(payload):
    """EC2 の deploy_api.php を呼ぶ。戻り値は (レスポンスJSON, HTTPステータス)。"""
    if not API_URL or not API_KEY:
        return {"status": "NG", "error": "BLUDE_API_URL / BLUDE_API_KEY が未設定"}, 500
    try:
        r = requests.post(
            API_URL,
            json=payload,
            headers={"X-Blude-Key": API_KEY, "Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        return {"status": "NG", "error": "api request failed: %s" % str(e)[:300]}, 502
    try:
        return r.json(), r.status_code
    except ValueError:
        return ({"status": "NG",
                 "error": "api returned non-JSON",
                 "http_code": r.status_code,
                 "body": r.text[:300]}, 502)


def _body():
    return request.get_json(silent=True) or {}


def _deny_by_secret(b):
    """合言葉が合わなければ拒否の応答を返す。問題なければ None。
       BLUDE_CLIENT_SECRET が未設定のときは照合しない(導入時の互換のため)。"""
    if not CLIENT_SECRET:
        return None
    got = str((b or {}).get("client_secret") or "")
    if not hmac.compare_digest(CLIENT_SECRET, got):
        return jsonify({"status": "NG", "error": "client secret mismatch"}), 403
    return None


@app.get("/")
def health():
    return jsonify({"status": "ok", "service": "pmj-blude-tool-real",
                    "api_configured": bool(API_URL and API_KEY),
                    "client_secret_required": bool(CLIENT_SECRET)})


@app.post("/fetch")
def fetch():
    b = _body()
    deny = _deny_by_secret(b)
    if deny:
        return deny
    target = str(b.get("target_server") or "149")
    if target not in ALLOWED_TARGETS:
        return jsonify({"status": "NG", "error": "unknown target_server: %s" % target}), 400
    payload = {"action": "fetch",
               "target_server": target,
               "worker_id": str(b.get("worker_id") or "cron")[:64]}
    res, code = _call_api(payload)
    return jsonify(res), code


@app.post("/done")
def done():
    b = _body()
    deny = _deny_by_secret(b)
    if deny:
        return deny
    if not b.get("id"):
        return jsonify({"status": "NG", "error": "id required"}), 400
    payload = {"action": "done", "id": int(b["id"])}
    if b.get("backup_path"):
        payload["backup_path"] = str(b["backup_path"])[:512]
    res, code = _call_api(payload)
    return jsonify(res), code


@app.post("/error")
def error():
    b = _body()
    deny = _deny_by_secret(b)
    if deny:
        return deny
    if not b.get("id"):
        return jsonify({"status": "NG", "error": "id required"}), 400
    payload = {"action": "error",
               "id": int(b["id"]),
               "error_message": str(b.get("error_message") or "")[:2000]}
    res, code = _call_api(payload)
    return jsonify(res), code


@app.post("/release")
def release():
    """doing を pending に戻す(dry-run や、途中で中断したときの戻し用)。"""
    b = _body()
    deny = _deny_by_secret(b)
    if deny:
        return deny
    if not b.get("id"):
        return jsonify({"status": "NG", "error": "id required"}), 400
    res, code = _call_api({"action": "release", "id": int(b["id"])})
    return jsonify(res), code


@app.post("/ping")
def ping():
    """EC2 側 API まで届くかの確認用。"""
    res, code = _call_api({"action": "ping"})
    return jsonify(res), code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
