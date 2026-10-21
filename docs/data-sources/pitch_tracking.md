# 投球・打球・守備計測

[台帳トップへ](README.md)

| ID | 候補 | 優先度 | 資料 | 入口接続 |
|---|---|---|---|---|
| [S001](#s001) | Baseball Savant：投球・打球のStatcast CSV | A | 資料確認済み | reachable |
| [S002](#s002) | MLB Stats API：試合のlive feed | A | 資料確認済み | reachable |
| [S003](#s003) | SportsDataverse：MLB raw収録一覧 | A | 資料確認済み | reachable |
| [S004](#s004) | Baseball Savant：バットトラッキング | B | 資料確認済み | reachable |
| [S005](#s005) | Baseball Savant：Sprint Speed | B | 資料確認済み | reachable |
| [S006](#s006) | Baseball Savant：Outs Above Average | B | 資料確認済み | reachable |
| [S007](#s007) | Baseball Savant：捕手フレーミング | B | 資料確認済み | reachable |
| [S008](#s008) | Baseball Savant：捕手送球・Pop Time | B | 資料確認済み | reachable |
| [S009](#s009) | Baseball Savant：球場係数 | B | 資料確認済み | reachable |
| [S010](#s010) | Baseball Savant：送球速度・Arm Strength | B | 資料確認済み | reachable |
| [S011](#s011) | Baseball Savant：投球の変化量 | B | 資料確認済み | reachable |
| [S119](#s119) | Brooks Baseball | C | 資料確認済み | reachable |
| [S120](#s120) | Sportradar MLB API | C | 資料確認済み | reachable |
| [S121](#s121) | SportsDataIO MLB API | C | 資料確認済み | reachable |
| [S122](#s122) | Stats Perform / Opta | C | 資料確認済み | reachable |
| [S127](#s127) | Baseball Savant：Minor League Statcast | B | 資料確認済み | reachable |
| [S128](#s128) | Baseball Savant：World Baseball Classic Statcast | B | 資料確認済み | reachable |

## S001

**Baseball Savant：投球・打球のStatcast CSV** — 一球ごとの球種・球速・位置・カウント・投打・結果・打球計測。

- 提供元グループ: `mlb` / 種類: `dataset` / 対象: MLB
- 入口: https://baseballsavant.mlb.com/statcast_search
- 収録範囲: 公式列定義は2008–16年の球速をPitchFX、2017年以降をStatcastと説明。打球系の利用可能年は項目ごとに異なる。2026年にプレート位置・ゾーン定義が変わる項目がある。
- 取得方法・形式: 公式検索のCSV候補。pybaseballで日付を小分けに取得する方法が文書化。 / CSV
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: game_pk・at_bat_number・pitch_number・batter・pitcher
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 初期の投球追跡と2015年以降のStatcastを同一測定方式と扱わない。 / 測定機器・項目定義の年度差、過年度修正、短縮試合・欠損を確認。 / 2026年のplate_x/plate_zとsz_top/sz_bot等の定義変更を保持。補正済み球速でも測定機器差を無視しない。
- 確認資料: [投球・打席・集計・日程の取得機能と、過去のStatcastにも改訂がある旨を確認](https://raw.githubusercontent.com/jldbc/pybaseball/master/README.md)
- 確認資料: [投球単位のDataFrame、日付分割、2015年以降の打球関連項目に関する説明を確認](https://raw.githubusercontent.com/jldbc/pybaseball/master/docs/statcast.md)
- 確認資料: [公式CSV列定義を確認。2008–16年の球速、2017年以降、2026年のABS関連座標・ゾーン定義の違いを明記。](https://baseballsavant.mlb.com/csv-docs)

## S002

**MLB Stats API：試合のlive feed** — 打席・投球・走者・交代を含む試合JSONの候補。

- 提供元グループ: `mlb` / 種類: `dataset` / 対象: MLB・MiLB
- 入口: https://statsapi.mlb.com/
- 収録範囲: リーグ・年度・gamePkごとに確認が必要。入口は特定試合の候補URLで、収録期間を保証しない。
- 取得方法・形式: Stats APIの試合単位GET。MLB-StatsAPI等は補助クライアント。 / JSON
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: gamePk・atBatIndex・pitchNumber・player.id
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: APIは安定した公開契約を保証しない。 / この入口は第1段階では本文を取得せず、live feed配布元・形式の文書調査だけを行う。
- 確認資料: [MLB非公式ラッパーの説明と、データ利用条件はMLB側に従う旨を確認](https://raw.githubusercontent.com/toddrob99/MLB-StatsAPI/master/README.md)
- 確認資料: [1試合ずつのStatsAPI・Savant保存と収録一覧の説明を確認](https://raw.githubusercontent.com/sportsdataverse/baseballr-mlb-raw/HEAD/README.md)

## S003

**SportsDataverse：MLB raw収録一覧** — Stats API live feedとSavantを試合ごとに保存した二次配布の候補。

- 提供元グループ: `sportsdataverse` / 種類: `dataset` / 対象: MLB
- 入口: https://github.com/sportsdataverse/baseballr-mlb-raw
- 収録範囲: 実際に確認したindex.csvには2024年だけが記載され、両形式2472試合を収録と記載。READMEの広い説明を実在する全年度と混同しない。
- 取得方法・形式: 年別manifest→記載パス・SHA256で選択。大容量cloneは行わない。 / JSON.gz・CSV.gz・manifest CSV
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: game_pk・season・sha256
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 一次データの再配布条件と加工条件を別々に確認。 / manifestの件数は提供者メタデータで、本体を検証した件数ではない。 / READMEの容量記述と現在のmanifest実体を区別。
- 確認資料: [1試合ずつのStatsAPI・Savant保存と収録一覧の説明を確認](https://raw.githubusercontent.com/sportsdataverse/baseballr-mlb-raw/HEAD/README.md)
- 確認資料: [収録一覧だけを確認。2024年、StatsAPI/Savantそれぞれ2472試合と記載。本体は未取得](https://raw.githubusercontent.com/sportsdataverse/baseballr-mlb-raw/main/mlb/raw/manifest/index.csv)
- 確認資料: [NCAAの配布先、MLB rawの別リポジトリ、巨大cloneを避ける手順を確認](https://raw.githubusercontent.com/sportsdataverse/baseballr-data/HEAD/README.md)

## S004

**Baseball Savant：バットトラッキング** — バット速度、スイング長、接触品質の指標候補。

- 提供元グループ: `mlb` / 種類: `portal` / 対象: MLB
- 入口: https://baseballsavant.mlb.com/leaderboard/bat-tracking
- 収録範囲: 画面・指標ごとの収録年は一次資料未確認。
- 取得方法・形式: 公開leaderboardの画面・CSV機能を確認する。未確認APIは固定しない。 / HTML・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 新しい計測で対象年・対象スイング・公開範囲に制約がある。 / 入口ページ・実ファイル・利用条件を未確認。
- 確認資料: [公式のバットトラッキング画面とSavant内の検索・指標への導線を確認。CSVと本体の収録年は未検査。](https://baseballsavant.mlb.com/leaderboard/bat-tracking)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S005

**Baseball Savant：Sprint Speed** — 走塁速度、競技レベル別の走力分布候補。

- 提供元グループ: `mlb` / 種類: `portal` / 対象: MLB
- 入口: https://baseballsavant.mlb.com/leaderboard/sprint_speed
- 収録範囲: 画面・指標ごとの収録年は一次資料未確認。
- 取得方法・形式: 公開leaderboardの画面・CSV機能を確認する。未確認APIは固定しない。 / HTML・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 機会数・対象プレーの選別を確認。 / 入口ページ・実ファイル・利用条件を未確認。
- 確認資料: [公式のleaderboardページの存在・タイトルを確認。計測本体・CSV・収録年は未検査。](https://baseballsavant.mlb.com/leaderboard/sprint_speed)

## S006

**Baseball Savant：Outs Above Average** — 守備範囲・守備機会の難度補正指標候補。

- 提供元グループ: `mlb` / 種類: `portal` / 対象: MLB
- 入口: https://baseballsavant.mlb.com/leaderboard/outs_above_average
- 収録範囲: 画面・指標ごとの収録年は一次資料未確認。
- 取得方法・形式: 公開leaderboardの画面・CSV機能を確認する。未確認APIは固定しない。 / HTML・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 算出済み指標と元の守備機会を区別。 / 入口ページ・実ファイル・利用条件を未確認。
- 確認資料: [公式のleaderboardページの存在・タイトルを確認。計測本体・CSV・収録年は未検査。](https://baseballsavant.mlb.com/leaderboard/outs_above_average)

## S007

**Baseball Savant：捕手フレーミング** — 捕手によるストライク判定関連指標候補。

- 提供元グループ: `mlb` / 種類: `portal` / 対象: MLB
- 入口: https://baseballsavant.mlb.com/leaderboard/catcher-framing
- 収録範囲: 画面・指標ごとの収録年は一次資料未確認。
- 取得方法・形式: 公開leaderboardの画面・CSV機能を確認する。未確認APIは固定しない。 / HTML・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 審判・ABS等のルール差と年度による算出差を確認。 / 入口ページ・実ファイル・利用条件を未確認。
- 確認資料: [公式の捕手フレーミング画面の存在・名称・関連指標への導線を確認。個別データは未検査。](https://baseballsavant.mlb.com/leaderboard/catcher-framing)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S008

**Baseball Savant：捕手送球・Pop Time** — 捕手の送球動作、送球速度等の指標候補。

- 提供元グループ: `mlb` / 種類: `portal` / 対象: MLB
- 入口: https://baseballsavant.mlb.com/leaderboard/poptime
- 収録範囲: 画面・指標ごとの収録年は一次資料未確認。
- 取得方法・形式: 公開leaderboardの画面・CSV機能を確認する。未確認APIは固定しない。 / HTML・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 盗塁企図のある機会に偏る可能性を確認。 / 入口ページ・実ファイル・利用条件を未確認。
- 確認資料: [公式のleaderboardページの存在・タイトルを確認。計測本体・CSV・収録年は未検査。](https://baseballsavant.mlb.com/leaderboard/poptime)

## S009

**Baseball Savant：球場係数** — 球場ごとの打撃結果分布・左右別補正の候補。

- 提供元グループ: `mlb` / 種類: `portal` / 対象: MLB
- 入口: https://baseballsavant.mlb.com/leaderboard/statcast-park-factors
- 収録範囲: 画面・指標ごとの収録年は一次資料未確認。
- 取得方法・形式: 公開leaderboardの画面・CSV機能を確認する。未確認APIは固定しない。 / HTML・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 単年値と複数年値、左右・対象打球の定義を確認。 / 入口ページ・実ファイル・利用条件を未確認。
- 確認資料: [公式の球場係数画面を確認。集計条件・複数年窓・公開CSVは第2段階で確認する。](https://baseballsavant.mlb.com/leaderboard/statcast-park-factors)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S010

**Baseball Savant：送球速度・Arm Strength** — 守備位置別の送球計測指標候補。

- 提供元グループ: `mlb` / 種類: `portal` / 対象: MLB
- 入口: https://baseballsavant.mlb.com/leaderboard/arm-strength
- 収録範囲: 画面・指標ごとの収録年は一次資料未確認。
- 取得方法・形式: 公開leaderboardの画面・CSV機能を確認する。未確認APIは固定しない。 / HTML・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 対象守備位置・閾値・計測機会が選別される。 / 入口ページ・実ファイル・利用条件を未確認。
- 確認資料: [公式の送球速度画面を確認。守備位置と対象機会の閾値は第2段階で確認する。](https://baseballsavant.mlb.com/leaderboard/arm-strength)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S011

**Baseball Savant：投球の変化量** — 球種別の変化量・球速・リリースの比較候補。

- 提供元グループ: `mlb` / 種類: `portal` / 対象: MLB
- 入口: https://baseballsavant.mlb.com/leaderboard/pitch-movement
- 収録範囲: 画面・指標ごとの収録年は一次資料未確認。
- 取得方法・形式: 公開leaderboardの画面・CSV機能を確認する。未確認APIは固定しない。 / HTML・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 球種分類の変更と基準からの差・絶対値の違いを確認。 / 入口ページ・実ファイル・利用条件を未確認。
- 確認資料: [公式の投球変化量画面を確認。比較条件と実データは第2段階で確認する。](https://baseballsavant.mlb.com/leaderboard/pitch-movement)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S119

**Brooks Baseball** — 投球追跡・球種分類・投手別傾向の参照候補。

- 提供元グループ: `brooks_baseball` / 種類: `portal` / 対象: MLB
- 入口: https://www.brooksbaseball.net/
- 収録範囲: 項目・契約・年度により異なる。一次資料を直接読めておらず未確認。
- 取得方法・形式: 公式資料・配布・API・契約条件を調査する。第1段階ではデータ本体は取得しない。 / HTML・CSV候補
- 料金・認証: 料金・認証・保存・再配布範囲は未確認。
- 条件: unknown（needs_review）。公開された案内と実際のデータ利用許可を分けて確認する。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 公式の提供範囲・出典・利用条件を確認して、必要なら第2段階候補に追加する。
- 注意点: 分類・集計と元のMLB投球観測を独立した標本と数えない。
- 確認資料: [Brooks BaseballのPITCHf/xと手修正の球種分類を含む選手カードの説明を確認。](https://www.brooksbaseball.net/)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S120

**Sportradar MLB API** — 契約に基づく試合・成績等のAPI候補。

- 提供元グループ: `sportradar` / 種類: `portal` / 対象: MLB
- 入口: https://developer.sportradar.com/baseball/reference/mlb-overview
- 収録範囲: 項目・契約・年度により異なる。一次資料を直接読めておらず未確認。
- 取得方法・形式: 公式資料・配布・API・契約条件を調査する。第1段階ではデータ本体は取得しない。 / JSON・XML候補
- 料金・認証: 料金・認証・保存・再配布範囲は未確認。
- 条件: unknown（needs_review）。公開された案内と実際のデータ利用許可を分けて確認する。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 公式の提供範囲・出典・利用条件を確認して、必要なら第2段階候補に追加する。
- 注意点: 契約・試用枠・保存・学習・再配布範囲を確認。現在のキーは要求しない。
- 確認資料: [SportradarのMLB v8 API概要と試合・季節等の統計区分を確認。契約・キー・範囲は未確認。](https://developer.sportradar.com/baseball/reference/mlb-overview)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S121

**SportsDataIO MLB API** — 契約に基づく試合・選手・成績等のAPI候補。

- 提供元グループ: `sportsdataio` / 種類: `portal` / 対象: MLB
- 入口: https://sportsdata.io/developers/api-documentation/mlb
- 収録範囲: 項目・契約・年度により異なる。一次資料を直接読めておらず未確認。
- 取得方法・形式: 公式資料・配布・API・契約条件を調査する。第1段階ではデータ本体は取得しない。 / JSON候補
- 料金・認証: 料金・認証・保存・再配布範囲は未確認。
- 条件: unknown（needs_review）。公開された案内と実際のデータ利用許可を分けて確認する。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 公式の提供範囲・出典・利用条件を確認して、必要なら第2段階候補に追加する。
- 注意点: 有料・試用データと本番データの違い、契約条件を確認。
- 確認資料: [SportsDataIOのMLB向け開発者ページを確認。試用・本番・契約条件は未確認。](https://sportsdata.io/developers/api-documentation/mlb)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S122

**Stats Perform / Opta** — 商用のイベント・トラッキング等の提供可否を調べる候補。

- 提供元グループ: `stats_perform` / 種類: `portal` / 対象: MLB・その他
- 入口: https://www.statsperform.com/
- 収録範囲: 項目・契約・年度により異なる。一次資料を直接読めておらず未確認。
- 取得方法・形式: 公式資料・配布・API・契約条件を調査する。第1段階ではデータ本体は取得しない。 / 契約データ候補
- 料金・認証: 料金・認証・保存・再配布範囲は未確認。
- 条件: unknown（needs_review）。公開された案内と実際のデータ利用許可を分けて確認する。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 公式の提供範囲・出典・利用条件を確認して、必要なら第2段階候補に追加する。
- 注意点: 具体的な野球製品・対象リーグ・料金・許諾は未確認。
- 確認資料: [Opta等のデータ・API事業の案内を確認。野球固有の製品・範囲・契約は未確認。](https://www.statsperform.com/)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S127

**Baseball Savant：Minor League Statcast** — マイナーリーグの投球・打球計測を調べる公開検索入口。

- 提供元グループ: `mlb` / 種類: `portal` / 対象: MiLB
- 入口: https://baseballsavant.mlb.com/statcast-search-minors
- 収録範囲: 公式Savantのナビゲーションから発見。実収録年・試合・計測項目・欠損は未検査。
- 取得方法・形式: 専用検索画面の項目・計測期間・配布を次に確認する。 / HTML・CSV候補
- 料金・認証: MLB側の利用条件・配布・認証要否を確認する。
- 条件: unknown（needs_review）。MLB本体・マイナー・国際大会の提供・利用条件を確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: game_pk候補・選手ID候補
- 次の確認: 専用検索の公開範囲・計測機器・列定義・利用条件を確認する。
- 注意点: MLBの計測と同じ項目・精度・収録期間と仮定しない。
- 確認資料: [公式Savantのナビゲーションに専用検索へのリンクがあることを確認。](https://baseballsavant.mlb.com/leaderboard/bat-tracking)

## S128

**Baseball Savant：World Baseball Classic Statcast** — 国際大会WBCの投球・打球計測を調べる公開検索入口。

- 提供元グループ: `mlb` / 種類: `portal` / 対象: WBC
- 入口: https://baseballsavant.mlb.com/statcast-search-world-baseball-classic
- 収録範囲: 公式Savantのナビゲーションから発見。実収録年・試合・計測項目・欠損は未検査。
- 取得方法・形式: 専用検索画面の項目・計測期間・配布を次に確認する。 / HTML・CSV候補
- 料金・認証: MLB側の利用条件・配布・認証要否を確認する。
- 条件: unknown（needs_review）。MLB本体・マイナー・国際大会の提供・利用条件を確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: game_pk候補・選手ID候補
- 次の確認: 専用検索の公開範囲・計測機器・列定義・利用条件を確認する。
- 注意点: MLBの計測と同じ項目・精度・収録期間と仮定しない。
- 確認資料: [公式Savantのナビゲーションに専用検索へのリンクがあることを確認。](https://baseballsavant.mlb.com/leaderboard/bat-tracking)
