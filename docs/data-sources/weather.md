# 天候・環境

[台帳トップへ](README.md)

| ID | 候補 | 優先度 | 資料 | 入口接続 |
|---|---|---|---|---|
| [S071](#s071) | Open-Meteo：過去気象 | A | 資料確認済み | reachable |
| [S072](#s072) | Meteostat：観測所の過去気象 | A | 資料確認済み | reachable |
| [S073](#s073) | NOAA GHCN-Daily | B | 資料確認済み | reachable |
| [S074](#s074) | NOAA Integrated Surface Database | B | 資料確認済み | reachable |
| [S075](#s075) | 気象庁：過去の気象データ | A | 資料確認済み | reachable |
| [S076](#s076) | ERA5：再解析データの原提供元 | C | 資料確認済み | reachable |

## S071

**Open-Meteo：過去気象** — 球場時刻・位置に合わせる気温・風・湿度・降水等の再解析データ候補。

- 提供元グループ: `open_meteo` / 種類: `dataset` / 対象: 全世界
- 入口: https://open-meteo.com/en/docs/historical-weather-api
- 収録範囲: 公式説明は過去再解析を1940年以降と案内。ERA5/ERA5-Land/IFS等で期間・解像度が異なる。変数別・球場時刻の本体は未取得。
- 取得方法・形式: APIのモデル、時間解像度、タイムゾーン、現行サービス条件を確認。 / JSON・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: CC BY 4.0（README記載）（mixed）。READMEはAPIの非商用・商用利用条件を別に記載。提供サービスの現行料金・条件と元再解析データの条件を再確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 緯度・経度・UTC時刻・モデル版
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 再解析値と球場内の実測値は別。屋内球場は別処理。 / データCC BYとAPIサービスの商用・料金条件を区別。
- 確認資料: [データCC BY 4.0と、APIの非商用・商用利用条件が別である旨を確認](https://raw.githubusercontent.com/open-meteo/open-meteo/main/README.md)
- 確認資料: [過去気象・再解析モデルの説明を確認。観測値そのものと扱わない。](https://open-meteo.com/en/docs/historical-weather-api)

## S072

**Meteostat：観測所の過去気象** — 時別・日別観測と観測所メタデータの候補。

- 提供元グループ: `meteostat` / 種類: `dataset` / 対象: 全世界
- 入口: https://dev.meteostat.net/
- 収録範囲: 観測所・変数・元提供者によって収録期間が異なる。
- 取得方法・形式: 観測所・時別・日別の配布と、推定値混入・元提供者を確認。 / CSV・JSON・Python
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: CC BY 4.0（Meteostat再配布データ）（mixed）。Meteostatと元提供者への帰属を保持。Pythonから直接元気象サービスを読む場合はその提供者の条件を別確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: station ID・UTC時刻・緯度経度
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 最寄り観測所と球場内の風は一致しない。 / 欠測補間・モデル値・観測値の識別を確認。
- 確認資料: [観測気象データと、一般にCC BY 4.0という記載を確認。元観測所・個別条件は別途確認](https://raw.githubusercontent.com/meteostat/meteostat/HEAD/README.md)
- 確認資料: [再配布データのCC BY 4.0と、Pythonから直接元サービスへ取得する場合の条件の違いを確認。](https://dev.meteostat.net/license)

## S073

**NOAA GHCN-Daily** — 日別観測・気温・降水等と観測所の長期記録。

- 提供元グループ: `noaa` / 種類: `dataset` / 対象: 全世界
- 入口: https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily
- 収録範囲: 観測所ごとの開始年・項目・欠損が異なる。
- 取得方法・形式: 公式仕様・品質フラグ・観測所履歴・配布形式を確認。 / CSV・text
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: station ID・UTC時刻
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 古いrnoaaクライアントは更新・互換性の問題がREADMEにあるため、そのまま採用しない。 / 気象観測の品質フラグを捨てない。
- 確認資料: [NOAAのGHCN-Daily製品説明・メタデータ・取得先への案内を確認。本体は未取得。](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S074

**NOAA Integrated Surface Database** — 時刻別・総観観測により試合時刻と結合する候補。

- 提供元グループ: `noaa` / 種類: `dataset` / 対象: 全世界
- 入口: https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database
- 収録範囲: 観測所ごとの開始年・項目・欠損が異なる。
- 取得方法・形式: 公式仕様・品質フラグ・観測所履歴・配布形式を確認。 / CSV・text
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: station ID・UTC時刻
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 古いrnoaaクライアントは更新・互換性の問題がREADMEにあるため、そのまま採用しない。 / 気象観測の品質フラグを捨てない。
- 確認資料: [NOAAのGlobal Hourly/ISD製品説明と取得資料への案内を確認。本体は未取得。](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S075

**気象庁：過去の気象データ** — 日本の球場に対応する観測地点の過去気象候補。

- 提供元グループ: `jma` / 種類: `dataset` / 対象: 日本
- 入口: https://www.data.jma.go.jp/stats/etrn/
- 収録範囲: 観測地点・項目・時間単位によって異なる。
- 取得方法・形式: 公式のデータダウンロード・利用規約・品質情報を確認。 / HTML・CSV候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: 公共データ利用規約 第1.0版（気象庁の適用条件付き）（documented）。出典と加工の表示が必要。別の権利表示・第三者権利・個別法令等の例外を確認。対象の過去観測データへの適用を第2段階前に確認する。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 観測所番号・日本標準時・観測日
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 品質記号、観測地点移転、風向・風速の観測高さを確認。 / 球場内の天候は周辺観測地点と一致しない。
- 確認資料: [公共データ利用規約第1.0版、出典・加工表示、別表示や第三者権利等の例外を確認。](https://www.jma.go.jp/jma/kishou/info/coment.html)
- 確認資料: [観測地点・日付・時間単位による過去気象検索の入口を確認。](https://www.data.jma.go.jp/stats/etrn/)

## S076

**ERA5：再解析データの原提供元** — 再解析のモデル・変数・時間解像度の原仕様を確認する候補。

- 提供元グループ: `ecmwf_copernicus` / 種類: `reference` / 対象: 全世界
- 入口: https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels
- 収録範囲: 公式製品ページは1940年以降の時別ERA5を案内。実際の変数・取得範囲は別途確認。
- 取得方法・形式: カタログ・ライセンス・取得量・認証要否を調査。 / GRIB・NetCDF候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 格子・UTC時刻・変数・版
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 全世界・長期間の丸ごと取得は大容量。球場周辺・必要な変数へ絞る段階は第2段階以降。
- 確認資料: [公式CDSのERA5単一面・時別データの製品説明と1940年以降の案内を確認。](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。
