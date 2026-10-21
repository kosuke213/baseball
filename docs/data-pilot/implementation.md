# 収集基盤・保存形式・再検証

[第2段階の結果](README.md) / [標本と再実行手順](../../data_sources/pilot/README.md) / [必須出典表示](../../data_sources/pilot/ATTRIBUTIONS.md)

## 保存するもの

| 場所 | 内容 |
|---|---|
| `data_sources/pilot/plan.json` | 調査済みの対象URL、権利判断・確認資料、最大サイズ、選択規則、保留理由 |
| `data_sources/pilot/lock.json` | 計画ファイルのSHA256、全28原本のURL・SHA256・バイト数 |
| `data_sources/pilot/manifest.json` | 実取得時刻UTC、元URL・最終URL、HTTP状態、Content-Type、ETag等、版、利用条件の写し |
| `data/research/pilot/raw/blobs/<sha256>` | HTTPエンティティの原本。ZIP等は展開せず元のバイト列で保持。Git対象外 |
| `data/research/pilot/raw/index/<artifact-id>.json` | 原本を指すメタデータと要求仕様の指紋。再実行時に原本を再検査 |
| `data/research/pilot/normalized/*.jsonl` | 元列全て、原本ID、ZIPメンバー、元の行番号。加工データ。Git対象外 |
| `data/research/pilot/pilot.sqlite3` | 独立したSQLiteスナップショット。Git対象外。配布ZIPには標本DBを収録 |
| `data_sources/pilot/quality.json` | 実入力走査数と標本収録数、列別空欄、元記号、キー重複、整合性検査、結合結果 |
| `data_sources/pilot/sample_bundle.zip` | 標本SQLite、CSV、少数のプレビュー、出典表示、manifestと品質。約2.4 MB |
| `data_sources/pilot/bundle.json` | 配布ZIPとSQLiteのSHA256 |

第1段階の `catalog.sqlite3` は候補台帳、`data/lab.sqlite3` は架空試合です。実データをこれらに混入させません。

## 取得・失敗・版の扱い

`data_collection/fetch.py` はPython標準ライブラリのHTTPS、SHA256、JSONを使います。TLS検証は既定のままです。認証不要の今回の配布物だけを対象にしており、有料・会員領域を迂回しません。リダイレクトはHTTPSかつ明示した同一ホスト等に限定します。

ファイルごとの上限に加え、1回の実行で新しくダウンロードする合計を96 MBまでに制限。応答ヘッダーの上限超過は本体を読む前に停止し、転送中の超過・空応答・途中切断・指紋不一致も失敗にします。ZIPはディスクへ展開せず、決めたメンバーだけを読み、非圧縮サイズにも160 MBの上限を置きます。

同一ホストへの要求を最低0.4秒空け、429と一部のサーバー障害だけ最大2回再試行します。長いRetry-Afterはその回を中止。401/403でリトライや認証回避はしません。利用条件の確認資料が取れなければ、依存する本体取得も止めます。ネットワーク例外の詳細はプロキシ情報が混ざる可能性があるため保存しません。

`lock.json` で可変URLのRetrosheet/気象庁も原本を特定します。GitHubの2提供元はさらに完全なコミットSHAを固定しています。既存lockを通常実行で書き換えません。原本に更新があった場合は、元の標本を保持した新しい版として受け入れます。

新しい計画を初めて取得するときだけ `--record-lock` で封印します。今回の配布計画にはすでにlockがあるため不要です。キャッシュを信用して処理を飛ばすのではなく、オンライン・オフラインとも全原本の指紋を再検査します。通信の失敗後も取得済み原本は再利用できます。

SQLiteは新しい一時ファイルへ全表を作り、外部キーとintegrity_checkを確認してから置換します。取得・解析・構築失敗で前のDBを消しません。品質異常のあるデータは検査結果を`review_required`とし、原行を保持した診断用スナップショットとして出力、終了コード2で区別します。正常0、取得・解析等の失敗1です。

## 列とキー

全列の実型は [quality.json](../../data_sources/pilot/quality.json) にあります。CSVの値は文字列として保持し、計算に必要な箇所だけ整数として検査しています。空欄・記号・球速などを黙って補間・換算しません。

| データ | 主な列・キー | 定義・単位の根拠 |
|---|---|---|
| Game Logs | game_id = home team + date + game number。field_001日付、002試合番号、004遠征側、007ホーム側、010/011得点、012アウト数、014再開情報、017球場、018入場者数、019所要分、020/021イニング別得点 | [公式glfields.txt](https://www.retrosheet.org/gamelogs/glfields.txt)、保存済み指紋 |
| plays | gid+pn。score_v/hはプレー**開始前**、outs_pre/post、br1〜3_pre/post、vis_home、top_bot、runs、date、pbpなど177列 | [公式parsed CSV定義](https://www.retrosheet.org/downloads/plays.html)。NP行を含むので行数は投球数や打席数ではない |
| people | key_uuidを人物の永続キーとし、key_retro等の原IDも保持。短縮key_personを永久キーにしない | 固定版Chadwick README。人物統合・分離の可能性があり、一意対応は版ごとに検査 |
| japan_board | rank+name_jpは今回の表内キーだけ。将来の人物キーにはしない。原注記を保持 | 固定版のLICENSE/METHODOLOGY。数値の計測系・単位・著者の評価を混同しない |
| weather | station_id+timestamp_utc。JSTの観測日・時1〜24、気温℃、風速m/s、降水mm、気圧hPa、元のcell_attributesなど | 対象公式HTMLの多段見出しとセル属性。24時は翌日0時。記号の説明は[気象庁](https://www.data.jma.go.jp/stats/data/mdrr/man/remark.html)参照、今回数値化せず |

各原行には `artifact_id`、`member`、`source_row` を付け、SQLiteの `artifacts` 表からURLと原本SHAにたどれます。通常CSVはヘッダーを1行と数え、Game Logsはヘッダーなしで1行目から数えます。気象の `source_row` は対象HTML表のデータ行番号です。新列を列名のあるCSVから捨てずに取り込み、列数不一致や重複ヘッダーは停止します。Game Logs・気象の固定書式が変わった場合も原本を残して停止します。

重複した業務キーは報告します。SQLiteは原行の連番を主キーにしているため、勝手な重複削除で消えません。人物のID結合は一意の完全一致だけで、未一致・複数候補は別の状態になります。日本の候補表には外部IDがないので、自動結合していません。

## 実行した確認

取得した全28原本をオフラインで再検査し、同じ件数と内容のDBを再構築しました。検査コードのテストは、破損キャッシュ、指紋不一致、空応答・途中切断・サイズ上限、権利ゲート、条件資料の失敗による本体停止、429/403、危険なURL/転送、CSV書式、気象の品質表記・24時、曖昧なID、得点・アウト矛盾、DB再構築と前版保持を対象にしています。

Linuxクラウドで実行しています。Windows実機で収集コマンドやDB閲覧の動作確認はしていません。追加ライブラリやAPIキーは不要で、既存のNumPy・pandas・Streamlit・pytestを変更せず利用できます。
