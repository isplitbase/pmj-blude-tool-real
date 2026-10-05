# pmj-blude-tool-real

ファイル自動更新の中継API (Cloud Run)。

配信先サーバ(149/148)は社内ネットワークから `run.app` と `oauth2.googleapis.com` にしか
出られないため、配信キューを持つ EC2 との橋渡しをこのサービスが行う。

```
配信先(cron) → pmj-door(-real) → [pmj-blude-tool] → test1.aitask.biz/…/deploy_api.php → dbblude
```

- `pmj-blude-tool`      … 検証用
- `pmj-blude-tool-real` … 本番用

## エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| GET  | `/`       | ヘルスチェック |
| POST | `/ping`   | EC2 側 API まで届くかの確認 |
| POST | `/fetch`  | 未実施を1件取り出す(doing にする) |
| POST | `/done`   | 完了にする |
| POST | `/error`  | 失敗にする |

### POST /fetch
```json
{ "target_server": "149", "worker_id": "cron-149" }
```
返り値(未実施あり):
```json
{ "status":"OK", "found":true, "id":12,
  "file_full_path":"/var/www/html/xxx.html",
  "full_code":"…", "content_sha256":"…", "file_mode":"644" }
```
未実施が無いときは `{"status":"OK","found":false}`。

### POST /done
```json
{ "id": 12, "backup_path": "/var/www/html/_deploy_backups/20261005/xxx.html" }
```

### POST /error
```json
{ "id": 12, "error_message": "write failed: Permission denied" }
```

## 必要な環境変数 (Cloud Run に設定)

| 変数 | 必須 | 説明 |
|---|---|---|
| `BLUDE_API_URL` | ○ | EC2 側 API の URL |
| `BLUDE_API_KEY` | ○ | EC2 の `/data/blude_api.conf.php` の `api_key` と同じ値 |
| `BLUDE_TIMEOUT` | 任意 | EC2 API への待ち時間(秒)。既定 60 |
| `PORT`          | 自動 | Cloud Run が設定 |

## デプロイ

GitHub への push で自動デプロイされる(リポジトリからの継続的デプロイ)。
`gcloud run deploy` は不要。環境変数の追加・変更だけコンソールで行う。

## pmj-door 側の設定

door は `target` 名で転送先を選ぶため、door のサービスに次を追加する。

| 変数 | 値 |
|---|---|
| `TARGET_BLUDETOOL` | このサービスの URL |

あわせて、door のサービスアカウントにこのサービスへの `roles/run.invoker` を付与する。

配信先からは door 経由でこう呼ぶ。

```json
POST /call
{ "target": "bludetool", "path": "/fetch",
  "payload": { "target_server": "149", "worker_id": "cron-149" } }
```

## 安全のための制限

- 配信先として受け付けるのは `149` / `148` / `test1` のみ。
- 書き込み先パスの検査(`/var/www/html/` 配下のみ、`..` 禁止)は EC2 側 API と
  配信先サーバ側の両方で行う。このサービスは内容を素通しするだけで判断しない。
