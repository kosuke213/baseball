# Phase 1 検証記録

## 環境と結果

Linux x86_64 / Python 3.12.14 / NumPy 2.5.4 / pandas 2.3.3 / Streamlit 1.66.0 / pytest 9.1.1。CPU実行、スレッド・プロセス並列は使用していません。依存関係はSHA-256検証付きロックから導入しました。

Windows向け手順とWindows/Linux × Python 3.11/3.12のCIを用意しました。**Windows実機とGitHub Actionsでの実行は未検証**です。Linuxの検証をWindowsでの成功として扱いません。

## 実行した主要コマンド

作業ディレクトリは `/workspace/baseball`。仮想環境を明示的に使いました。

```bash
# 初回のロック生成と導入
uv pip compile requirements.in --python-version 3.11 --universal --generate-hashes --output-file requirements.txt --cache-dir /workspace/.cache/uv
uv venv .venv --python python --cache-dir /workspace/.cache/uv
uv pip install --python .venv/bin/python --require-hashes -r requirements.txt --cache-dir /workspace/.cache/uv

# 再利用用インストールスクリプトとして、この手順も実行・再実行
python -m venv .venv
PIP_CACHE_DIR=/workspace/.cache/pip .venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m baseball_simulation_lab init

.venv/bin/python -m pytest -q
.venv/bin/python -m baseball_simulation_lab simulate --games 1 --seed 42 --output reports/smoke
.venv/bin/python -m baseball_simulation_lab replay --game-id 5faf632ed1182948b525cff8

.venv/bin/python -m baseball_simulation_lab simulate --games 1000 --seed 42 --summary-only --output reports/validation-1000

.venv/bin/python -m baseball_simulation_lab simulate --games 10 --seed 200 --carry-fatigue --world-config config/generation.json --rules config/rules.json --db data/series.sqlite3 --output reports/series

.venv/bin/python -m streamlit run baseball_simulation_lab/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
curl --fail --silent http://127.0.0.1:8501/_stcore/health
```

`pip check` は `No broken requirements found`、Streamlitのhealthは `ok`、ルートへのHTTPリクエストも成功しました。サーバーのポート確認に加え、AppTestで実際の画面の状態遷移と保存結果を確認しています。クラウドのWebプレビューURLは生成していません。

テスト中に初期化したDBだけを `reset --yes` で再生成し、最終コードの試合例を用意しました。既存のユーザーファイルはありませんでした。`init` とインストール手順の再実行では既存の世界・試合を保持することを確認しました。

## 自動テスト

最終実行は **45 passed in 8.97s**（失敗・スキップなし）。pytestはルール、モデル、保存、CLI、Streamlit画面を検証します。

- 3アウト、4ボール、3ストライク、2ストライク後ファウル、強制進塁、満塁四球、安打4種類、併殺、犠飛、打席と打数、打順継続。
- 9回裏省略、ビジターがリードする9回裏、サヨナラ本塁打、非本塁打サヨナラの決勝点と残走者、延長上限、タイブレークの非自責走者。
- 投手交代・再登板禁止、継承走者の失点責任、野手交代・再出場禁止、塁上選手の交代と得点帰属。
- 同じ入力・シードの全記録一致、モデルの交換、各条件での確率の範囲・総和、屋内の天候効果除外、相関付き生成と生成設定、疲労回復。
- 100試合で得点・安打・投球数・打席の記録整合、終了と安全上限、不正な状態の診断。
- SQLiteの完全復元、過去記録の不変性、重複排除、交代判断の異なる実験の区別、トランザクション失敗時のロールバック。
- CLI初期化・実行・再実行検証・繰り返し保存・明示的リセット要件。
- AppTestによる56選手の表示、内部特性の非表示、1球進行、試合完了、保存ログ再表示、開発者画面、守備選択の不整合に対するエラー表示。

一括実行とは別に、疲労を継承する10試合を全ログ付きで保存し、**10試合すべてを再実行して全記録一致**を確認しました。SQLiteの `PRAGMA integrity_check` は `ok` でした。

## 1試合の実行例

初期世界シード2026、試合シード42、蒼波実験球場、20℃・無風、通常の延長上限12回。

- ビジター: 蒼波オービッツ **1点**
- ホーム: 星環コメッツ **7点**
- 総投球数: **262球**、登板投手合計5人
- 9回表終了時にホームがリードして終了し、9回裏は実施しない。
- game_id: `5faf632ed1182948b525cff8`
- 保存入力からの再実行で、イベント・成績・最終状態が完全一致。

## 1,000試合の独立試行

初期世界を毎試合同じ状態に戻し、試合シード42〜1041、ホーム・ビジター交互で実行。**1,000試合完了、エラーなし**。今回の測定時間は約45.65秒です。`--summary-only` なのでこの1,000試合のSQLite・一球ログは保存せず、CSV/JSONの集計を出力しています。全ログ付き保存は上記1試合と10試合、および自動テストで別途確認しました。

| 指標 | 観測値 |
|---|---:|
| 1チーム1試合あたり平均得点 | 4.5025 |
| 打率 | .30094 |
| 出塁率 | .35554 |
| 長打率 | .47980 |
| 三振率（打席あたり） | 20.398% |
| 四球率（打席あたり） | 7.990% |
| 本塁打率（打席あたり） | 3.152% |
| 平均総投球数 | 266.161 |
| ホーム勝率（引き分け含む） | 50.3% |
| 延長戦発生率 | 9.3% |
| 引き分け | 21試合 |

詳細なイニング別得点、得点分布、設定とモデル版は [validation-summary.json](validation-summary.json) に保存しました。これらは実測プロ野球との一致を示す数値ではありません。比較用データは未取得で、参照値はnullです。打率が高めで保守的な進塁を使うことなどを、Phase 2の較正で検証します。

## 保存したクラウド設定

`install_script` と `start_skill` を環境設定の下書きに保存しました。依存導入・DB初期化、既存チェックアウトの利用、プロセスの再起動、ローカルhealthと画面操作テストによる確認を含みます。秘密情報や追加サービスは不要です。

下書きの保存は公開ではありません。環境設定で内容を確認・保存し、Publishしてください。公開後の新規タスクへの復元はまだ検証していません。作成したコードはクラウド内にあり、GitHubへのpushはこの検証時点では行っていません。
