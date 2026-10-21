# 選手ID・所属・経歴

[台帳トップへ](README.md)

| ID | 候補 | 優先度 | 資料 | 入口接続 |
|---|---|---|---|---|
| [S021](#s021) | Chadwick Persons Register | A | 資料確認済み | reachable |
| [S022](#s022) | MLB Stats API：人物・ロスター・球団 | A | 資料確認済み | reachable |
| [S023](#s023) | SportsDataverse：リーグ・球団の年度別対応 | A | 資料確認済み | reachable |
| [S024](#s024) | Wikidata：人物・球場・組織の識別子 | B | 一次資料未確認 | http_error |
| [S025](#s025) | Wikipedia：経歴・球場履歴の出典探索 | C | 一次資料未確認 | reachable |

## S021

**Chadwick Persons Register** — 異なるサイト・リーグの人物IDを結び付ける登録表。

- 提供元グループ: `chadwick` / 種類: `dataset` / 対象: MLB・NPB・MiLB・その他
- 入口: https://github.com/chadwickbureau/register
- 収録範囲: READMEでは2016年以降の公開履歴があると説明。人物・ID体系によって欠損がある。
- 取得方法・形式: people・names・links等のCSVを版固定して取得する候補。 / CSV
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: Open Data Commons Attribution License 1.0（documented）。帰属表示を保持。人物対応が完全であるとは限らず、版ごとの対応表を保存。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: key_uuid・key_mlbam・key_retro・key_npb・key_bbref・key_fangraphs
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 短縮IDの再利用、人物の統合・分離、同姓同名を考慮。 / 氏名だけで自動結合しない。
- 確認資料: [MLBAM・Retrosheet・NPB等のID対応、改訂・統合分離、ODC-Byを確認](https://raw.githubusercontent.com/chadwickbureau/register/HEAD/README.md)

## S022

**MLB Stats API：人物・ロスター・球団** — 人物ID、球団ID、所属・ポジションの参照元候補。

- 提供元グループ: `mlb` / 種類: `dataset` / 対象: MLB・MiLB
- 入口: https://www.mlb.com/players
- 収録範囲: 現行情報と過去時点のロスターが同じ取得方法で得られるか未確認。
- 取得方法・形式: APIのpeople/teams/roster等の仕様を調査。入口は台帳段階では本文を取得しない。 / JSON
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: person.id・team.id・season・roster date
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 現在の所属を過去シーズンへ一律適用しない。
- 確認資料: [MLB非公式ラッパーの説明と、データ利用条件はMLB側に従う旨を確認](https://raw.githubusercontent.com/toddrob99/MLB-StatsAPI/master/README.md)
- 確認資料: [MLB・NCAA・FanGraphs・Retrosheet等の取得機能と配布先を確認](https://raw.githubusercontent.com/BillPetti/baseballr/master/README.md)

## S023

**SportsDataverse：リーグ・球団の年度別対応** — リーグ・地区・所属・別名・NCAA/ESPN対応の年度別参照表。

- 提供元グループ: `sportsdataverse` / 種類: `dataset` / 対象: MLB・NCAA
- 入口: https://github.com/sportsdataverse/sdv-reference-data
- 収録範囲: README記載でMLB 1901–2026、NCAA baseball 2010–2026。ファイル単位の網羅性は未検査。
- 取得方法・形式: CONTRACT.mdとReleaseのCSV/Parquetを確認。 / CSV・Parquet
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: team ID・season・SDV group ID
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 現在の地区名を過去に適用しない。 / 名称の手修正行と自動取得行の出典を残す。
- 確認資料: [球場寸法2001–2026、MLB組織1901–2026、NCAA組織2010–2026等の文書記載を確認](https://raw.githubusercontent.com/sportsdataverse/sdv-reference-data/HEAD/README.md)

## S024

**Wikidata：人物・球場・組織の識別子** — 人物・球場・組織の共通IDと外部ID、位置・経歴の補助情報。

- 提供元グループ: `wikimedia` / 種類: `reference` / 対象: 全世界
- 入口: https://www.wikidata.org/
- 収録範囲: 項目ごとに収録・出典・更新状況が異なる。
- 取得方法・形式: SPARQL・API・dumpのうち必要な方法を選ぶ。全dumpは取得しない。 / JSON・RDF
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: CC0候補（今回、一次利用条件ページは未確認）（needs_review）。Wikimediaの他のコンテンツや画像と同じ許諾と考えない。
- 状態: 一次資料未確認 / 入口 http_error / 本体サンプル未取得
- 結合キー候補: QID・external ID
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 項目の出典と更新日を確認し、公式記録の代わりに無条件採用しない。 / 初回の入口確認は http_error / HTTP 502。データの入手可能性は未確定。

## S025

**Wikipedia：経歴・球場履歴の出典探索** — 球場改修・球団改称・経歴等の参考文献と外部リンクを発見する入口。

- 提供元グループ: `wikimedia` / 種類: `reference` / 対象: 全世界
- 入口: https://ja.wikipedia.org/wiki/野球
- 収録範囲: 各ページの版・引用元に依存。
- 取得方法・形式: まず参考文献・出典URLを台帳に追加する。本文の一括取得は別途判断。 / HTML・wikitext
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 一次資料未確認 / 入口 reachable / 本体サンプル未取得
- 結合キー候補: page ID・revision ID・外部出典
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 記事の記述を一次事実と混同しない。 / 本文・画像の利用条件とデータ項目の条件を分ける。 / 本文調査ではHTTP 403。接続チェックの一回の成功を継続取得可能と扱わない。
- 別途の本文確認: HTTP 403。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。
