# 第2段階の検証記録

検証日：2026-10-21。Linuxクラウド / Python 3.12.14。Windows実機では未検証です。

- `python -m pytest -q`：**61件成功**（収集基盤16件＋既存45件）。8.21秒。
- 全28原本のSHA256とバイト数を `lock.json` / `manifest.json` / 実ファイル間で照合：一致。
- オフライン再構築：通信0回、28キャッシュを再検査。5データセットの件数と品質検査結果が一致。連続再実行でSQLite・品質JSON・配布ZIPのバイト列も一致。
- 配布ZIPのCRC検査：正常。収録SQLiteのSHA256は `bundle.json` と一致。
- 配布SQLiteの `integrity_check`：ok。`foreign_key_check`：問題なし。
- ZIP収録DBの行数：games 2,429 / plays 2,612 / people 693 / japan_board 18 / weather 24。quality.jsonと一致。
- 全試合ログのイニング別得点集計、32試合のプレー照合、人物593件のID一意結合：不一致・曖昧な対応0。
- 原本、条件、書式の最終取得失敗0。条件確認で保留した対象と初回のサイズ上限停止は別途記録。
- README・新設文書のローカルリンク：欠落0。`git diff --check`：問題なし。

ファイルごとの指紋は [manifest.json](../../data_sources/pilot/manifest.json)、検査の詳細と列別プロファイルは [quality.json](../../data_sources/pilot/quality.json) にあります。標本内で整合していることと、独立検証・全期間の完全性・モデルの妥当性は別です。
