# 第11.5段階：NPB掲載選手の身体・投打プロフィール標本

第11段階から独立した`baseball_simulation_lab.npb_profiles`を追加します。旧プロフィール、内部能力、モデル、試合履歴、テストは変更しません。**これはNPB公式名鑑の全数・同時点調査ではありません。**

2021〜2025年の日本語Wikipedia球団年度記事に掲載された選手を枠とし、球団・守備位置・登録区分の5年の和集合から、固定シードで主名簿6人・育成2人を抽出しました。プロフィールの身体値は取得時点の掲載値で、過去年度の測定値ではありません。生年月日から各年7月1日の満年齢を計算します。

[検証報告](../../docs/data-stage11-5/README.md) · [年度／球団別範囲](coverage.csv) · [身体統計](body_statistics.csv) · [投打](handedness.csv) · [生成比較](generation_validation.json) · [架空720人CSV](https://raw.githubusercontent.com/kosuke213/baseball/refs/heads/codex/stage11-5-npb-profiles/data_sources/stage11_5/fictional_players.csv)

## 再現

Python 3.12、既存プロジェクトとテスト依存を用意し、収集／描画用の依存を追加します。

```bash
.venv/bin/python -m pip install -r data_sources/stage11_5/requirements-research.txt
.venv/bin/python -m data_collection.npb_profiles
.venv/bin/python -m baseball_simulation_lab.npb_profiles analyze
.venv/bin/python -m baseball_simulation_lab.npb_profiles validate
.venv/bin/python -m pytest -q
```

旧CIの依存・設定は変更していません。HTML収集用Beautiful Soupがない環境では、その依存を要する新規パーサー2件だけを明示してスキップします。追加の`.github/workflows/npb-profiles.yml`は研究用依存を入れ、既存・新規の全テストを実行します。本検証環境ではスキップなしの593件成功です。

収集は単一プロセス・最低2秒間隔・新規要求最大460件。HTMLとURL・取得日時・SHA256を無視対象`data/research/stage11_5/raw/`に保持し、既存原本は検証して再利用します。制限・認証・429を受けたら停止し、回避しません。画像・禁止されたAPIや検索ページは収集しません。取得時点以降のサイト編集があるため、新しい環境での再取得が同一バイトになる保証はありません。公開`parameters.json`だけで保存版の生成は再現できます。

`validate`の試合DBは新しい保存先を要求し、既存試験を上書きしません。繰り返す場合はPythonから`validation.compatibility(root=Path('/tmp/new-unused-run'))`を呼び出します。既存第11段階の完全再生には管理者用の元スナップショットが必要です。元DBを配布していないため、公開GitHubだけで過去1,716試合の内部履歴を取得できるとはしません。

## ローカルデモ

```bash
.venv/bin/python -m baseball_simulation_lab.npb_profiles demo --admin-dir data/careers/physical-demo-1 --seed 115026
```

新しい2球団世界を生成し、1試合を保存します。公開例だけを標準出力へ返し、才能や内部能力を返しません。保存先は未使用のディレクトリを指定します。運営世界で`--seed`を省略すると非公開の256bit鍵を生成します。研究用固定シードを秘密保持が必要な世界へ流用しません。

## 出力の境界

- 公開：集計、生成パラメータ、出典URL・取得日時・SHA、架空プロフィールの公開評価と身体値、検証結果、図。
- ローカルのみ：原本HTML、実在選手の結合行、個人IDの対応、キャリアの真の能力・潜在才能・ルート鍵を含むDB。
- 育成は主名簿と別集計。国籍欄の記載だけを区分に使い、NPB外国人枠資格や出身・ドラフト経路を推定しません。

[方法と限界](MODEL.md) · [出典・条件](RIGHTS.md) · [第12段階](STAGE12.md)

区分の探索的比較は`docs/data-stage11-5/scripts/compare_bins.py`、日本語レポートの再生成は`docs/data-stage11-5/scripts/write_report.py`、保存済み原本・履歴・独立環境の検証は`docs/data-stage11-5/scripts/verify.py`です。これらの詳細検証にはローカルの非公開研究成果が必要です。区分を再比較した場合は`analyze`と分布検証も実行し直し、公開済みの結果と別の版として保存してください。
