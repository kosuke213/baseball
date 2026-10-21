# 架空野球シミュレーション実験室 — Phase 1

2球団・各28人の**完全に架空の選手**による、CPUで動くローカル実験環境です。1球ずつ進む試合、SQLiteの一球ログ、再現可能な乱数、CLI、Streamlit UIを備えます。確率・疲労・球場補正は仮説で、実際のプロ野球データでは較正していません。

数値計算は **NumPy**、集計は **pandas**、UIは **Streamlit**、テストは **pytest**、保存はPython標準の **SQLite** を利用します。外部API・LLM・GPU・クラウドの契約やキーは不要です。野球の状態遷移と記録処理は交換可能な確率モデルから分離しています。

## 最初に実行するコマンド（Windows 11 / PowerShell）

まず画面を試す場合は、Python 3.11以上を導入して `start_windows.bat` をダブルクリックできます。依存関係の導入・必要な初期化・ブラウザ起動をまとめて行います。初回はネット接続が必要です。展開したフォルダーの `START_HERE.txt` も参照してください。この起動ファイルはWindows実機では未検証です。

Python 3.11以上を用意し、このREADMEがあるリポジトリのルートで実行してください。PowerShellの実行ポリシー変更や仮想環境のActivateは不要です。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
.\.venv\Scripts\python.exe -m baseball_simulation_lab init
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run baseball_simulation_lab/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Python 3.12を使う場合は最初の `-3.11` を `-3.12` に変更してください。以降のコマンドは同じです。起動後はStreamlitがターミナルに表示するローカルアドレスをブラウザで開きます。クラウドのオンボーディング画面にはWebプレビュー機能がありません。

## Linux / このクラウド環境

```bash
python -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -m baseball_simulation_lab init
.venv/bin/python -m pytest -q
.venv/bin/python -m streamlit run baseball_simulation_lab/app.py --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
```

依存関係は `requirements.in` に列挙し、`requirements.txt` に推移依存を含めてバージョンとSHA-256を固定しています。Python 3.11と3.12以降でNumPyの固定版が異なるため、記録の再検証にはスナップショットに記載したNumPy版が必要です。通常の再表示はNumPy版によらず保存ログを読みます。

## CLI

上記の仮想環境のPythonを使います。以下はActivate済みの表記です。ActivateせずPython部分を上記の実行パスに置き換えても動きます。

```bash
# 2球団・56選手を生成。再実行しても試合記録を消さない
python -m baseball_simulation_lab init

# 1試合。既定では初期状態と全イベント・成績をSQLiteに保存
python -m baseball_simulation_lab simulate --games 1 --seed 42 --output reports/smoke

# 100試合の独立試行。ビジター・ホームは毎試合入れ替える
python -m baseball_simulation_lab simulate --games 100 --seed 42 --output reports/100

# 1,000試合の速度・統計検証用。DBと一球ログを保存しないことを明示
python -m baseball_simulation_lab simulate --games 1000 --seed 42 --summary-only --output reports/validation-1000

# 休養と疲労を継承する連戦。毎試合後に1日休む
python -m baseball_simulation_lab simulate --games 10 --seed 200 --carry-fatigue --db data/series.sqlite3 --output reports/series

# 球場・天候・延長条件・仮説モデルを変更
python -m baseball_simulation_lab simulate --park bay --temperature 28 --wind 4 --wind-direction 0 --max-innings 12 --extra-runner --hr-scale 1.1

# JSON設定ファイル（--rules は個別ルールフラグに優先）
python -m baseball_simulation_lab simulate --world-config config/generation.json --rules config/rules.json

# 保存済み試合の再実行と、全イベント・個人成績の完全一致検証
python -m baseball_simulation_lab replay --game-id YOUR_GAME_ID

# 初期データごと作り直すときだけ明示的に実行。指定DBの全記録を削除
python -m baseball_simulation_lab reset --db data/sandbox.sqlite3 --yes
```

`reports/.../games.csv` は試合単位の観測値、`summary.json` は得点・打率・出塁率・長打率・三振率・四球率・本塁打率・投球数・得点分布・延長率・ホーム勝率などです。イニング平均は**実際に行われた攻撃半イニング数**を分母にします。ホーム勝率は引き分けを含む値と除いた値の両方を出力します。比較データと推定試合時間は未取得なので `null` です。

既定のDBは `data/lab.sqlite3`。`init` は同じ世界なら何度でも実行できます。異なる初期シード・生成設定で既存世界を上書きしようとするとエラーになります。別の `--db` を指定するか、必要なデータをバックアップして明示的に `reset` してください。同一入力・同一シード・同一交代履歴の試合は二重登録しません。異なる交代判断の試合は別の実験として保存します。同じ入力と交代履歴で結果だけ異なる場合は競合として拒否します。

## UIの使い方

- **ダッシュボード**: 球団、全選手の公開プロフィール、最近10試合と直近の個人成績。
- **試合実験**: シード、球場、天候、延長上限、タイブレーク、本塁打・疲労係数、先発、守備位置、打順を指定。「新しい試合」で確定し、「1球進める」か「最後まで進める」で進行します。終了時に自動保存します。
- 打順の選択を外して再選択すると順番を変更できます。守備選手を変更したときは打順も同じ9人に揃えてください。重複・守備不適格の選択はエラーとして表示します。
- 打席の間に救援投手・控え野手へ手動交代できます。控え野手は交代先の守備位置を守れる必要があります。先発の自動交代は既定90球、救援は35球です。
- **保存試合・リプレイ**: 保存済みの試合を選び、スライダーで過去の各球の状態を再表示。一球ログをCSVで取得できます。これは再計算ではありません。再実行検証はCLIの `replay` です。
- **開発者**: 内部特性、初期状態での確率と大量抽選、処理時間、ログを表示。通常画面には潜在特性を渡しません。この画面分離は認証ではなく、ローカル実験用です。
- 一括実験は1〜1,000試合を独立試行して全ログを保存し、集計CSVを取得できます。CLIの `--carry-fatigue` は別途、連戦条件を試す機能です。

## 構成

| 場所 | 内容 |
|---|---|
| `baseball_simulation_lab/domain.py` | 選手・球団・潜在特性・日々の状態・球場・天候・ルール・記録 |
| `generation.py` | 共有因子で相関を持たせた架空選手生成 |
| `model.py` | 交換可能な一球モデル、打球モデル、確率検証 |
| `engine.py` | 乱数抽選と決定的なルール遷移、交代、公式記録 |
| `storage.py` | SQLite、履歴保護、シリアライズ、再実行検証 |
| `reporting.py`, `__main__.py` | 集計・CSV/JSON・CLI |
| `app.py` | StreamlitローカルUI |
| `config/` | 延長などのルール設定と生成分布の設定例 |
| `tests/` | ルール、モデル、記録・再現性、CLI、画面操作 |
| `docs/` | 設計、検証結果、Phase 2のデータ要件、OSS情報 |

## 実装範囲と仮定

DH制、9回制、既定12回打ち切り引き分け。ファウルは2ストライクから三振にしません。安打4種類、ゴロ・フライ・ライナーアウト、条件付き併殺・犠飛、四球、三振を扱います。9回表終了時のホーム勝利、通常のサヨナラ、サヨナラ本塁打の全得点を区別します。非本塁打のサヨナラは決勝点までとし、決勝点に必要な塁打数に記録を短縮します。

進塁は保守的な固定塁数モデル（単打1塁、二塁打2塁など）。通常のゴロ・フライ・ライナーでは走者を止め、条件付きの併殺・犠飛を別の結果として扱います。守備範囲のチーム平均、投打の左右、カウント、投手の奪三振・制球特性、投球による疲労を使います。球場の仮定係数と屋外の気温・風は本塁打確率に作用します。フェンス寸法は情報で、物理計算はしません。湿度・降水状態は保持のみです。

得点は走者が出塁した時の投手に帰属させます。タイブレーク走者は自責点に含めません。失策などがないモデルなので、それ以外の得点は自責点とする限定的な記録です。投球回は小数値でなくアウト数で保持します。

投手・打者交代は打席間だけ。塁上の選手を交代させた場合は代走にも反映し、投手の失点責任は引き継ぎます。再出場は禁止し、控え投手を使い切ったら現在の投手が続投します。最低対戦打者数などのリーグ固有の継投制限は未実装です。UIはブラウザのセッション内に進行中試合を保持し、途中保存・再開は未実装。公式保存は試合終了時に行います。

**未実装**: 失策、盗塁・盗塁死、犠牲バント、死球、暴投・捕逸、ボーク、振り逃げ、打撃妨害、守備選択、アピール・複雑な第3アウト、走塁死、勝敗投手・セーブなどの詳細公式記録。成長・故障・長期キャリア、実測による較正、機械学習、ファン投票、球団経営、公開サイト、LLMコンテンツ生成は後続フェーズです。

## 検証と次の段階

Phase 2の第1段階で [データ・情報源の収集先台帳](docs/data-sources/README.md) を作成し、第2段階で [実データの取得・品質検査](docs/data-pilot/README.md) を実施しました。4提供元の原本を保存し、試合・プレー・選手ID・日本の候補情報・気象を独立したSQLiteへ収録しています。[DBと確認用CSVのダウンロード](https://raw.githubusercontent.com/kosuke213/baseball/codex/data-sampling-pilot/data_sources/pilot/sample_bundle.zip) と [開き方](data_sources/pilot/README.md) を用意しました。確率モデルの学習・較正はまだ行っていません。

[検証記録](docs/validation.md) に実行済みコマンド・試合例・1,000試合の測定値を記載しています。Linux / Python 3.12でテストしました。**Windows実機での起動は未検証**です。Windows/Linux × Python 3.11/3.12のGitHub Actions設定を用意していますが、まだ実行されていません。

Phase 2では、出典・期間・利用条件を確認した投球・打席・打球・走者進塁データを取得し、定義と対象リーグを揃えて較正します。詳細は [アーキテクチャとPhase 2](docs/architecture.md) を参照してください。
