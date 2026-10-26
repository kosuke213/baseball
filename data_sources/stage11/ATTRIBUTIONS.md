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

## 第9段階

第8段階までの原本・利用条件・出典を継承。新しいプレーデータ取得は0件。2023〜2024年だけを推定・経路学習に使用し、2025年は既知の参考期間です。原本670窓の抜粋行と既存出典ID・行番号・ZIP SHA256を監査に含めます。

MLB 2025 Official Baseball Rulesの5.08（得点・終了）、9.02（成績）、9.04（打点）、9.06（安打価値）、9.16（失点責任）、9.17（勝敗）を参照します。PDFのSHA256は `d1860de43bf3877177ed463a4b4145da51ee83f9d358ae93bdab4a9c67a55fe0`、URLは `https://mktg.mlbstatic.com/mlb/official-information/2025-official-baseball-rules.pdf`。参照用PDF全体の再配布はしません。NPB独自の記録・運用の認定には使用していません。

## 第10段階の追加説明

既存Retrosheet原本と第5〜9段階の出典条件を継承し、新しいプレーデータの取得は0件。対象を限定して既存原本行を読み直します。生成した順序・走塁死・事後分布はRetrosheetの実測時刻・観測経路として扱いません。

MLB OBR 2025の5.08(a)(b)、9.04(a)(b)、9.06(f)(g)、9.02(c)、9.16(g)、9.17を参照。公式PDFは前段階と同じSHA256で照合し、全文を再配布しません。NPBの独自運用を同一と認定するものではありません。

## 第11段階

基礎打席確率・経路・規則は第7・9・10段階を継承します。新しい実プレーデータの収集・医学モデル学習・NPB個人成績による能力推定はありません。架空の氏名、生年月日、能力・才能・健康・成長は生成したゲームデータで、実在の同名人物とは関係ありません。

NPBの公式公示の区分を参考として閲覧しました（https://npb.jp/announcement/2025/pn_registered.html）。ページ全文や選手一覧は再配布せず、モデルへの学習入力にも使いません。登録抹消を故障診断とはみなしません。登録制度、支配下・育成等の正式枠は未実装で、60人編成は検証用の独自設定です。参照情報の指紋はreferences.jsonに記録します。

研究用の固定シードは再現用です。個人の真値・潜在才能を含む管理者DBと真値曲線は公開ZIPへ入れません。公開選手データは誤差付き評価・公開状態・確定成績だけです。年齢別の内部能力集計は匿名研究集団の統計です。
