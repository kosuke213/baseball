# データの出典・利用条件・加工表示

この文書は今回の共通DB・CSVに付随する表示です。各提供元が本プロジェクトを推奨していることを示すものではありません。コードの利用条件とデータの利用条件は別です。原本の取得日時・SHA256・確認資料の指紋は `manifest.json` にあります。

## Retrosheet（S012 / S013）

**The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.**

**The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".**

https://www.retrosheet.org/notice.txt / https://www.retrosheet.org/gamelogs/index.html / https://www.retrosheet.org/downloads/plays.html

Game Logsおよび公式parsed playsを使用。CSVの解析、原列のJSON/SQLite化、Game Logsのgame_id付加、2023〜2025年のレギュラーシーズン全件の抽出・型付け・整合性集計、公式parkcode表の参照を実施しました。Retrosheetによる記録・復元や改訂の性質は保持します。

## Chadwick Baseball Bureau Persons Register（S021）

Contains information from the **Chadwick Baseball Bureau Persons Register**, https://github.com/chadwickbureau/register, made available under the **Open Data Commons Attribution License v1.0**: https://opendatacommons.org/licenses/by/1-0/ .

取得版：`781c175e748b89e5730fd3f5de0086b9355b2f92`。16分割の公開people表を走査し、収録試合の打者・投手・走者・試合ログ内のIDに一致した人物と、NPB IDを持つ公開人物行を抽出、JSON/SQLiteへ加工しました。氏名による対応推測はしていません。元のREADMEの利用条件を原本バックアップにも保存しています。

## Japan Prospect Lab（S034）

Copyright (c) 2026 **Japan Prospect Lab**. **CC BY 4.0** — https://creativecommons.org/licenses/by/4.0/ .

指定帰属先：https://japanprospectlab.substack.com / https://github.com/japanprospectlab/data . README本文では別のSubstack綴りも案内されますが、この表示にはLICENSE本文の指定を採用しました。

取得版：`cd0f9a0ec39db786fdad20815a0b5f91f8466b12`。2026 NPB Draft BoardのCSVをJSON/SQLite化。評価・数値・注記は原文のままです。著者によるスカウティング評価を公式成績や真の能力と扱いません。元LICENSEおよびMETHODOLOGYを原本バックアップにも保持しています。

## 気象庁（S075）

**出典：気象庁「過去の気象データ検索」東京・2024年3月29日（１時間ごとの値）。当プロジェクトがHTMLを表に加工し、JST/UTC時刻を付加。**

対象：https://www.data.jma.go.jp/stats/etrn/view/hourly_s1.php?prec_no=44&block_no=47662&year=2024&month=3&day=29&view=

適用条件：https://www.jma.go.jp/jma/kishou/info/coment.html （公共データ利用規約 第1.0版と気象庁の例外・適用条件）。

観測所47662の公開数値表部分を使用。元のセル文字列・単位・品質記号・HTMLセル属性を残し、JSON/SQLite/CSVへ変換しました。空欄、`--` などを一律に0へ置換していません。球場内の観測ではありません。

## 第5段階の追加と加工

Retrosheet：1996・2006・2016・2019・2022年のGame Logsを追加。成績・試合情報の型付け、年度別集計、原本保存を実施。過去年のプレーやセンサー値は復元していません。Chadwickは同じ固定版から歴史年度の参照IDを追加しました。

以下の3資料は各Zenodoレコードに明記された **Creative Commons Attribution 4.0 International**（https://creativecommons.org/licenses/by/4.0/ ）で提供されています。著者の推奨・公認を示しません。原本、取得時点のライセンス表示を含むメタデータ、出典行参照をZIP内に保存しています。

- **JyhHow Huang**. *Adult male baseball pitchers anthropometric measurements and pitching velocity in tryout settings*. https://doi.org/10.5281/zenodo.5796004 . `baseball__Dataset.csv`。CSVを型付きSQLite/CSVへ変換。単位不明のため推測変換なし。原本56人と説明文64人の差を明示。
- **Wada, Naoki**. *Inter-pitcher and Intra-pitcher Comparisons on the Relationship between Trunk Kinematics and Ball Speed in Collegiate Baseball Pitchers*. https://doi.org/10.5281/zenodo.17502529 . `Tables (Wada et al.).docx` の3表。セルを抽出して平均・SD・相関・投球周期を区別、節見出しの単位を付与。図ファイルPPTXは未取得。個別投球の作成なし。
- **Murdock, Alanna**. *COMPARISON OF BIOMECHANICAL PARAMETERS AND IN-SPORT ANALYTICS IN BASEBALL HITTERS*. https://doi.org/10.5281/zenodo.16050919 . `55 2025-07-28 Murdock Thesis FINAL.pdf`。原著実験のTable 1（本文10ページ、PDF14ページ）12行を転記し、PDF画像と照合。平均・SD・Nを保存、km/hの速度のみm/sへ換算。論文中で引用されたMLB集計値は抽出対象外。原本SHA256と転記内容は `murdock_table1.json`。

DBは出典ごとの利用条件が併存します。第5段階では元資料の列・数値を保存し、加工した資料であることを表示しています。その他の著作物をCC BYへ再許諾するものではありません。
