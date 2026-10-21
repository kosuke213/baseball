# 収集先の台帳データ

まず [分類別の閲覧ページ](../docs/data-sources/README.md) と [調査結果](../docs/data-sources/findings.md) を開いてください。台帳は実際に取得・学習できたデータの一覧ではなく、取得候補と確認状況の一覧です。

- `catalog.json`: 編集元。出典・範囲・取得方法・利用条件・根拠・次の確認を記録。
- `sources.csv`: Excelで開くためのUTF-8 BOM付き一覧。
- `link_checks.json`: 軽量な接続確認の記録。本文確認の成否はcatalogのportal_reviewにも記録。
- `summary.json`: 件数・状態・分類の集計。
- `discovery_queries.json`: 公開リポジトリ探索の検索語・結果。
- `url_corrections.json`: 404等から取得入口を修正した履歴。
- `network_requirements.json`: 調査対象の接続先と設定下書きに追加したドメイン。
- `catalog.sqlite3`: buildで生成する台帳用DB。Git管理から除外。

```bash
python scripts/catalog.py validate
python scripts/catalog.py build
```

SQLiteの例（ファイルを編集せず、Python標準ライブラリから確認）:

```python
import sqlite3

with sqlite3.connect("data_sources/catalog.sqlite3") as connection:
    for row in connection.execute(
        "SELECT id, name, review_status FROM sources WHERE priority = ?", ("A",)
    ):
        print(row)
```

台帳自体には本体データ・第三者のページ全文・資格情報を含めていません。[pilot/](pilot/README.md) と [warehouse/](warehouse/README.md) は、確認した条件に基づく加工済みDBと検査結果の別成果物です。公開ページの入口の成功と、データ取得・条件確認の完了を区別して利用してください。
