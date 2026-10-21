# 第2段階：実データの少量取得・品質検査

利用条件を確認した4提供元・台帳5項目から、原本76,208,720バイトを保存し、実データを独立したSQLiteに収録しました。学習・試合モデルの変更はまだ行っていません。

**[データベースと確認用CSVをダウンロード](https://raw.githubusercontent.com/kosuke213/baseball/codex/data-sampling-pilot/data_sources/pilot/sample_bundle.zip)** / [詳しい結果](https://github.com/kosuke213/baseball/blob/codex/data-sampling-pilot/docs/data-pilot/README.md) / [必須の出典表示](ATTRIBUTIONS.md)

WindowsではZIPを保存して右クリック →「すべて展開」。まず `sample_games.csv`、`identity_matches.csv`、`weather_sample.csv` をExcel等で開けます。`pilot.sqlite3` は実際のDBで、閲覧には [DB Browser for SQLite](https://sqlitebrowser.org/) などを使えます。ZIPは元の年別配布物すべてを含むものではなく、今回の検証に使った加工済みの部分集合です。

| DBのビュー | 収録件数 | 内容 |
|---|---:|---|
| games | 2,429 | 2024年の公式Game Logs全行。2024-03-20〜09-30 |
| plays | 2,612 | 選んだ32試合の公式parsed CSV。177列を保持。NP行も含む |
| people | 693 | 当該試合の打者・投手593人＋別のNPB ID付き100例 |
| japan_board | 18 | Japan Prospect Labの2026ドラフト候補ボード。二次資料 |
| weather | 24 | 気象庁・東京の2024-03-29、1〜24時。品質記号・セル属性も保持 |

32試合について、得点の推移・最終得点・アウトの推移・総アウト数・攻撃順・同一攻撃中の塁の占有を照合し、不一致0件でした。選手ID593件は一意に対応し、未対応・曖昧な対応は0件です。これはこの標本に限った結果です。独立したスコアカードとの検証や全年度の完全性は保証しません。

`manifest.json` に取得URL・取得日時・版・バイト数・SHA256・利用条件と証拠を保存。原本は収集環境の `data/research/pilot/raw/blobs/<SHA256>` にあり、Gitには大きな原本を含めていません。CSVからDBへの変換では全列を保持し、気象にJST/UTC、Game Logsに複合キー由来のgame_idを追加しました。JSONL/SQLiteへの変換と標本抽出以外の補完・能力推定はしていません。

DBは `records` に原列のJSONと出典を保持し、5つのビューから参照できます。例：

```sql
SELECT json_extract(data_json, '$.game_id') AS game_id,
       json_extract(data_json, '$.field_010') AS visiting_runs,
       json_extract(data_json, '$.field_011') AS home_runs
FROM games LIMIT 10;
```

`artifacts` 表は原本の指紋と取得情報、`identity_matches` 表は名前に頼らないID対応を収録します。既存の架空野球用 `data/lab.sqlite3` とは別のDBです。

同じ原本で再構築するにはリポジトリのルートで次を実行します。収集部分はPython 3.11以上の標準ライブラリだけで動きます。初回はHTTPS接続が必要です。

```bash
python -m data_collection
# 原本キャッシュのSHA256を検査して、通信なしで再構築
python -m data_collection --offline
```

Windowsで `python` が使えなければ `py -3` に置き換えられます。取得先が原本を訂正すると固定SHA256検査が止まります。その場合は既存のlockや原本を上書きせず、新しい版の計画と保存先で訂正を受け入れます。失敗済みの原本は成功キャッシュとして保存しません。SQLiteは一時DBで構築・整合性検査してから置換します。空データや重複は削除・ゼロ補完で隠さず、検査結果に残します。

`quality.json` は列別の空欄・記号・重複と全検査結果、`plan.json` は対象と取得上限、`lock.json` はURLと固定指紋、`bundle.json` はZIPとDBの指紋です。`initial_size_guard.json` は初回のサイズ上限による停止と、その後の上限調整の記録です。

## 出典

[ATTRIBUTIONS.md](ATTRIBUTIONS.md) の表示をデータと一緒に保持してください。特にRetrosheetは以下の指定表示を必要とします。

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".
