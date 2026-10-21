# 利用するオープンソース

| コンポーネント | 用途 | ライセンス概要 / 出典 |
|---|---|---|
| NumPy | 乱数・確率モデル・分布の計算 | BSD系、同梱コンポーネントに別許諾あり / https://numpy.org/ |
| pandas | 表・統計集計・CSV | BSD-3-Clause / https://pandas.pydata.org/ |
| Streamlit | 実験UI・画面操作テスト | Apache-2.0 / https://streamlit.io/ |
| pytest | 自動テスト | MIT / https://pytest.org/ |
| SQLite / Python sqlite3 | ローカルDB / 接続 | SQLiteはpublic domain、PythonはPSF License / https://sqlite.org/ 、https://python.org/ |

推移依存の正確な固定版と配布物ハッシュは `requirements.txt` にあります。各パッケージに含まれるLICENSE/NOTICEがライセンスの正式な根拠です。サードパーティのソースコードや実在選手のデータはこのリポジトリにコピーしていません。将来の実測データはソフトウェアライセンスとは別に利用・再配布条件を確認する必要があります。

依存関係を更新する場合の生成コマンド（開発用uvが必要）:

```bash
uv pip compile requirements.in --python-version 3.11 --universal --generate-hashes --output-file requirements.txt
```

更新後は再現性に影響するNumPy版を確認し、テストと試合の統計検証を再実行してください。既存記録の閲覧に再計算は不要です。
