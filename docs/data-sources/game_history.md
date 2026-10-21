# 試合経過・歴史・集計

[台帳トップへ](README.md)

| ID | 候補 | 優先度 | 資料 | 入口接続 |
|---|---|---|---|---|
| [S012](#s012) | Retrosheet：イベント・プレー記録 | A | 資料確認済み | reachable |
| [S013](#s013) | Retrosheet：Game Logs | A | 資料確認済み | reachable |
| [S014](#s014) | Chadwick：拡張Retrosheet | A | 資料確認済み | reachable |
| [S015](#s015) | Chadwick Retrosplits | A | 資料確認済み | reachable |
| [S016](#s016) | Lahman：長期の選手・球団・成績データベース | A | 資料確認済み | reachable |
| [S017](#s017) | FanGraphs：打撃・投球・守備・状況別成績 | A | 資料確認済み | reachable |
| [S018](#s018) | Baseball-Reference：年度成績・試合記録 | B | 資料確認済み | http_error |
| [S019](#s019) | SportsDataverse：NCAA試合・プレー記録 | A | 資料確認済み | reachable |
| [S020](#s020) | SportsDataverse：配布ファイル・更新状況 | A | 資料確認済み | reachable |
| [S123](#s123) | Seamheads Negro Leagues Database | C | 資料確認済み | reachable |

## S012

**Retrosheet：イベント・プレー記録** — 打席、走者進塁、アウト、交代を復元するための歴史的イベント記録。

- 提供元グループ: `retrosheet` / 種類: `dataset` / 対象: MLB
- 入口: https://www.retrosheet.org/game.htm
- 収録範囲: 公式の年別配布ページを確認。1910年より前はbox score event形式のみという説明があり、イベント・復元・boxscoreの区分を保持する必要がある。
- 取得方法・形式: 公式の年別配布・書式資料を確認。Chadwickのofficial枝も比較。 / ZIP・EVT・ROS
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: Retrosheet Notices：指定の帰属表示条件（documented）。公式ページは販売・配布・商用製品を含む利用を案内し、指定の文言を目立つ形で表示するよう求める。転載時は当該配布版の表示を保持。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: Retrosheet game ID・player ID・event number
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 推定・復元されたイベントと実際のスコアカードを区別。 / 選手・球団の同じ試合が複数原資料に現れることがある。
- 確認資料: [officialとmasterの内容差、およびRetrosheetの権利・帰属表示を確認](https://raw.githubusercontent.com/chadwickbureau/retrosheet/HEAD/README.md)
- 確認資料: [試合別・状況別集計、原資料種別による重複、ODbLの記載を確認](https://raw.githubusercontent.com/chadwickbureau/retrosplits/HEAD/README.md)
- 確認資料: [公式の年別配布、復元データとの違い、Noticesの利用・帰属条件を確認。](https://www.retrosheet.org/game.htm)

## S013

**Retrosheet：Game Logs** — 試合日、チーム、スコア、球場など試合単位の比較記録候補。

- 提供元グループ: `retrosheet` / 種類: `dataset` / 対象: MLB
- 入口: https://www.retrosheet.org/gamelogs/index.html
- 収録範囲: 公式Game Logsページは1871–2025年を案内。試合別本体・欠損は未検査。
- 取得方法・形式: 年別ZIP・列定義を確認。 / CSV・ZIP
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: Retrosheet Notices：指定の帰属表示条件（documented）。公式ページは販売・配布・商用製品を含む利用を案内し、指定の文言を目立つ形で表示するよう求める。転載時は当該配布版の表示を保持。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: date・visiting team・home team・doubleheader number
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 同日ダブルヘッダーを日付だけで結合しない。
- 確認資料: [MLB・NCAA・FanGraphs・Retrosheet等の取得機能と配布先を確認](https://raw.githubusercontent.com/BillPetti/baseballr/master/README.md)
- 確認資料: [公式の1871–2025年の案内と、商用製品を含む利用・帰属条件を確認。](https://www.retrosheet.org/gamelogs/index.html)

## S014

**Chadwick：拡張Retrosheet** — Retrosheetの公式版と、訂正・拡張メタデータを含む版の配布。

- 提供元グループ: `chadwick` / 種類: `dataset` / 対象: MLB
- 入口: https://github.com/chadwickbureau/retrosheet
- 収録範囲: official枝とmaster枝の収録・改訂を個別に固定する必要がある。
- 取得方法・形式: ブランチ・コミットを固定して必要な年だけ取得。 / EVT・ROS・text
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: Retrosheet game ID・player ID
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 公式版と拡張版を混ぜない。 / 帰属表示条件を原提供元でも確認。
- 確認資料: [officialとmasterの内容差、およびRetrosheetの権利・帰属表示を確認](https://raw.githubusercontent.com/chadwickbureau/retrosheet/HEAD/README.md)

## S015

**Chadwick Retrosplits** — 選手・球団の試合別記録と打撃・投球の状況別集計。

- 提供元グループ: `chadwick` / 種類: `dataset` / 対象: MLB
- 入口: https://github.com/chadwickbureau/retrosplits
- 収録範囲: READMEではsplitsは1969年以降、daybydayはRetrosheet側の収録に依存と説明。実収録末年未確認。
- 取得方法・形式: 配布テキストと列定義を確認。 / CSV・text
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: ODbL 1.0 / DbCL 1.0（documented）。データベースと個別内容のライセンスを区別。帰属・共有条件と元Retrosheet条件を確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: game.id・player.id・game.source
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: evt/ded/boxの複数記録を重複計上しない。 / 推定試合と守備記録の精度差に注意。
- 確認資料: [試合別・状況別集計、原資料種別による重複、ODbLの記載を確認](https://raw.githubusercontent.com/chadwickbureau/retrosplits/HEAD/README.md)

## S016

**Lahman：長期の選手・球団・成績データベース** — 打撃・投球・守備、球団、人物、監督、賞などの年単位データ。

- 提供元グループ: `lahman` / 種類: `dataset` / 対象: MLB
- 入口: https://sabr.org/lahman-database/
- 収録範囲: SABR公式は1871–2025年の2025版を案内。一方、確認したRパッケージDESCRIPTIONは1871–2024と記載。採用する配布版を固定する。
- 取得方法・形式: SABR配布版とR Lahmanの列定義を比較して版を固定。 / CSV・SQL・Microsoft Access・R data（別配布）
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: 配布文書と原提供元別の条件を要確認（mixed）。公式ページはSeamheads由来データをライセンス取得して含むと説明。RパッケージGPLをSABR版全データの利用条件と見なさず、配布文書と原提供元別の条件を確認する。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: playerID・teamID・yearID・stint
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: RパッケージのGPL表記だけで元データの再配布条件を決めない。 / 移籍選手のstint、過去リーグ・フランチャイズID、資料間の収録年表記差を確認。
- 確認資料: [Rパッケージ14.0-0の対象期間説明とライセンス表記を確認](https://raw.githubusercontent.com/cran/Lahman/master/DESCRIPTION)
- 確認資料: [データベース構成・R版の配布説明を確認](https://raw.githubusercontent.com/cdalzell/Lahman/HEAD/README.md)
- 確認資料: [公式配布は1871–2025年、SQL/Access/CSV、Seamheads由来部分を含むと記載。R版と版が異なる。](https://sabr.org/lahman-database/)

## S017

**FanGraphs：打撃・投球・守備・状況別成績** — シーズン・任意期間の成績、状況別集計、派生指標の候補。

- 提供元グループ: `fangraphs` / 種類: `dataset` / 対象: MLB・MiLB
- 入口: https://www.fangraphs.com/leaders/major-league
- 収録範囲: 項目・シーズン・リーグ別に異なる。現在のダウンロード範囲は未確認。
- 取得方法・形式: 公式ダウンロード機能と条件を確認。pybaseball/baseballrの既存取得機能も調査。 / CSV・HTML
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: IDfg・Season・Team
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 算出指標の定義変更、最低出場閾値、集計と元記録の重複を確認。 / クライアントが存在しても提供元の取得許可・稼働を保証しない。
- 確認資料: [投球・打席・集計・日程の取得機能と、過去のStatcastにも改訂がある旨を確認](https://raw.githubusercontent.com/jldbc/pybaseball/master/README.md)
- 確認資料: [MLB・NCAA・FanGraphs・Retrosheet等の取得機能と配布先を確認](https://raw.githubusercontent.com/BillPetti/baseballr/master/README.md)

## S018

**Baseball-Reference：年度成績・試合記録** — 歴史的な選手・球団成績、試合ログ、リーグ別情報の探索。

- 提供元グループ: `sports_reference` / 種類: `portal` / 対象: MLB・NPB・KBO・その他
- 入口: https://www.baseball-reference.com/
- 収録範囲: リーグ・項目ごとに収録期間が異なり、個別に確認が必要。
- 取得方法・形式: 公式閲覧・エクスポート条件を確認。自動取得は提供者の許可範囲で判断。 / HTML・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 http_error / 本体サンプル未取得
- 結合キー候補: bbref ID・team ID・year
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 自動取得制限・有料Statheadとの違い・二次配布条件を確認。 / 初回の入口確認は http_error / HTTP 403。データの入手可能性は未確定。
- 確認資料: [投球・打席・集計・日程の取得機能と、過去のStatcastにも改訂がある旨を確認](https://raw.githubusercontent.com/jldbc/pybaseball/master/README.md)
- 確認資料: [MLB・NCAA・FanGraphs・Retrosheet等の取得機能と配布先を確認](https://raw.githubusercontent.com/BillPetti/baseballr/master/README.md)

## S019

**SportsDataverse：NCAA試合・プレー記録** — NCAAの日程・PBP・ロスター等を加工して公開するデータパイプライン。

- 提供元グループ: `sportsdataverse` / 種類: `dataset` / 対象: NCAA
- 入口: https://github.com/sportsdataverse/baseballr-data
- 収録範囲: 資料に2024–2026年等の取得キャンペーン例があるが、公開済み年度はRelease一覧で別途検証する。
- 取得方法・形式: sportsdataverse-dataのReleaseメタデータを先に確認し、必要な年だけ取得。 / Parquet・CSV・RDS
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: NCAA game ID・team ID・season
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: NCAA一次資料の条件・加工定義・公開データの年度別実在を確認。 / 原サイトの制限を回避するために配布物を使うのではなく、正当な配布条件を確認して利用。
- 確認資料: [NCAAの配布先、MLB rawの別リポジトリ、巨大cloneを避ける手順を確認](https://raw.githubusercontent.com/sportsdataverse/baseballr-data/HEAD/README.md)
- 確認資料: [MLB・NCAA・FanGraphs・Retrosheet等の取得機能と配布先を確認](https://raw.githubusercontent.com/BillPetti/baseballr/master/README.md)

## S020

**SportsDataverse：配布ファイル・更新状況** — 各データセットのRelease・ファイル形式・更新対象を探索する配布台帳。

- 提供元グループ: `sportsdataverse` / 種類: `portal` / 対象: MLB・NCAA
- 入口: https://github.com/sportsdataverse/sportsdataverse-data/releases
- 収録範囲: タグ・資産ごとに異なる。READMEの大きさと実際の収録量を区別する。
- 取得方法・形式: 配布一覧・manifestだけを先に確認。 / Release metadata
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: release tag・asset name・version
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 同じ配布物の表形式違いを独立した原データと数えない。
- 確認資料: [NCAAの配布先、MLB rawの別リポジトリ、巨大cloneを避ける手順を確認](https://raw.githubusercontent.com/sportsdataverse/baseballr-data/HEAD/README.md)
- 確認資料: [MLB・NCAA・FanGraphs・Retrosheet等の取得機能と配布先を確認](https://raw.githubusercontent.com/BillPetti/baseballr/master/README.md)

## S123

**Seamheads Negro Leagues Database** — 歴史的な選手・チーム・試合・成績の参照候補。

- 提供元グループ: `seamheads` / 種類: `portal` / 対象: 歴史的Negro Leagues
- 入口: https://www.seamheads.com/NegroLgs/
- 収録範囲: 公式ページに歴史的な黒人プロ野球、交流試合、ラテンアメリカでの競技等の範囲を説明。収録表の完了率・版は未確認。
- 取得方法・形式: 公式資料・配布・API・契約条件を調査する。第1段階ではデータ本体は取得しない。 / HTML候補
- 料金・認証: 料金・認証・保存・再配布範囲は未確認。
- 条件: unknown（needs_review）。公開された案内と実際のデータ利用許可を分けて確認する。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 公式の提供範囲・出典・利用条件を確認して、必要なら第2段階候補に追加する。
- 注意点: 史料の欠損・推計・改訂と、MLB公式集計への統合方針の違いを確認。
- 確認資料: [Seamheadsの歴史的黒人野球統計と、リーグ戦・交流試合・ラテンアメリカ等の範囲の説明を確認。](https://www.seamheads.com/NegroLgs/)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。
