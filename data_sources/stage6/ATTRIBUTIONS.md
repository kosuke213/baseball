# 出典・加工表示

**The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".**

**The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.**

対象：Retrosheet 2023・2024・2025年レギュラーシーズンの公式parsed plays、照合済みGame Logs。https://www.retrosheet.org/downloads/plays.html / https://www.retrosheet.org/gamelogs/ / https://www.retrosheet.org/notice.txt

加工：第5段階の固定DBと取得済み年別原本を読み取り、PA指標による14分類、非プレーの分離、観測された打席の窓の組立て、24状態＋半イニング終了の遷移・得点集計、確率表の平滑化と年度分割評価を実施。確率は本プロジェクトによる推定で、Retrosheetによる保証や推奨ではありません。個々の実測投球や実測打球の物理モデルではありません。

人物ID対応の監査には、Chadwick Baseball Bureau Persons Registerの固定版 `781c175e748b89e5730fd3f5de0086b9355b2f92` を含む既存DBを参照しました。Contains information from the **Chadwick Baseball Bureau Persons Register**, https://github.com/chadwickbureau/register, made available under the **Open Data Commons Attribution License v1.0**: https://opendatacommons.org/licenses/by/1-0/ . 人物の将来の経歴・生年月日等は予測入力に使用していません。

取得原本・ライセンス確認資料は第5段階の [全取得原本ZIP](https://raw.githubusercontent.com/kosuke213/baseball/codex/stage5-tracking/data_sources/stage5/originals_bundle.zip) に保存済みです。第6段階は新しい収集を行っていません。SHA256・原本URL・取得日時は `manifest.json`、変換後の各プレー・窓の出典行は同梱 `observations.sqlite3` の `plays`・`windows` から追跡できます。
