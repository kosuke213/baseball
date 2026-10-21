# 出典と加工表示

**The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".**

**The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.**

出典：https://www.retrosheet.org/downloads/plays.html / https://www.retrosheet.org/notice.txt 。第5段階までに取得・保存した2023〜2025年のparsed playsと、第6段階の派生DB・確率表を使用しました。新規データの収集はしていません。

加工：2024年内の時系列校正、14分類の校正診断、役割に基づく個別走者の進塁・得点・アウト・残塁の復元、限定ルールの検証、経路テンプレート化、同時分布の比較、半イニング試行を実施。推定値と仮定は本プロジェクトのもので、提供元の保証・推奨を示しません。

`run_b` / `run1..3` は得点者のID、`lob_id1..3` は残塁者のIDとして読みます。アウト者は進塁後・得点・残塁に含まれない参加者がアウト増分と一致した場合だけ特定します。打球後のアウトに関する守備位置コードを選手IDとは扱いません。元のルールで解釈できないケースを都合よく補完していません。

原本のURL・SHA256は `manifest.json` と `identity_audit.json`、元の全取得原本は [第5段階の原本ZIP](https://raw.githubusercontent.com/kosuke213/baseball/codex/stage5-tracking/data_sources/stage5/originals_bundle.zip) に保存されています。第6段階の人物ID対応監査は固定版Chadwick Registerを参照していますが、第7段階の予測に将来の人物経歴は使いません。Contains information from the Chadwick Baseball Bureau Persons Register, https://github.com/chadwickbureau/register, under ODC-By-1.0: https://opendatacommons.org/licenses/by/1-0/ .
