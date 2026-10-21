# データ・情報源の収集先台帳

調査日: 2026-10-21。候補 **128件**、提供元グループ **84**、補助ツール **13件**。

説明資料・公開ページを確認: **110件**。十分な資料確認が残る候補: **18件**。統計レコードのサンプルセットは未作成です。

件数はデータセット・入口・参考資料を含みます。同じ提供元の別データは同じグループで識別します。候補数は取得済みデータ数や独立した提供企業数ではありません。

「資料確認済み」は説明資料の確認を意味します。HTTP 200は入口ページへの接続確認です。どちらもデータ取得・欠損検査・利用許可の完了を意味しません。優先度A/B/Cは次の調査順で、収集許可ではありません。本体サンプル取得は第2段階です。

[調査方法・注意点](methodology.md) / [重点候補と発見事項](findings.md) / [検証記録](validation.md) / [Excel向けCSV](../../data_sources/sources.csv) / [機械可読JSON](../../data_sources/catalog.json) / [接続結果](../../data_sources/link_checks.json)

## 分類別

| 分類 | 件数 |
|---|---:|
| [投球・打球・守備計測](pitch_tracking.md) | 17 |
| [試合経過・歴史・集計](game_history.md) | 10 |
| [選手ID・所属・経歴](identities.md) | 5 |
| [日本プロ・アマチュア・独立リーグ](japan.md) | 22 |
| [海外リーグ・国際大会・大学](international.md) | 18 |
| [球場・地理・移動](parks.md) | 5 |
| [天候・環境](weather.md) | 6 |
| [疲労・成長・動作・故障研究](health.md) | 8 |
| [契約・ドラフト・経営](business.md) | 8 |
| [ルール・統計定義・分析資料](rules.md) | 8 |
| [論文・データセット探索](research.md) | 14 |
| [公開アーカイブ・補助データ](archives.md) | 7 |

## 補助ツール

ライブラリは取得元データとは別に数えます。コードのOSSライセンスをデータの利用許可として扱いません。

| ツール | 役割 | 注意点 |
|---|---|---|
| [pybaseball](https://github.com/jldbc/pybaseball) | Statcast・FanGraphs・Baseball-Reference等のPython取得補助。 | 取得元の可用性・利用条件を別途確認。コードのOSS条件はデータ許諾ではない。 |
| [baseballr](https://github.com/BillPetti/baseballr) | MLB・NCAA・既存配布の調査とR取得補助。 | load系とscrape系の元提供者・版を分ける。 |
| [MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI) | MLB Stats APIのPythonラッパー。 | MLB非公式。READMEはMLBのデータ利用条件を参照。 |
| [Chadwick](https://github.com/chadwickbureau/chadwick) | Retrosheet形式の解析と公式記録への展開候補。 | ツールのライセンスと原イベントの条件を分ける。 |
| [R Lahman](https://github.com/cdalzell/Lahman) | Lahmanの表・列定義の調査と読み込み候補。 | パッケージGPLだけで元データの条件を決めない。 |
| [collegebaseball](https://github.com/nathanblumenfeld/collegebaseball) | NCAA取得・分析のPython候補。 | READMEにはPBPや日程など未完成の予定項目がある。現行機能を検証してから採用。 |
| [kbo-data](https://github.com/dev-bearabbit/kbo-data) | KBO取得用Pythonクライアント候補。 | READMEにはChromeDriver依存。自動取得許可・稼働は未確認。 |
| [Meteostat Python](https://github.com/meteostat/meteostat) | 観測気象と観測所の取得候補。 | コードMITと気象データの条件は別。 |
| [rnoaa](https://github.com/ropensci/rnoaa) | NOAA取得機能・移行先の調査。 | READMEはAPI変更とアーカイブ予定を警告。現状のままの採用は保留。 |
| [rcrossref](https://github.com/ropensci/rcrossref) | DOI・書誌情報の取得補助。 | 論文本文の利用条件は別途確認。 |
| [Wikidata Toolkit](https://github.com/Wikidata/Wikidata-Toolkit) | Wikidataの大規模処理候補。 | 原データ・画像・説明文それぞれの条件を確認。 |
| [DuckDB](https://github.com/duckdb/duckdb) | 将来のParquet横断SQL分析候補。 | 第1段階ではインストール・分析用データ取得は行わない。 |
| [PyArrow](https://github.com/apache/arrow) | 将来の列形式保存と読み込み候補。 | ソフトウェアが原データの利用権を追加するわけではない。 |

## 再生成

リポジトリ直下でPython 3.11以上を使用:

```bash
python scripts/catalog.py validate
python scripts/catalog.py build
# 未確認URLだけを確認
python scripts/catalog.py check-links
# 接続許可の変更後などに、すべてを明示的に再調査する場合
python scripts/catalog.py check-links --refresh
python scripts/catalog.py build
```

buildはCSV・閲覧用Markdown・台帳用SQLiteを再生成します。catalog.jsonが編集元です。既存の試合DBには触れません。check-linksは各URLを1回確認し、429の後は同じホストへの残りの要求を止めます。
