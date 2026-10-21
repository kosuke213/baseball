"""Local experiment UI. Run from the repository root with Streamlit."""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import time
import pandas as pd
import streamlit as st

from baseball_simulation_lab.domain import Environment, PARKS, Rules, Weather
from baseball_simulation_lab.engine import Game
from baseball_simulation_lab.generation import generate_world
from baseball_simulation_lab.model import ModelSettings, RuleBasedModel
from baseball_simulation_lab.reporting import game_row, summarize
from baseball_simulation_lab.storage import Store


def score_view(view, names):
    st.subheader(f"{names[0]}  {view['score'][0]} — {view['score'][1]}  {names[1]}")
    st.caption(f"{view['inning']}回{'表' if view['half']=='top' else '裏'} · {view['outs']}アウト · {view['balls']}ボール {view['strikes']}ストライク · 総投球数 {view['pitches']}")
    st.table(pd.DataFrame(view["line_score"], index=names,
                         columns=[str(i+1) for i in range(len(view["line_score"][0]))]).fillna("—"))
    base_labels = ["一塁", "二塁", "三塁"]
    st.write(" / ".join(f"{base_labels[i]}: {r['player_id'] if r else '空'}" for i, r in enumerate(view["bases"])))
    st.write(f"打者: {view['batter_id']} / 投手: {view['pitcher_id']}（{view['pitcher_pitches']}球）")
    if view["finished"]:
        st.success(f"試合終了: {view['ending']}")


def event_frame(events):
    return pd.DataFrame([{
        "順": e["sequence"], "回": e["before"]["inning"], "表裏": e["before"]["half"],
        "打者": e.get("batter_id", ""), "投手": e.get("pitcher_id", ""),
        "カウント前": f"{e['before']['balls']}-{e['before']['strikes']}",
        "投球": e.get("pitch", "交代"), "結果": e.get("result", str(e.get("substitution", ""))),
        "得点後": str(e["after"]["score"]), "アウト後": e["after"]["outs"],
    } for e in events])


def statistics(result):
    st.write("打撃成績（PA=打席、AB=打数、SF=犠飛）")
    st.dataframe(pd.DataFrame(result["batting"]).T, width="stretch")
    st.write("投手成績（outs=投球アウト数。投球回の小数表記ではありません）")
    st.dataframe(pd.DataFrame(result["pitching"]).T, width="stretch")


def choose_lineup(team):
    with st.expander(f"{team.name} のスタメン・守備位置"):
        defense = {}
        for pos, current in team.defense.items():
            eligible = [p.player_id for p in team.players if p.category == "batter" and (pos == "DH" or pos in [p.position, *p.secondary_positions])]
            defense[pos] = st.selectbox(pos, eligible, index=eligible.index(current),
                                       key=f"{team.team_id}-{pos}", format_func=lambda pid: team.player(pid).name)
        choices = list(dict.fromkeys(defense.values()))
        order = st.multiselect("打順（選択した順。9人を指定）", choices,
                               default=[pid for pid in team.lineup if pid in choices], key=f"order-{team.team_id}",
                               format_func=lambda pid: team.player(pid).name)
        # When defensive choices change, the previous order can include an old player.
        team.lineup = order
        team.defense = defense
        pitchers = [p.player_id for p in team.players if p.category == "pitcher"]
        team.starter_id = st.selectbox("先発", pitchers, key=f"starter-{team.team_id}", format_func=lambda pid: team.player(pid).name)
    return team


def main():
    st.set_page_config(page_title="架空野球シミュレーション実験室", layout="wide")
    st.title("架空野球シミュレーション実験室")
    st.caption("すべて架空の球団・選手です。Phase 1 の仮説モデルで、現実の統計による較正はまだ行っていません。")
    db = Path("data/lab.sqlite3")
    with Store(db) as store:
        if not store.conn.execute("SELECT 1 FROM world").fetchone():
            store.initialize(generate_world())
        teams = store.initial_teams()
        names = [t.name for t in teams]
        page = st.sidebar.radio("画面", ["ダッシュボード", "試合実験", "保存試合・リプレイ", "開発者"])
        if page == "ダッシュボード":
            st.subheader("球団・選手")
            st.write(" / ".join(f"{t.name}（{len(t.players)}人）" for t in teams))
            st.dataframe(pd.DataFrame(store.public_players()), width="stretch", hide_index=True)
            ids = store.game_ids()
            st.subheader(f"保存試合 {len(ids)}件")
            recent = [store.load(gid) for gid in ids[:10]]
            st.dataframe(pd.DataFrame([{"game_id": r["game_id"], "away": r["snapshot"]["teams"][0]["name"], "home": r["snapshot"]["teams"][1]["name"], "score": str(r["final"]["score"]), "ending": r["final"]["ending"]} for r in recent]), width="stretch")
            if recent:
                st.write("直近の試合の個人成績")
                statistics(recent[0])
            return
        if page == "保存試合・リプレイ":
            ids = store.game_ids()
            if not ids:
                st.info("試合実験で試合を完了すると、ここに保存されます。")
                return
            gid = st.selectbox("試合ID", ids)
            result = store.load(gid)
            names = [t["name"] for t in result["snapshot"]["teams"]]
            events = result["events"]
            position = st.slider("ログの再表示（0=試合開始）", 0, len(events), len(events))
            view = events[position-1]["after"] if position else events[0]["before"]
            score_view(view, names)
            st.dataframe(event_frame(events[max(0, position-30):position]), width="stretch", hide_index=True)
            statistics(result)
            st.download_button("一球ログCSV", event_frame(events).to_csv(index=False).encode("utf-8-sig"), "events.csv", "text/csv")
            return

        if page == "開発者":
            st.warning("ローカル開発者画面です。認証機能ではありません。一般公開用サーバーとして使用しないでください。")
            players = {p.player_id: p for t in teams for p in t.players}
            pid = st.selectbox("内部特性を確認する選手", list(players))
            st.json({"latent": asdict(players[pid].latent), "ability": asdict(players[pid].ability), "state": asdict(players[pid].state)})
            sample = Game(*teams)
            st.write("試合開始条件での一球確率")
            st.json(sample.model.predict_probabilities(players[sample.batter_id], players[sample.pitcher_id], sample.state, sample.environment))
            repetitions = st.number_input("確率サンプル数", 100, 1000000, 10000, 100)
            if st.button("指定打者と先発投手の確率を大量試行"):
                import numpy as np
                batter = players[pid]
                if batter.category != "batter":
                    st.error("野手を選択してください。")
                else:
                    start = time.perf_counter()
                    probs = sample.model.predict_probabilities(batter, players[sample.pitcher_id], sample.state, sample.environment)
                    counts = np.random.default_rng(42).multinomial(int(repetitions), list(probs.values()))
                    st.dataframe(pd.DataFrame({"outcome": list(probs), "probability": list(probs.values()), "observed_count": counts}))
                    st.write(f"処理時間: {time.perf_counter()-start:.4f} 秒")
            if "game" in st.session_state:
                st.write("進行中／直近の試合の内部状態・ログ")
                st.json(st.session_state.game.view())
                st.dataframe(event_frame(st.session_state.game.events), width="stretch")
            return

        st.subheader("試合設定")
        seed = st.number_input("乱数シード", min_value=0, max_value=2147483647, value=42)
        park = st.selectbox("球場", PARKS, format_func=lambda p: p.name)
        temperature = st.slider("気温（℃）", -20, 45, 20)
        wind = st.slider("風速（m/s）", 0.0, 20.0, 0.0)
        wind_direction = st.slider("風向（0=センター方向、180=本塁方向）", 0, 360, 0)
        max_innings = st.slider("延長上限", 9, 20, 12)
        extra_runner = st.checkbox("延長は無死二塁から開始")
        hr_scale = st.slider("仮説モデル：本塁打係数", 0.1, 3.0, 1.0, 0.1)
        fatigue_scale = st.slider("仮説モデル：疲労効果係数", 0.0, 3.0, 1.0, 0.1)
        starter_limit = st.slider("先発の自動交代投球数", 40, 150, 90)
        prepared = [choose_lineup(deepcopy(t)) for t in teams]
        st.caption("守備選手を変更した場合は、打順も9人に揃えてください。設定は「新しい試合」で反映します。")
        rules = Rules(max_innings=max_innings, extra_runner=extra_runner, starter_pitch_limit=starter_limit)
        environment = Environment(park, Weather(temperature, wind, wind_direction))
        model = RuleBasedModel(ModelSettings(hr_scale, fatigue_scale))
        if st.button("新しい試合", type="primary"):
            try:
                st.session_state.game = Game(*prepared, seed=int(seed), rules=rules, environment=environment, model=model)
            except ValueError as exc:
                st.error(str(exc))
        if "game" in st.session_state:
            game = st.session_state.game
            if not game.state.finished:
                col1, col2 = st.columns(2)
                if col1.button("1球進める"):
                    game.step()
                if col2.button("最後まで進める"):
                    progress = st.empty()
                    while not game.state.finished:
                        game.step()
                        if game.state.pitches % 50 == 0:
                            progress.caption(f"{game.state.inning}回 {game.state.pitches}球を処理")
                    progress.empty()
            if game.state.finished:
                store.save(game)
            score_view(game.view(), [t.name for t in game.teams])
            st.dataframe(event_frame(game.events[-20:]), width="stretch", hide_index=True)
            if game.state.finished:
                statistics(game.result())
            elif game.state.balls == game.state.strikes == 0:
                with st.expander("手動交代（打席の間のみ）"):
                    side = 1-game.batting_side
                    candidates = [p.player_id for p in game.teams[side].players if p.category == "pitcher" and p.player_id not in game.used_pitchers[side]]
                    if candidates:
                        choice = st.selectbox("救援投手", candidates)
                        if st.button("投手交代"):
                            game.change_pitcher(choice)
                            st.rerun()
                    batting_side = st.selectbox("打者交代の球団", [0, 1], format_func=lambda s: game.teams[s].name)
                    slot = st.selectbox("打順の枠（1〜9）", list(range(9)), format_func=lambda s: str(s+1))
                    bench = [p.player_id for p in game.teams[batting_side].players if p.category == "batter" and p.player_id not in game.used_batters[batting_side]]
                    if bench:
                        replacement = st.selectbox("控え野手", bench)
                        if st.button("打者交代"):
                            try:
                                game.replace_batter(batting_side, slot, replacement)
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))

        st.subheader("独立した条件での一括実験")
        count = st.number_input("試合数", 1, 1000, 100)
        st.caption("同じ初期状態から独立試行し、ホーム・ビジターを交互に入れ替えます。全試合の一球ログをDB保存します。")
        if st.button("一括実行"):
            try:
                for team in prepared:
                    team.validate()
                started = time.perf_counter()
                rows = []
                progress = st.progress(0)
                for i in range(int(count)):
                    pair = prepared if i % 2 == 0 else list(reversed(prepared))
                    g = Game(*pair, seed=int(seed)+i, rules=rules, environment=environment, model=model).run()
                    store.save(g)
                    rows.append(game_row(g))
                    progress.progress((i+1)/int(count))
                summary = summarize(rows)
                st.json(summary)
                st.write(f"処理時間: {time.perf_counter()-started:.2f} 秒")
                st.download_button("集計CSV", pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"), "games.csv", "text/csv")
            except ValueError as exc:
                st.error(str(exc))


if __name__ == "__main__":
    main()
