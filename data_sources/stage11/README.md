# 第11段階の起動・再構築

[実装・測定レポート](https://github.com/kosuke213/baseball/blob/codex/stage11-player-careers/docs/data-stage11/README.md) · [公開用ZIP](https://raw.githubusercontent.com/kosuke213/baseball/refs/heads/codex/stage11-player-careers/data_sources/stage11/stage11_bundle.zip)

ZIPを保存→「すべて展開」。Python 3.11以上で、展開先のターミナルから次を実行します。標準ライブラリだけで動きます。

```powershell
py -3 example.py --model-dir . --admin-db private_demo.sqlite3 --seed 110026
```

ローカルに管理者用DBを作り、2球団の選手を生成して能力付きの1試合を実行します。画面出力は公開項目だけです。同じDB・同じ指定を再実行すると保存済みの試合を再生し、上書きや再抽選をしません。`--seed`を省くと、新しい世界には非公開の256bitルート鍵を作ります。

`private_demo.sqlite3`には真の能力・潜在才能・内部履歴が入ります。公開APIの出力や公開配布物とは別です。このDBをWebの公開ファイル置場へ置かないでください。本番の認証サービスは今回作っていません。

リポジトリ：

```bash
.venv/bin/python -m baseball_simulation_lab.careers demo --admin-db data/careers/private_demo.sqlite3 --seed 110026
.venv/bin/python -m baseball_simulation_lab.careers public --admin-db data/careers/private_demo.sqlite3 --world-id local-demo --as-of 2026-04-01
.venv/bin/python -m pytest -q
.venv/bin/python -m baseball_simulation_lab.careers build
```

`build`は、8条件×10万打席の対照、能力あり・平均モード各1,000試合、条件を満たせば12球団×858試合×2シーズン、別の1,200選手×20年次更新を行います。年次検証の負荷は仮定で、20年間の実試合を実行したものではありません。内部DBと真値曲線は`data/research/stage11/snapshots/`へ保存し、公開データへコピーしません。

```bash
.venv/bin/python -m baseball_simulation_lab.careers build --output /tmp/stage11-rebuild
```

再構築に必要なのは、既存の第7・9・10段階の確率モデルとmanifestです。選手成長や故障の大規模な追加収集・医学モデル学習は行いません。再構築の指紋にはコード・設定・親モデル・Python/SQLite環境を含め、同じ保存先では既存成果を検証して再利用します。別実行の処理時間は変動します。

公開ZIPにはコード、親の確率表、公開用選手評価・成績、匿名集団の集計、説明資料とSHA256 manifestを収録します。管理者用DB、個人の真値曲線、潜在才能イベントは入れません。研究用シードは公開した再現用入力で、運営世界の秘密保持を保証するものではありません。

[モデルと公開境界](MODEL.md) · [第12段階への接続](STAGE12.md) · [ゲーム設計上の仮定](model_assumptions.json)

公開表・検証レポートの再生成（リポジトリ内、内部スナップショット生成後）：

```bash
.venv/bin/python docs/data-stage11/scripts/postprocess.py
.venv/bin/python docs/data-stage11/scripts/write_report.py
```

[選手一覧CSV](https://raw.githubusercontent.com/kosuke213/baseball/refs/heads/codex/stage11-player-careers/data_sources/stage11/public_players.csv)はExcel向けの別添で、値は誤差付き評価です。公開ZIP内の選手一覧はJSONです。
