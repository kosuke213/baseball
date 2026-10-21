# 第7段階：確率校正・選手ID付き状態遷移

**[API・モデル・加工DB・評価一式をダウンロード](https://raw.githubusercontent.com/kosuke213/baseball/codex/stage7-calibration-transition/data_sources/stage7/stage7_bundle.zip)** / [結果レポート](https://github.com/kosuke213/baseball/blob/codex/stage7-calibration-transition/docs/data-stage7/README.md) / [走者遷移仕様](TRANSITIONS.md) / [第8段階への接続](STAGE8.md)

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".

WindowsではZIPを保存 → 右クリック →「すべて展開」。Python 3.11以上があれば、展開したフォルダーで `py -3 example.py --model-dir .` を実行できます。API例には追加ライブラリは不要です。`code/` に今回のソースを同梱しています。Windows実機での検証ではありません。

## 確認するファイル

- `calibration_metrics.csv`：補正前後、2024年前半・後半、既知の参考期間2025年。
- `calibration_fit_grid.csv`：2024年前半での温度・リーグ混合の比較。`class_scores.csv` と `rare_quantile_calibration.csv` は全14分類・稀な結果の診断。
- `transition_comparison.csv`：同じ次状態・得点への射影で比較。予測確率0の場合は対数損失を有限値に丸めず、JSONではnull＋無限大フラグで保存。
- `identity_audit.json`・`unsupported_windows.csv`：復元・検証できた範囲と未対応の記録。`identity.sqlite3` は全窓の判定と原本行参照、役割別の進塁テンプレート。
- `simulation_summary.csv`・`simulation_distribution.csv`：各モデルの半イニング試行。失敗は引き直さず、件数を残します。成功した試行だけの平均には選択の影響があります。
- `base_model.json`・`calibration.json`・`identity_model.json`・`kernels.json`：版を固定した推論用データ。
- `manifest.json`・`snapshot.json`：入力・コード・同梱ファイルのSHA256。配布ZIPの指紋は `bundle.json`。

## 評価期間

2023年で基礎モデルを学習し、2024年前半で校正係数を推定、後半で手法を選びます。日付はゲーム内の最小・最大イベント日付を使い、7月1日をまたぐ再開試合は両方から除外。校正学習と選択に同じ試合を使いません。

第6段階で2024年のモデル選択と2025年の評価を既に行っています。このため2024年の再分割は探索的検証、2025年は既知の参考評価です。新しい未使用テスト期間とは称していません。適切な新しい期間が既存の固定データにないため、独立した最終評価は未実施です。

校正手法は温度、リーグ平均との混合、両者の組合せを軽量比較。2024年前半で係数を推定して後半で比較し、対数損失に加えてBrierと最大確率ECEの悪化を抑える条件で選びます。補正なしが選ばれれば、そのまま維持します。2025年へ合わせた再調整はしません。

「先行走者なしの野選」を除く制約は、校正とは別のルール修正です。`selected_plus_FC_rule` として分離して評価します。打席完了条件の14確率と、打席未完了の走者アウト終了を含む15確率も区別します。

## API例

リポジトリのルートから実行できます。ダウンロードZIPなら `code/` が同じパッケージを含みます。

```python
import random
from baseball_simulation_lab.calibrated.api import CalibratedModel
from baseball_simulation_lab.calibrated.identity import example_frame

model = CalibratedModel.load('data_sources/stage7')
state = example_frame(11)  # 一死一・二塁、架空のB/R1/R2
print(model.predict_pa(state, batter_hand='L', pitcher_hand='R'))
print(model.support_report(state))
result = model.resolve_outcome(state, 'double', random.Random(726))
print([r.player_id for r in result.scored], result.out_ids, result.after)
```

`model.sample(state, rng)` は窓結果も抽選します。原則は実データから復元・検証できた経路だけを選び、未観測の経路は `UnsupportedRule` を返します。`allow_assumptions=True` を明示した場合だけ、保守的な固定進塁を事前分布として加えます。各イベントの `plan.source` は `empirical` / `assumption` / `explicit_event` です。既存の24状態表から個人の動きを勝手にランダム生成しません。

予測への実在選手IDは `batter_model_id`・`pitcher_model_id` で明示します。架空選手IDを統計表の実在IDへ自動対応付けず、未指定ならリーグ・条件の基礎分布を使います。両打ち `S` は原本区分 `B` へ対応付けます。

1回の窓に盗塁・暴投等の途中プレーが含まれる場合があります。各原子プレーを `result.transitions` で確認でき、得点者・アウト者・残塁者・試合終了で打ち切った選手を返します。`completed_pa` が偽なら打順を進めません。3アウト後は `advance_half` で明示的に攻守交代します。

## 再実行

全処理はオフラインです。第5段階のDBと取得原本、第6段階の派生DBが必要です。各段階の公開ZIPから復元できます。新規収集・外部サービスへの接続は行いません。

```bash
.venv/bin/python -m baseball_simulation_lab.calibrated run
.venv/bin/python -m baseball_simulation_lab.calibrated.example --model-dir data_sources/stage7 --seed 726
.venv/bin/python -m pytest -q
```

Windowsは `.venv\\Scripts\\python.exe` または `py -3` を利用できます。再推定にはリポジトリで固定したNumPyを使います。APIの推論・ルール処理・記録再生は標準ライブラリのみです。

第5段階DBを `data/research/stage5/snapshots/3380cf3ee94809d4dae3fe92/warehouse.sqlite3`、第6段階の `observations.sqlite3` を `data/research/stage6/snapshots/d0a6e1166170560f19b250d3/observations.sqlite3`、原本の `originals/blobs` を `data/research/pilot/raw/blobs` へ置きます。`--source5`・`--source6`・`--cache` で別パスも指定可能です。第7段階ZIPだけで推論例は実行できますが、原本からの再推定にはこれらの入力が必要です。

出力は `data/research/stage7/snapshots/<snapshot_id>`、現行版は `current.json`。同じ入力・コード・環境なら再利用し、破損を検知した場合は停止。失敗時は前の現行版を維持します。第3〜6段階の保存先への出力は拒否します。

完全な公式試合エンジンではありません。とくに未対応の経路、複雑な第3アウト、サヨナラ打の公式記録、交代時の記録責任などは [制限と接続仕様](STAGE8.md) を参照してください。
