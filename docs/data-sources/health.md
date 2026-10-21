# 疲労・成長・動作・故障研究

[台帳トップへ](README.md)

| ID | 候補 | 優先度 | 資料 | 入口接続 |
|---|---|---|---|---|
| [S077](#s077) | OpenBiomechanics：投球 | C | 資料確認済み | reachable |
| [S078](#s078) | OpenBiomechanics：打撃 | C | 資料確認済み | reachable |
| [S079](#s079) | OpenBiomechanics：身体評価 | C | 資料確認済み | reachable |
| [S080](#s080) | MLB Pitch Smart：投球負荷の指針 | B | 資料確認済み | reachable |
| [S081](#s081) | ASMI：投球・故障・動作研究 | B | 一次資料未確認 | reachable |
| [S082](#s082) | Driveline Research：研究資料 | C | 資料確認済み | reachable |
| [S083](#s083) | MLB公式：Transactions | B | 資料確認済み | reachable |
| [S084](#s084) | MLB injuryコミュニティ調査パイプライン | C | 資料確認済み | reachable |

## S077

**OpenBiomechanics：投球** — 動作・関節・力学・球速等の匿名化研究データ。

- 提供元グループ: `driveline` / 種類: `dataset` / 対象: 大学・高校・MiLB・独立リーグ
- 入口: https://github.com/drivelineresearch/openbiomechanics/tree/main/baseball_pitching
- 収録範囲: 資料上411投球・100選手、速球のみ、主に大学レベル。
- 取得方法・形式: データシートとライセンス全文を確認し、採用可否を先に判断する。大容量資産は未取得。 / CSV・C3D・時系列
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: CC BY-NC-SA 4.0 + 追加の利用者条件（restricted）。コードMITとは別。READMEに商用制限と、プロスポーツ組織・金融分析企業の関係者等への追加制限を記載。現行全文と用途を確認するまでモデルへの採用を保留。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: session_pitch・user
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 実験室の標本をプロリーグ全体へ直接一般化しない。 / 同一選手の複数試行を独立選手として学習・評価しない。 / モジュールを氏名で再識別・結合しない。
- 確認資料: [投球・打撃・身体計測の構成、約1.1GBの大容量配布、データの非商用・追加制限を確認](https://raw.githubusercontent.com/drivelineresearch/openbiomechanics/HEAD/README.md)
- 確認資料: [参加者・競技レベル・球種の偏りと、匿名IDの結合制限を確認](https://raw.githubusercontent.com/drivelineresearch/openbiomechanics/HEAD/DATASHEET.md)
- 確認資料: [データ・関連文書のライセンス全文と、非商用・追加の利用者条件を確認。](https://raw.githubusercontent.com/drivelineresearch/openbiomechanics/HEAD/LICENSE-DATA.md)

## S078

**OpenBiomechanics：打撃** — スイング・打球・動作の研究データ。

- 提供元グループ: `driveline` / 種類: `dataset` / 対象: 大学・高校・MiLB・独立リーグ
- 入口: https://github.com/drivelineresearch/openbiomechanics/tree/main/baseball_hitting
- 収録範囲: 資料上677スイング・98選手、HitTrax対応604行。
- 取得方法・形式: データシートとライセンス全文を確認し、採用可否を先に判断する。大容量資産は未取得。 / CSV・C3D・時系列
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: CC BY-NC-SA 4.0 + 追加の利用者条件（restricted）。コードMITとは別。READMEに商用制限と、プロスポーツ組織・金融分析企業の関係者等への追加制限を記載。現行全文と用途を確認するまでモデルへの採用を保留。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: session_swing・user
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 実験室の標本をプロリーグ全体へ直接一般化しない。 / 同一選手の複数試行を独立選手として学習・評価しない。 / モジュールを氏名で再識別・結合しない。
- 確認資料: [投球・打撃・身体計測の構成、約1.1GBの大容量配布、データの非商用・追加制限を確認](https://raw.githubusercontent.com/drivelineresearch/openbiomechanics/HEAD/README.md)
- 確認資料: [参加者・競技レベル・球種の偏りと、匿名IDの結合制限を確認](https://raw.githubusercontent.com/drivelineresearch/openbiomechanics/HEAD/DATASHEET.md)
- 確認資料: [データ・関連文書のライセンス全文と、非商用・追加の利用者条件を確認。](https://raw.githubusercontent.com/drivelineresearch/openbiomechanics/HEAD/LICENSE-DATA.md)

## S079

**OpenBiomechanics：身体評価** — フォースプレート・可動域等の身体評価。

- 提供元グループ: `driveline` / 種類: `dataset` / 対象: 大学・高校・MiLB・独立リーグ
- 入口: https://github.com/drivelineresearch/openbiomechanics/tree/main/high_performance
- 収録範囲: 資料上1934評価・1162選手。投打の公開IDとは人物対応表なし。
- 取得方法・形式: データシートとライセンス全文を確認し、採用可否を先に判断する。大容量資産は未取得。 / CSV・C3D・時系列
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: CC BY-NC-SA 4.0 + 追加の利用者条件（restricted）。コードMITとは別。READMEに商用制限と、プロスポーツ組織・金融分析企業の関係者等への追加制限を記載。現行全文と用途を確認するまでモデルへの採用を保留。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: athlete_uid・assessment
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 実験室の標本をプロリーグ全体へ直接一般化しない。 / 同一選手の複数試行を独立選手として学習・評価しない。 / モジュールを氏名で再識別・結合しない。
- 確認資料: [投球・打撃・身体計測の構成、約1.1GBの大容量配布、データの非商用・追加制限を確認](https://raw.githubusercontent.com/drivelineresearch/openbiomechanics/HEAD/README.md)
- 確認資料: [参加者・競技レベル・球種の偏りと、匿名IDの結合制限を確認](https://raw.githubusercontent.com/drivelineresearch/openbiomechanics/HEAD/DATASHEET.md)
- 確認資料: [データ・関連文書のライセンス全文と、非商用・追加の利用者条件を確認。](https://raw.githubusercontent.com/drivelineresearch/openbiomechanics/HEAD/LICENSE-DATA.md)

## S080

**MLB Pitch Smart：投球負荷の指針** — 年代別の投球数・休養の指針を確認する参考資料。

- 提供元グループ: `mlb` / 種類: `reference` / 対象: 育成年代
- 入口: https://www.mlb.com/pitch-smart/pitching-guidelines
- 収録範囲: 対象年齢・指針改訂日ごとの資料を確認する。
- 取得方法・形式: 公式指針の版・根拠文献を調査。 / HTML・PDF候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 指針版・年齢区分
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 育成年代への指針を成人プロ投手の因果係数として直接使わない。
- 確認資料: [MLBの年代別投球数・休養の推奨指針を確認。成人プロの係数として直接使わない。](https://www.mlb.com/pitch-smart/pitching-guidelines)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S081

**ASMI：投球・故障・動作研究** — 投球動作・負荷・故障等の研究と原論文を探す入口。

- 提供元グループ: `asmi` / 種類: `research_index` / 対象: 野球研究
- 入口: https://asmi.org/research/
- 収録範囲: 論文ごとに対象者・年代・競技レベルが異なる。
- 取得方法・形式: 研究一覧からDOI・対象集団・公開データをたどる。 / HTML・論文メタデータ
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 一次資料未確認 / 入口 reachable / 本体サンプル未取得
- 結合キー候補: DOI・研究ID候補
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 論文に記載された結果と、再利用できる個票データを区別。 / 本文調査ではHTTP 403。接続チェックの一回の成功を継続取得可能と扱わない。
- 別途の本文確認: HTTP 403。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S082

**Driveline Research：研究資料** — 育成・投球・打球の研究や技術的解説を探す入口。

- 提供元グループ: `driveline` / 種類: `research_index` / 対象: 野球研究
- 入口: https://www.drivelinebaseball.com/research/
- 収録範囲: 記事・研究ごとの公開範囲。
- 取得方法・形式: 主張の根拠・標本・検証方法・公開データの有無を整理。 / HTML・参考文献
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 記事URL・DOI候補
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 企業の解説・主観的見解・査読研究を同じ証拠強度としない。
- 確認資料: [Drivelineの研究・開発活動と公開論文等への参照を確認。主張の根拠は論文別に要確認。](https://www.drivelinebaseball.com/research/)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S083

**MLB公式：Transactions** — IL・昇降格・契約等の公表された日付情報の候補。

- 提供元グループ: `mlb` / 種類: `dataset` / 対象: MLB
- 入口: https://www.mlb.com/transactions
- 収録範囲: 過去日付・リーグ・異動区分による取得範囲を確認。
- 取得方法・形式: 公式表示とStats API経由の仕様を調査。 / HTML・JSON候補
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: person ID・transaction ID・effective date
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: IL登録・復帰日と故障発症日・完治日・診断内容は一致しない。
- 確認資料: [MLB Transactionsの公式公開入口を確認。データ取得・過去時点の網羅性は未確認。](https://www.mlb.com/transactions)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。

## S084

**MLB injuryコミュニティ調査パイプライン** — 故障関連の取得元・加工方法を調べるための候補リポジトリ。

- 提供元グループ: `injury_capstone` / 種類: `portal` / 対象: MLB
- 入口: https://github.com/LA-Dodgers-Capstone-Team/API-Web-Scraper-Pipeline
- 収録範囲: GitHub検索で発見。本文・対象年・データ条件は未確認。
- 取得方法・形式: README・元提供元・医学的ラベルの定義を調べる。 / 未確認
- 料金・認証: 料金・認証・自動取得条件は未確認。
- 条件: unknown（needs_review）。公開閲覧・取得可能性と、学習・再配布・商用利用の許諾は別途確認。
- 状態: 資料確認済み / 入口 reachable / 本体サンプル未取得
- 結合キー候補: 未確認
- 次の確認: 一次資料の利用条件・実収録期間・配布形式を確認し、第2段階の少量取得候補を決める。
- 注意点: 学習済みモデルの推定値を実測の故障診断として使わない。 / 医学的な個票の有無を確認し、非公開情報を収集対象にしない。
- 確認資料: [リポジトリの説明・ノートブック類の存在を確認。データ出典・利用条件は未確認。](https://github.com/LA-Dodgers-Capstone-Team/API-Web-Scraper-Pipeline)
- 別途の本文確認: HTTP 200。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。
