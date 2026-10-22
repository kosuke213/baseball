# 第10段階の実行方法

[検証レポート](https://github.com/kosuke213/baseball/blob/codex/stage10-season-stability/docs/data-stage10/README.md) · [配布ZIP](https://raw.githubusercontent.com/kosuke213/baseball/refs/heads/codex/stage10-season-stability/data_sources/stage10/stage10_bundle.zip)

ZIPを保存し、右クリック→「すべて展開」。Python 3.11以上で、展開先のターミナルから実行します。推論・生成・保存再生は標準ライブラリだけで動きます。

```powershell
py -3 example.py --model-dir . --seed 310000 --db my_history.sqlite3 --journal my_game.jsonl
```

**既定は、原本の終点と明示的な生成仮定を組み合わせる実験モード**です。原本だけの制限を確認するときは`--empirical-only`を追加してください。このモードには未観測経路や時系列不明による停止が残ります。停止は状況・履歴とともに保存し、終了コード2を返します。同名ジャーナルの上書きは拒否するので新しい名前を指定してください。

リポジトリ：

```bash
.venv/bin/python -m baseball_simulation_lab.stability simulate --seed 310000 --db data/stability/history.sqlite3
.venv/bin/python -m baseball_simulation_lab.stability replay --db data/stability/history.sqlite3 --game-id YOUR_GAME_ID
.venv/bin/python -m pytest -q
.venv/bin/python -m baseball_simulation_lab.stability build
```

`build`は既存62停止の再現、原本行の確認、通常／サヨナラの全経路監査、確率比較、100→1,000→条件を満たせば10,000試合、原本限定の対照、条件を満たせば858試合の順に進めます。1,000試合で停止・整合性エラー・優先記録未確定があれば主検証の10,000試合への拡大を止めます。858試合は主検証全体の同条件を満たした場合に限ります。未実施の試合をスコアで埋めません。

原本再構築には第5・6段階のDB、第7段階の推論JSONとmanifest、第9段階の経路・終端表・モデルmanifest・62停止、既存Retrosheet年別ZIPが必要です。原本の配置・復元は第5〜9段階のREADMEを継承します。追加データ収集はありません。配布ZIPに原本DBは重複収録しません。

```bash
.venv/bin/python -m baseball_simulation_lab.stability build --output /tmp/stage10-rebuild
```

コード・固定入力・設定・Python/SQLite環境を指紋にして不変スナップショットへ保存します。途中失敗では現行版を保持し、失敗領域を調査用に残します。同じ指紋の再実行は全ファイルを照合して既存結果を再利用します。別実行の時間計測は変動するため、測定JSON全体のバイト一致は要求しません。

配布物は`model/`（支持表）、`stage7_model/`と`stage9_model/`（親モデル）、`audits/`、`main/`、`empirical_only/`、実施できた場合の`league/`、`code/`に分けています。`manifest.json`は配布全体のSHA256です。`snapshot_manifest.json`は元スナップショットに対する指紋で、配布物の親モデルやコード等は`manifest.json`で照合します。

[生成仮定と規則の契約](TRANSITIONS.md)、[公式記録対応](record_coverage.json)、[第11段階への接続](STAGE11.md)も確認してください。NPBの実測環境や全公式記録を再現した本番リーグとは称していません。
