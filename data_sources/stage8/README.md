# 第8段階：実験用フルゲームと変更しない試合履歴

[一式ZIPをダウンロード](https://raw.githubusercontent.com/kosuke213/baseball/codex/stage8-game-engine/data_sources/stage8/stage8_bundle.zip) / [実測結果レポート](https://github.com/kosuke213/baseball/blob/codex/stage8-game-engine/docs/data-stage8/README.md) / [ルール・記録の制限](TRANSITIONS.md) / [第9段階への接続仕様](STAGE9.md)

第7段階の打席窓モデルを使う独立した実験用エンジンです。従来の一球モデルや保存記録は保持します。NPBの本番リーグ運営システムではありません。完走しなかった試合も保存し、抽選の引き直しで隠しません。

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".

## Windowsでまず試す

ZIPを保存し、右クリック→「すべて展開」。Python 3.11以上があれば、展開先のフォルダーで以下を実行できます。追加ライブラリは不要です。Windows実機での動作確認ではありません。

```powershell
py -3 example.py --model-dir . --db my_history.sqlite3 --journal my_game.jsonl
```

この例は原本由来の経路だけを使います。主検証と同じ明示的な進塁仮定も許可するなら `--allow-assumptions` を追加します。未対応時の終了コードは2で、失敗を含む結果と履歴を保存します。同じジャーナル名への上書きは拒否します。再実行する場合は別名を使ってください。

`code/` に実行時のソース、`stage7_model/` に確率推論に必要な固定モデル、`routes.json.gz` に2023〜2024年の成績情報付き経路を同梱します。第8段階ZIPだけでサンプルの実行・保存・再生ができます。

## Python API

```python
from baseball_simulation_lab.fullgame.engine import Game, fictional_team
from baseball_simulation_lab.fullgame.model import GameModel
from baseball_simulation_lab.fullgame.rules import GameRules
from baseball_simulation_lab.fullgame.storage import HistoryStore, replay_game

model = GameModel.load('data_sources/stage7', 'data_sources/stage8/routes.json.gz')
game = Game(model, (fictional_team('AWAY'), fictional_team('HOME')),
            seed=8000, game_date='2026-04-01',
            rules=GameRules(max_innings=12, allow_draw=True,
                            automatic_runner_start=None),
            allow_assumptions=False, auto_relief_inning=7)
result = game.run()
assert replay_game(game.journal.rows)['score'] == result['score']
store = HistoryStore('data/fullgame/history.sqlite3')
try:
    store.save(game)
    saved_result = store.load(game.game_id)  # 確率モデルを読み込まず再検証
finally:
    store.close()
```

`game.step()` は1窓ずつ進めます。途中プレーを含む窓全体の抽選と、別の盗塁抽選を重ねません。打席間の `game.change_pitcher(id)`・`game.substitute(side, slot, id, pinch_runner=False)` が利用できます。球団には9人の打順・先発・ベンチ・救援の名簿を渡し、IDは全球団で一意にします。

`GameRules` は9回制に対する延長上限、引き分けの許可、二塁自動走者を導入する回（10回以降または無効）、安全上限を指定します。上限で同点かつ引き分け禁止なら失敗として停止し、架空の勝者を作りません。上限なし・引き分けなしも指定できますが、安全上限では停止します。

## 確認する成果物

- `validation.json`・`checkpoints.json`：100→1,000→10,000試合の累積結果。主検証は仮定を明示的に許可し、7回以降の最初の機会に救援1人を使います。先発の疲労推定ではありません。
- `games.csv`・`distributions.csv`：全試行のステータス、成功分の得点・安打・本塁打・四球・三振・打席分布。失敗を除いた分布には選択の影響があります。
- `failures.json`：原因、選手ID、状態、シード、モデル・ルール版、停止時の乱数状態。
- `stage7_failure_reproduction.json`：前段階の8停止の再現、原本上の件数・行範囲と新しい対応状況。
- `source_audit.json`：原本から復元・検証できた件数、残る解析不足、原本SHAと出典。
- `mlb_reference.json / mlb_reference_games.csv`：取得済みMLBとの参考比較。NPBとの差、2025年が既知の期間であることを明記。
- `league.json / schedule_858.csv`：12球団各143試合、各カード13回、ホーム71/72試合の日程検証。安定性・優先記録の条件を満たさなければ858試合の実行は未達とします。
- ZIP内の `empirical_only/`：仮定を使わない対照実験。主検証の結果と区別します。
- ZIP内の `sample_history.sqlite3 / sample_replay.jsonl`：完全な履歴を保存したサンプル。大規模ヘッドレス試行の集計を公式の試合履歴とは扱いません。
- `manifest.json / snapshot.json / bundle.json`：入力・コード・配布物の指紋。ゲームの結果・イベントは固定シードで再現可能ですが、実測した実行時間は環境で変わります。

## 原本からの再実行

```bash
.venv/bin/python -m baseball_simulation_lab.fullgame build
.venv/bin/python -m baseball_simulation_lab.fullgame simulate --seed 8000 --db data/fullgame/history.sqlite3
.venv/bin/python -m baseball_simulation_lab.fullgame replay --db data/fullgame/history.sqlite3 --game-id YOUR_GAME_ID
.venv/bin/python -m pytest -q
```

原本からの構築には第5段階の固定DB・3年分プレー原本、第6段階の `observations.sqlite3`、第7段階の固定モデルが必要です。第7段階READMEの復元場所を引き継ぎます。大規模な新規プレーデータ収集・モデル再学習は行いません。

構築先は `data/research/stage8/snapshots/<id>`。同じコード・設定・入力では検証済みの結果を再利用します。新しい保存先で作り直す場合は `--output` と、4冊の仕様書を配置した `--report-dir` を指定します。第3〜7段階の保存先を拒否し、処理失敗時には既存の現行版を変更しません。

記録は実験用です。自責点・セーブ・ホールド・裁量の必要な救援勝利投手は未完成の値を作らず、nullまたは要確認として出力します。完全な公式記録が確定したとは扱いません。
