# 第9段階の実行と配布

実験用の第9段階。第8段階の `fullgame` は変更せず、`completion` を版別の実行器として追加しています。球速等の補完、新規プレーデータの取得、大規模な学習は行いません。

GitHubの結果は [検証レポート](../../docs/data-stage9/README.md) を参照してください。ZIPは展開後、Python 3.11以上の標準ライブラリだけで推論・試合生成・SQLite保存再生ができます。

```powershell
py -3 example.py --model-dir . --seed 90000 --db my_history.sqlite3 --journal my_game.jsonl
```

原本限定が既定です。固定進塁の仮定を許可する主検証モードは `--allow-assumptions` を付けます。停止もDBと履歴に保存し、CLIは終了コード2を返します。ジャーナルは新しい名前を指定してください。同じファイルの上書きは拒否します。

リポジトリでの実行：

```bash
.venv/bin/python -m baseball_simulation_lab.completion simulate --seed 90000 --db data/completion/history.sqlite3
.venv/bin/python -m baseball_simulation_lab.completion replay --db data/completion/history.sqlite3 --game-id YOUR_GAME_ID
.venv/bin/python -m pytest -q
.venv/bin/python -m baseball_simulation_lab.completion build
```

`build` は原本監査→旧155件と打点54件の再現→確率比較→主100/1,000/10,000試合→原本限定100/1,000試合を実行します。リーグ試験は各モードの直近1,000試合で停止・整合性エラー・優先記録の未確定がすべて0のときだけ開始します。単発の1,000連続成功で停止確率0は証明できません。

再構築には既存の第5・6段階DB、第7段階の4推論JSONとmanifest、第8段階の経路・155停止・1万試合CSV、第3〜5段階のRetrosheet原本ZIPが必要です。ZIP配布物には原本DBを重複収録しません。元データの保管・復元は第5〜8段階のREADMEを継承します。元の配置は `fullgame.sources.input_paths()` が返します。旧配布物を新しいモデルで再学習して置き換える操作はありません。

別保存先：

```bash
.venv/bin/python -m baseball_simulation_lab.completion build --output /tmp/stage9-rebuild
```

同じコード・設定・Python/SQLite環境は同じスナップショットIDを使います。保存済み結果はSHA256を確認して再利用します。時間計測は再実行ごとに変動するため、別保存先の測定JSON・ZIPがバイト一致するとはしません。原本からのモデルと監査JSONは一致を検証します。排他ロック・一時領域・原子的公開により、中断時は旧版を保持します。失敗領域も調査用に保持します。

推論ファイルの `model_manifest.json` と配布全体の `manifest.json` は役割が異なります。`snapshot_manifest.json` のパスは原スナップショットの `model/main/audits/empirical_only` 構造に対するものです。配布時は前3者をルートへ展開するので、配布整合性には `manifest.json` を使ってください。
