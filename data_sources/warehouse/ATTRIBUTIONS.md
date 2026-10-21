# データの出典・利用条件・加工表示

この文書は今回の共通DB・CSVに付随する表示です。各提供元が本プロジェクトを推奨していることを示すものではありません。コードの利用条件とデータの利用条件は別です。原本の取得日時・SHA256・確認資料の指紋は `manifest.json` にあります。

## Retrosheet（S012 / S013）

**The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.**

**The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".**

https://www.retrosheet.org/notice.txt / https://www.retrosheet.org/gamelogs/index.html / https://www.retrosheet.org/downloads/plays.html

Game Logsおよび公式parsed playsを使用。CSVの解析、原列のJSON/SQLite化、Game Logsのgame_id付加、2023〜2025年のレギュラーシーズン全件の抽出・型付け・整合性集計、公式parkcode表の参照を実施しました。Retrosheetによる記録・復元や改訂の性質は保持します。

## Chadwick Baseball Bureau Persons Register（S021）

Contains information from the **Chadwick Baseball Bureau Persons Register**, https://github.com/chadwickbureau/register, made available under the **Open Data Commons Attribution License v1.0**: https://opendatacommons.org/licenses/by/1-0/ .

取得版：`781c175e748b89e5730fd3f5de0086b9355b2f92`。16分割の公開people表を走査し、収録試合の打者・投手・走者・試合ログ内のIDに一致した人物と、NPB IDを持つ公開人物行を抽出、JSON/SQLiteへ加工しました。氏名による対応推測はしていません。元のREADMEの利用条件を原本キャッシュに保存しています。

## Japan Prospect Lab（S034）

Copyright (c) 2026 **Japan Prospect Lab**. **CC BY 4.0** — https://creativecommons.org/licenses/by/4.0/ .

指定帰属先：https://japanprospectlab.substack.com / https://github.com/japanprospectlab/data . README本文では別のSubstack綴りも案内されますが、この表示にはLICENSE本文の指定を採用しました。

取得版：`cd0f9a0ec39db786fdad20815a0b5f91f8466b12`。2026 NPB Draft BoardのCSVをJSON/SQLite化。評価・数値・注記は原文のままです。著者によるスカウティング評価を公式成績や真の能力と扱いません。元LICENSEおよびMETHODOLOGYを原本キャッシュに保持しています。

## 気象庁（S075）

**出典：気象庁「過去の気象データ検索」東京・2024年3月29日（１時間ごとの値）。当プロジェクトがHTMLを表に加工し、JST/UTC時刻を付加。**

対象：https://www.data.jma.go.jp/stats/etrn/view/hourly_s1.php?prec_no=44&block_no=47662&year=2024&month=3&day=29&view=

適用条件：https://www.jma.go.jp/jma/kishou/info/coment.html （公共データ利用規約 第1.0版と気象庁の例外・適用条件）。

観測所47662の公開数値表部分を使用。元のセル文字列・単位・品質記号・HTMLセル属性を残し、JSON/SQLite/CSVへ変換しました。空欄、`--` などを一律に0へ置換していません。球場内の観測ではありません。
