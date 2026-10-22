# 出典と利用条件

今回のプレーデータは第5〜7段階で保存済みのRetrosheet原本です。新規の大量収集や第三者データの取得はありません。原本URL、SHA256、取得日時、利用条件のスナップショットを `source_audit.json` の `raw_artifacts` に保持しています。

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".

- 原本・定義：https://www.retrosheet.org/downloads/plays.html 、https://www.retrosheet.org/notice.htm
- 継承したモデル・ID管理の出典は同梱 `stage7_model/ATTRIBUTIONS.md` と、第5〜7段階の各manifestを参照してください。過去のID対応表を変更していません。

ルール定義の確認にはMLB Official Baseball Rules 2025の5.08、9.02、9.04〜9.06、9.16(g)、9.17を参照しました。条文の意味を実装し、PDF本文の再配布はしません。

- 公式入口：https://www.mlb.com/official-information
- 参照PDF：https://mktg.mlbstatic.com/mlb/official-information/2025-official-baseball-rules.pdf
- 参照日：2026-10-22（日本時間）
- 参照したPDFのSHA256：`d1860de43bf3877177ed463a4b4145da51ee83f9d358ae93bdab4a9c67a55fe0`

2025版MLB規則の参照を、将来のNPBリーグの規則が同一であるという根拠にはしません。延長・引き分けは実験設定として明示します。モデルに球速・回転・打球角度の推測値を補っていません。
