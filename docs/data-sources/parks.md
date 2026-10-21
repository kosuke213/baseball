# 球場・地理・移動

[台帳トップへ](README.md)

| ID | 候補 | 優先度 | 資料 | 入口接続 |
|---|---|---|---|---|
| [S066](#s066) | GeoJSON-Ballparks | A | 資料確認済み | reachable |
| [S067](#s067) | SportsDataverse：年度別MLB球場寸法 | A | 資料確認済み | reachable |
| [S068](#s068) | OpenStreetMap：球場形状・周辺地理 | B | 資料確認済み | reachable |
| [S069](#s069) | Geofabrik：地域別OSM抽出 | C | 資料確認済み | reachable |
| [S070](#s070) | GeoNames：地名・タイムゾーン等 | C | 資料確認済み | reachable |

## S066

**GeoJSON-Ballparks** — 450超のプロ等の球場位置をうたうGeoJSONデータ。

- 提供元グループ: `geojson_ballparks` / 種類: `dataset` / 対象: 全世界
- 入口: https://github.com/cageyjames/GeoJSON-Ballparks
- 収録範囲: READMEはリーグ別に2025年更新と古いlegacyを分離。日本を含む海外の網羅率は未確認。
- 取得方法・形式: GeoJSONと最終更新・出典を確認し、年代別の球場IDに対応。 / GeoJSON
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 球場名・経緯度・リーグ
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 球場名変更・移転・リーグ再編を追跡。 / 点座標はフィールド寸法・方向・標高を保証しない。
- 確認資料: [450超の球場点データと、リーグ別更新日の差を確認](https://raw.githubusercontent.com/cageyjames/GeoJSON-Ballparks/HEAD/README.md)

## S067

**SportsDataverse：年度別MLB球場寸法** — 球場×年度のフェンス距離、屋根、芝、容量、位置等の候補。

- 提供元グループ: `sportsdataverse` / 種類: `dataset` / 対象: MLB
- 入口: https://github.com/sportsdataverse/sdv-reference-data/blob/main/CONTRACT.md
- 収録範囲: READMEは2001–2026年と説明。CONTRACTとReleaseの実ファイルを照合する。
- 取得方法・形式: mlb_parks Release・列定義・元出典を確認。 / CSV・Parquet
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: venue ID・season
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 改修前後を年度で分ける。寸法から直接飛距離効果を断定しない。
- 確認資料: [球場寸法2001–2026、MLB組織1901–2026、NCAA組織2010–2026等の文書記載を確認](https://raw.githubusercontent.com/sportsdataverse/sdv-reference-data/HEAD/README.md)

## S068

**OpenStreetMap：球場形状・周辺地理** — 球場位置・敷地・道路・周辺地理を補完する候補。

- 提供元グループ: `openstreetmap` / 種類: `reference` / 対象: 全世界
- 入口: https://www.openstreetmap.org/
- 収録範囲: 地域・タグ・編集者による差。歴史的スナップショットは別途調査。
- 取得方法・形式: 必要な地域・施設タグだけの取得方法と、データベース利用条件を確認。 / OSM・PBF・GeoJSON候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: OSM element type・OSM ID・version
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 地図タイルの閲覧条件と地理データの利用条件を区別。 / 公開Overpassへの大量連続要求を前提にしない。
- 確認資料: [OSMの地理データ・open license・利用条件への導線を確認。個別ライセンス本文は未確認。](https://www.openstreetmap.org/)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S069

**Geofabrik：地域別OSM抽出** — 地域別の地理データ配布を使う候補。

- 提供元グループ: `geofabrik` / 種類: `portal` / 対象: 全世界
- 入口: https://download.geofabrik.de/
- 収録範囲: 地域ごとの最新版・履歴配布を確認する。
- 取得方法・形式: 配布サイズ・対象地域・ライセンスを確認。 / PBF・Shape候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: OSM ID・snapshot date
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 広域全件は大容量。球場候補の探索範囲を定めてから取得。
- 確認資料: [地域別のOSM抽出配布、元データのODbLリンク、個人編集者メタデータの扱いの説明を確認。](https://download.geofabrik.de/)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S070

**GeoNames：地名・タイムゾーン等** — 地名・経緯度・時差の補助参照元。

- 提供元グループ: `geonames` / 種類: `reference` / 対象: 全世界
- 入口: https://www.geonames.org/
- 収録範囲: 項目と配布・APIで範囲が異なる。
- 取得方法・形式: 公開dumpとAPIの認証・利用条件を確認。 / text・API候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: geonameid・経緯度
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 空港・都市の位置を球場の位置や球場内環境と混同しない。
- 確認資料: [地名データの公開入口、配布・データ出典・利用条件の案内を確認。](https://www.geonames.org/)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。
