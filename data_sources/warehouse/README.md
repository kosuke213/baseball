# 第3・第4段階：共通DBと年単位の収集

2023〜2025年を対象に、試合・プレー・球団年度・球場・人物IDを結ぶSQLiteを構築します。

[実施結果](https://github.com/kosuke213/baseball/blob/codex/data-warehouse/docs/data-warehouse/README.md) / **[DBとCSVをダウンロード](https://raw.githubusercontent.com/kosuke213/baseball/codex/data-warehouse/data_sources/warehouse/database_bundle.zip)** / [必須出典表示](ATTRIBUTIONS.md)

ZIPを保存し、Windowsでは右クリック →「すべて展開」。`games.csv` は全収録試合の結果、`teams.csv` は球団年度、`parks.csv` は球場の参照情報です。`warehouse.sqlite3` は全収録プレーを含む共通DBで、[DB Browser for SQLite](https://sqlitebrowser.org/) 等で開けます。検査に不一致がある試合は `quarantine.csv` で分かります。

このZIPは型を付けた共通DBです。取得元の全列を含む年別ZIPや人物表の原本はクラウドの原本ストアに残し、Gitやこの配布ZIPへ大量の原本を複製していません。DBの各行に原本IDと行番号があり、取得日時・URL・SHA256・定義資料は `manifest.json` にあります。SQLiteの `artifacts` にも同じ情報を収録しています。

```sql
SELECT season, count(*) AS games FROM games GROUP BY season;
SELECT game_id, visiting_runs, home_runs FROM game_results LIMIT 10;
SELECT inning,half,event_raw,batter_person_id,pitcher_person_id
FROM analysis_plays WHERE game_id='retrosheet:game:SDN202403200' ORDER BY play_number;
SELECT * FROM game_checks WHERE status!='pass';
```

`plays` は収録した全てのレギュラーシーズン記録、`analysis_plays` は試合の整合性検査を通過し、pbp_typeがfullの記録です。どちらも投球数・打席数と同義ではありません。`NP` 行も保持します。人物の結合は名前ではなく、版を固定したID表の一意対応だけを使います。

球団は `retrosheet:team:<原コード>` と年度の組、球場は `retrosheet:park:<原コード>`、人物は `chadwick:person:<UUID>`、試合は `retrosheet:game:<原ID>` です。球団の移転・改名を推測でまとめません。球場名は参照表掲載時点の表記で、各年度の名称を保証しません。未確認の球場情報、二次資料の日本の候補表、東京の気象を区別して保持します。

リポジトリのルートで実行します。収集・DB構築は標準ライブラリだけで動きます。更新確認で新しいリポジトリ版を検知する部分にはGitを使い、利用できない場合は確認未完として表示します。Windowsでは `python` を `py -3` に置き換えられます。

```bash
python -m data_collection.warehouse run
python -m data_collection.warehouse run --offline
python -m data_collection.warehouse status
python -m data_collection.warehouse source-row --game-id SDN202403200 --play 1
python -m data_collection.warehouse check-updates
```

取得原本は既存の `data/research/pilot/raw` を共通ストアとして再利用します。正規化DBは `data/research/warehouse/snapshots/<snapshot_id>/warehouse.sqlite3`、現行版は `data/research/warehouse/current.json` が指します。取得・解析の失敗時は前の現行版を維持し、取得済み原本から再開できます。既存の第2段階のlock・標本DB、架空試合DBは別に保持します。

`check-updates` は可変URLを条件付き要求で確認し、Gitが利用可能なら固定した参照表の提供元リポジトリのHEADも確認します。更新候補を記録するだけです。固定した原本と旧DBを上書きしません。条件資料が変わった場合は利用条件を読み直し、新しい版の計画を作って取得・検査します。自動で学習へ投入しません。定期処理の設定はGitHub Actions用にありますが、既定ブランチへ反映して有効化するまで常時実行されません。

検査件数・例外・実際の収録期間は `quality.json`、ファイル指紋は `snapshot.json` と `bundle.json` を参照してください。Retrosheetの指定表示をデータと一緒に保持してください。

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".
