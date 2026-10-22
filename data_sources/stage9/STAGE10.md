# 第10段階への接続仕様

この段階は完走性を保証する本番エンジンではありません。最新レポートの停止・未確定・リーグ開始判定を先に確認してください。858試合が未実行なら、日程生成や集計APIだけをシーズン完走とみなさないでください。

## 継承するAPI

- `completion.engine.Game / fictional_team / Team`：試合の開始、`step/run`、基本交代。IDは名簿・日付・シード・設定・モデル／ルール／エンジン版から決定。
- `completion.model.GameModel.load(stage7_dir, routes_gz, terminal_json)`：指紋付き推論モデル、`predict_pa/predict_step/sample/support_report`。役割は事象と原本経路の選択。
- `completion.rules.apply_play`：抽選しない状態・得点・アウト・IDの処理。`Play / Credit / Frame / RunnerToken` を継承。根拠不足は例外。
- `completion.history.GameJournal / replay_rows`、`completion.storage.replay_game / HistoryStore`：確定イベントだけで全成績を再生。モデルファイル不要。
- `HistoryStore.bind_season(game_id, season_id, scheduled_number)`：不変の試合とシーズン日程を対応。試合自体のID・履歴を変更しない。
- `completion.season.Season.add/export / run_league`：重複拒否、null伝播、勝敗・引分・打撃・投球の合計。`run_league` は開始条件をAPI内でも検査。
- `fullgame.league.schedule/validate_schedule/Standings`：第8段階のまま使用。
- `completion.records.COVERAGE`：公式記録への対応区分。新しい記録を出す際は版を分け、未知を0にしない。

## 先に解決すべきこと

サヨナラ時の一塁アウト等の時刻情報を持つ事象表現が必要です。現在の完結した打席経路だけでは、サヨナラでどのアウトが成立したか一般には確定できません。既存原本の追加記述で確定できる範囲を調べ、足りない場合は利用条件を確認した詳細情報を対象限定で取得してください。仮定による時間分布を将来導入する場合も、実測とは分け、ユーザーに示す実験規則とモデル版を用意します。

通常攻撃終了の二項MLEは、未観測の二重走塁死に0を与えます。2025年の1例を学習へ加えて精度改善と称さず、終了モデルをどの粒度で一般化できるか、必要な情報と支持を検討してください。`other_pa` の正の未対応確率、窓内交代・途中カウント責任、未完了サヨナラの独立ハザードも残ります。CatBoostへ置換しても時間順やルールの情報不足は解消しません。

追加修正の後に、事前に決めた新しいシード列で100→1,000→10,000、開始条件を満たせば858試合を実行します。通るシードを探す運用にしません。終了ゲームの保存・再生・シーズン合計・全143試合・勝敗総数一致まで確認します。

これらが十分安定してから、選手能力・成長・故障・契約・編成・ファン参加を接続してください。確定した過去試合を新しい能力・確率で再生成する機能は追加しません。新しいNPB年度の導入は将来の試合にだけ適用し、MLBとのリーグ差と独立評価を別途扱います。

## 最小API例

```python
from baseball_simulation_lab.completion.engine import Game, fictional_team
from baseball_simulation_lab.completion.model import GameModel
from baseball_simulation_lab.completion.storage import HistoryStore

model = GameModel.load("data_sources/stage7", "data_sources/stage9/routes.json.gz",
                       "data_sources/stage9/terminal_model.json")
game = Game(model, (fictional_team("A"), fictional_team("H")), seed=90000)
result = game.run()
store = HistoryStore("data/completion/example.sqlite3")
try:
    store.save(game)  # 停止ゲームも状況と履歴を保存。履歴と全成績を照合。
    restored = store.load(game.game_id)  # モデルの抽選なし。
finally:
    store.close()
```
