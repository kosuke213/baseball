# 第5段階：実測研究データと年代比較

**[DB・CSV・研究原本をダウンロード](https://raw.githubusercontent.com/kosuke213/baseball/codex/stage5-tracking/data_sources/stage5/database_bundle.zip)** / **[全取得原本のバックアップ](https://raw.githubusercontent.com/kosuke213/baseball/codex/stage5-tracking/data_sources/stage5/originals_bundle.zip)** / [実施結果と評価](https://github.com/kosuke213/baseball/blob/codex/stage5-tracking/docs/data-stage5/README.md) / [出典・利用条件](ATTRIBUTIONS.md)

WindowsではZIPを保存 → 右クリック →「すべて展開」。`research_measurements.csv` は追加した研究の数値、`research_datasets.csv` は対象者・制約、`coverage.csv` は年度別の取得範囲です。`warehouse.sqlite3` は既存の2023〜2025年プレーを含む統合DBで、[DB Browser for SQLite](https://sqlitebrowser.org/) などで開けます。

研究の個人測定値・個人内の平均・全体平均・相関を `statistic` で区別します。台湾のCSVは実データ56人分ですが、説明文は64人です。単位が列名に書かれていないため、球速を含め `source_unit` と換算値は空欄です。数値からkm/hと推測していません。

大学投手の体幹研究には個々の投球速度の列がありません。参加者の国は取得表だけでは確認できず、著者名から日本と推測していません。打球実験は米国大学選手16人・金属バット・投球機・選ばれた良い打球という条件です。Table 1のN=39〜41の集計単位は本文と十分整合せず未確定で、人数や独立した打球数として扱いません。平均とSDから架空の生データも作っていません。

**詳細なプロ野球の再現は、まだ検証できる状態ではありません。** 球の回転、変化量、投球位置、打球角度、軌道、NPB公式戦の実測値が不足します。MLBサイトの自動取得条件、制限公開資料、商用目的と整合しないライセンスを確認し、未取得の理由を `source_review.json` に残しました。`quality.json` のデータ検査合格と、再現精度の評価は別です。

年代は1996・2006・2016・2019・2022年を比較用に追加しました。これらはGame Logsのみで、2023〜2025年のプレーと取得粒度が違います。8年分の連続期間ではありません。球団数、DH、タイブレーク、投球時計、ボール等の環境差を無視して同一分布で学習しないでください。`historical_comparison.csv` は1球団1試合あたり得点・四球、100打数あたり本塁打・三振です。打席あたりの割合ではありません。

```sql
SELECT * FROM research_datasets;
SELECT metric,condition,statistic,value,sd,reported_n,source_unit,normalized_value
FROM research_measurements WHERE metric IN ('velocity','exit_velocity','bat_speed');
SELECT * FROM research_confirmed_speeds;
SELECT season,coverage,count(*) FROM games JOIN stage5_game_coverage USING(game_id)
GROUP BY season,coverage;
```

各研究行から `artifact_id` と `source_location`、`artifacts.sha256` をたどると、原本のCSV行・DOCX表セル・PDF表へ戻れます。研究参加者は研究内だけのIDであり、プロ選手の人物表とは結合していません。

DBのZIPには追加した3研究の原本を同梱します。別の `originals_bundle.zip` には **今回までに統合DBへ収録した全取得原本** を `originals/blobs/<SHA256>`、取得メタデータを `originals/index/<artifact_id>.json` に同梱します。未使用列、元CSV、研究PDF/DOCX、利用条件確認資料も保持します。ZIP内 `manifest.json` は全原本の出典・サイズ・SHA256、`snapshot.json` はDBと同梱原本の指紋です。第1段階の候補すべてを取得したという意味ではありません。

再実行は標準ライブラリで可能です。元リポジトリのルートで次を実行します。

```bash
python -m data_collection.stage5
python -m data_collection.stage5 --offline
```

初回の収集は審査済み計画で `--record-lock` を指定し、以後は `lock.json` で固定します。取得失敗時は前の現行版を維持し、検証済みキャッシュから再開できます。現行版は `data/research/stage5/current.json`、以前の第3・第4段階や架空リーグのDBは別に保持します。新しい版への自動切り替え、学習、較正は実施していません。

クラウド外で再構築する場合は、`originals_bundle.zip` の `originals/blobs` と `originals/index` を `data/research/pilot/raw/` に復元し、第3・第4段階のZIPのDBを `data/research/warehouse/snapshots/717f7b15b7df58818ce55989/warehouse.sqlite3` に置き、同ZIPの `policy.json` も同じフォルダーへ置きます。第5段階の公開ブランチのコード・計画・lockで `--offline` を実行します。変更可能なAPIメタデータは元の取得時点の内容を使い、最新APIが過去と同じバイト列を返すとは仮定しません。
