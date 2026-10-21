# 公開アーカイブ・補助データ

[台帳トップへ](README.md)

| ID | 候補 | 優先度 | 資料 | 入口接続 |
|---|---|---|---|---|
| [S114](#s114) | Baseball Hack Day：資料探索の旧Wiki | C | 資料確認済み | reachable |
| [S115](#s115) | Rdatasets：Lahman等の配布・項目説明 | B | 資料確認済み | reachable |
| [S116](#s116) | MLB-YouTube：野球映像の研究データ候補 | C | 資料確認済み | reachable |
| [S117](#s117) | BaseballCV：公開データセットへの入口 | C | 資料確認済み | reachable |
| [S118](#s118) | Analyzing Baseball Data with R：教材・例示データ | C | 資料確認済み | reachable |
| [S124](#s124) | Baseball Almanac | C | 一次資料未確認 | reachable |
| [S125](#s125) | SABR BioProject | C | 資料確認済み | reachable |

## S114

**Baseball Hack Day：資料探索の旧Wiki** — データ・参考資料へのリンクをたどる歴史的なリソース集候補。

- 提供元グループ: `baseball_hackday` / 種類: `research_index` / 対象: 横断
- 入口: https://github.com/baseballhackday/data-and-resources
- 収録範囲: READMEは短く、旧Wikiへの案内がある。現在のリンク先の内容・保守状況は再確認が必要。
- 取得方法・形式: リンクの実在と現在の公式配布先を確認。 / Markdown・wiki
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 古いリンク・閉鎖・改訂に注意。
- 確認資料: [旧Wikiへの案内を確認。WikiのHTTP 200だけでは本文の実在を確認できない](https://raw.githubusercontent.com/baseballhackday/data-and-resources/HEAD/README.md)

## S115

**Rdatasets：Lahman等の配布・項目説明** — RデータセットのCSVと説明を参照できる二次配布候補。

- 提供元グループ: `rdatasets` / 種類: `dataset` / 対象: MLB
- 入口: https://github.com/vincentarelbundock/Rdatasets
- 収録範囲: 元パッケージの特定版に依存。最新版や全表の収録を保証しない。
- 取得方法・形式: 元Lahmanと版・列・件数・条件を照合。 / CSV・HTML
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: playerID・yearID・stint
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: Rdatasets側の配布条件と元データの条件を分離。 / Lahmanの別配布を独立した観測データと数えない。
- 確認資料: [Battingの列定義がある資料を確認](https://raw.githubusercontent.com/vincentarelbundock/Rdatasets/master/doc/Lahman/Batting.html)

## S116

**MLB-YouTube：野球映像の研究データ候補** — プレー動作認識の研究で使われる映像・ラベルの候補。

- 提供元グループ: `mlb_youtube` / 種類: `dataset` / 対象: MLB映像
- 入口: https://github.com/piergiaj/mlb-youtube
- 収録範囲: READMEは2017年MLBポストシーズン20試合、4290の分割クリップ等を説明。現在の配布・映像リンクの稼働は未確認。
- 取得方法・形式: ラベル・論文・映像配布の所在と権利を先に確認する。 / video・labels候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 映像・放送権とラベルの条件を別に確認。大容量映像は第1段階では取得しない。
- 確認資料: [2017年ポストシーズン20試合、映像区間ラベル等の説明を確認。映像は未取得。](https://raw.githubusercontent.com/piergiaj/mlb-youtube/HEAD/README.md)

## S117

**BaseballCV：公開データセットへの入口** — 野球のコンピュータビジョン用ツール・関連データ探索の候補。

- 提供元グループ: `baseballcv` / 種類: `portal` / 対象: 野球映像
- 入口: https://github.com/BaseballCV/BaseballCV
- 収録範囲: リポジトリ・dataset cardの記載を次に確認。
- 取得方法・形式: 実在するデータセットを個別に識別して元出典を確認。 / 画像・video・labels候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: ツール自体のライセンスを画像・映像・モデルの条件に適用しない。
- 確認資料: [公開データ・モデルを扱うCVプロジェクトの説明を確認。素材ごとの利用条件は別。](https://raw.githubusercontent.com/BaseballCV/BaseballCV/HEAD/README.md)

## S118

**Analyzing Baseball Data with R：教材・例示データ** — 得点期待値・モデル検証・集計処理の参考になる教材候補。

- 提供元グループ: `baseball_with_r` / 種類: `reference` / 対象: MLB分析
- 入口: https://github.com/maxtoki/baseball_R
- 収録範囲: 書籍に対応する例示データ。対象年・元出典は項目ごとに確認。
- 取得方法・形式: 教材のコードと元データへの参照を分けて確認。 / R・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 小さい教材データをリーグ全体の代表標本として扱わない。
- 確認資料: [書籍に対応する教材リポジトリの説明を確認](https://raw.githubusercontent.com/maxtoki/baseball_R/HEAD/README.md)

## S124

**Baseball Almanac** — 歴史的記録・選手・球場・記念記録の参照候補。

- 提供元グループ: `baseball_almanac` / 種類: `portal` / 対象: MLB・野球史
- 入口: https://www.baseball-almanac.com/
- 収録範囲: 項目・契約・年度により異なる。一次資料を直接読めておらず未確認。
- 取得方法・形式: 公式資料・配布・API・契約条件を調査する。第1段階ではデータ本体は取得しない。 / HTML候補
- 料金・認証: 料金・認証・保存・再配布範囲は未確認。
- 条件: unknown（needs_review）。公開された案内と実際のデータ利用許可を分けて確認する。
- 状態: 一次資料未確認 / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 公式の提供範囲・出典・利用条件を確認して、必要なら第2段階候補に追加する。
- 注意点: 項目ごとの原出典と転載条件を確認。 / 本文調査ではHTTP 403。接続チェックの一回の成功を継続取得可能と扱わない。
- 別途の本文確認: HTTP 403。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S125

**SABR BioProject** — 選手・監督・関係者の経歴と原資料の探索候補。

- 提供元グループ: `sabr` / 種類: `portal` / 対象: 野球史
- 入口: https://sabr.org/bioproj/
- 収録範囲: 項目・契約・年度により異なる。一次資料を直接読めておらず未確認。
- 取得方法・形式: 公式資料・配布・API・契約条件を調査する。第1段階ではデータ本体は取得しない。 / HTML・参考文献
- 料金・認証: 料金・認証・保存・再配布範囲は未確認。
- 条件: unknown（needs_review）。公開された案内と実際のデータ利用許可を分けて確認する。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 公式の提供範囲・出典・利用条件を確認して、必要なら第2段階候補に追加する。
- 注意点: 人物紹介の全文を自由に転載できるとは扱わない。出典のある事実と著者の記述を分離。
- 確認資料: [SABRの伝記プロジェクトと参考資料・利用条件への導線を確認。](https://sabr.org/bioproj/)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。
