# 第6段階：打席結果と状態遷移の確率表

**[確率表・CSV・加工DB・検証結果のZIP](https://raw.githubusercontent.com/kosuke213/baseball/codex/stage6-probability/data_sources/stage6/stage6_bundle.zip)** / [実施結果と評価](https://github.com/kosuke213/baseball/blob/codex/stage6-probability/docs/data-stage6/README.md) / [出典表示](ATTRIBUTIONS.md)

WindowsではZIPを保存 → 右クリック →「すべて展開」。`outcome_frequencies.csv` は打席結果の頻度、`evaluation_metrics.csv` は2025年の評価、`examples.json` は具体例です。`observations.sqlite3` は派生したプレー・観測打席の窓・除外行を含み、DB Browser for SQLite等で開けます。`model.json` と `kernels.json` はAPIから使う確率表です。

## 単位と制約

Retrosheetの行を一球・一打席と同一視していません。原本の `pa=1` と14個の排他的分類指標で打席完了を判別。三振・四球・単打・二塁打・三塁打・本塁打・死球・犠打・犠飛・失策出塁・野選・妨害・その他のアウト・その他打席を区別し、敬遠は四球の内数です。振り逃げでも結果区分は三振で、遷移は元記録を使います。

`plays` はNPを除く実プレー行です。盗塁・牽制・暴投・捕逸・ボーク・ファウルエラー等を含み、一球ではありません。`windows` は直前の打席完了／半イニング開始以降の実プレーから、次の打席完了または第3アウトまでをまとめます。打席中の走者アウトで半イニングが終われば `runner_only_end` で、打席完了を作りません。

窓の開始は「最初に記録された実プレー」の直前です。最初の投球時点を復元したものではありません。途中交代がある窓の入力IDは最初の記録時点のIDです。選手別の観測成績CSVは終了行のIDを使い、途中交代時の公式記録責任まで復元していません。

試合終了時に走者情報が消去される場合があるため、第3アウト前に終わった最終窓は遷移の推定・評価から除外します。完了した打席結果は残します。残り得点の集計も途中終了した半イニングを除外。延長の自動走者はルールにより開始状態へ置くもので、プレーとして学習しません。延長と通常回の遷移表は別です。

状態番号は `8 * outs + bases`。`bases` の1ビット目が一塁、2ビット目が二塁、3ビット目が三塁（1・2・4）です。0〜23が24状態、24は半イニング終了。0〜4得点と次状態を**同時に**推定・抽選します。

## 推定と年度分割

2023年で推定→2024年で検証して平滑化と選手成分の比率を選び、2023〜2024年で再推定し、2025年で評価します。2025年の成績を選手入力やパラメータ選択へ戻しません。

リーグ分布へクラスごと0.5の事前度数を加え、投打左右はリーグ、状態・左右・回・点差・表裏の条件は左右別分布へ縮小します。打者と投手はそれぞれリーグへの縮小成分で、条件成分との混合です。未知の選手はリーグへ、未知の条件は左右別→リーグへ戻ります。`B` は原本の両打ち区分で、実際の打席での構えを推測していません。

`probability_components.csv` は15クラスの成分表で、APIで条件・選手成分を混合し、打席完了を条件とする際は14クラスへ再正規化します。`conditional_posterior_sd` は親分布を固定した近似的な事後SDで、選手内相関・年度差・混合全体の不確実性を含みません。

遷移表は、状態・打席結果・通常／延長ごとに、次状態と得点の同時分布を推定します。同じ状態・結果の両区分を事前分布として共有し、走者数・アウト数の保存則を満たす候補に小さな事前確率を置きます。未観測の事前分布セルは `prior_only_cell=1` と明記し、観測数を捏造しません。この候補制約は全公式ルールの検証器ではありません。

評価は自然対数の対数損失、全クラスの二乗誤差の和によるBrier（0〜2）、10区間の校正表です。遷移・得点の予測では、実際の打席結果を入力せず、15結果を周辺化します。リーグ平均・左右別・条件別、一様分布、状態のみの遷移ベースラインを比較します。区間推定は試合単位の再抽出で、年度間の変化までは保証しません。

## API

リポジトリのルート、またはPythonパッケージを導入した環境で実行します。APIの推論自体はPython標準ライブラリのみです。

```python
import random
from baseball_simulation_lab.empirical import EmpiricalModel

model = EmpiricalModel.load('data_sources/stage6')
features = dict(outs=1, bases=1, batter_hand='L', pitcher_hand='R',
                inning=5, batting_score_diff=0, half=0)
print(model.predict_pa(**features))
print(model.predict_next_state_runs(**features))
print(model.predict_state_baseline(outs=1, bases=1))
step = model.sample_step(random.Random(42), **features)
print(step)
```

架空選手に実在選手のIDを勝手に割り当てません。最初は `batter_id`・`pitcher_id` を渡さず共通の基礎分布を使えます。実在選手の成分を検証するときは、訓練時点に存在したRetrosheet IDを明示します。架空の能力との対応付けは別の較正課題です。

`sample_step` は打席の窓の結果と、その結果に条件付けた状態・得点の組を返します。`completed_pa` が真のときだけ打順を進め、`half_ended` で攻守を交代します。延長開始時の自動走者、勝敗・サヨナラ判定、走者の個人ID、投手の失点責任、公式記録上の複雑な第3アウトなどは呼び出し側のルール処理が必要です。勝利打の打球種別・進塁の打ち切りまでは再構成しません。

第1段階の一球モデル `PitchOutcomeModel` とは異なる契約です。既存UIの一球をこのAPIの一ステップへ置き換えたり、架空の球速・回転・打球角度を実測として付加したりしていません。スコアのみのデモは統合方法の動作例で、公式ルールやゲーム分布の較正済み実装ではありません。

## 再実行

Python 3.11以上、推定・検証にはリポジトリのNumPyとpytestを使います。Windowsでは `python` を `py -3` に置き換えられます。

```bash
python -m baseball_simulation_lab.empirical run
python -m baseball_simulation_lab.empirical demo --seed 42
python -m pytest -q
```

通信は行いません。第5段階の固定DBと原本ストアが必要です。別環境では第5段階のDBを `data/research/stage5/snapshots/3380cf3ee94809d4dae3fe92/warehouse.sqlite3`、原本バックアップの `originals/blobs` を `data/research/pilot/raw/blobs` へ復元します。`--source`・`--cache` で別パスも指定できます。原本がなければ停止し、別サイトから自動収集しません。

生成先は `data/research/stage6/snapshots/<snapshot_id>/`。入力の指紋・コード・設定・実行環境から版を決め、同一入力の再実行は指紋検証後に再利用します。失敗時は前の現行版を維持。第3〜5段階の出力先への書き込みを拒否します。

ZIPの確認・API利用だけなら原本ストアの復元は不要です。`manifest.json` に各ファイルのSHA256と元原本の情報、`bundle.json` に配布ZIPの指紋があります。派生DBの `source_row`、窓の `first_source_row`・`last_source_row` から元ファイルへ戻れます。
