import copy
import io
import json
from pathlib import Path
import sqlite3
from urllib.error import HTTPError
import zipfile

import pytest

from data_collection import adapters as a
from data_collection import fetch
from data_collection.__main__ import database


RIGHTS = {'open': {'pilot_collection_allowed': True, 'attribution': 'Test'}}
SPEC = {'id': 'test', 'url': 'https://example.org/data.csv', 'purpose': 'data',
        'max_bytes': 1000, 'rights': 'open'}


class Response(io.BytesIO):
    status = 200
    url = SPEC['url']

    def __init__(self, data, declared_size=None):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data) if declared_size is None else declared_size)}


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def install(monkeypatch, responses):
    opener = Opener(responses)
    monkeypatch.setattr(fetch, 'build_opener', lambda *args: opener)
    monkeypatch.setattr(fetch.time, 'sleep', lambda n: None)
    return opener


def test_rights_gate_happens_before_network(tmp_path, monkeypatch):
    opener = install(monkeypatch, [])
    c = fetch.Collector(tmp_path, {'open': {'pilot_collection_allowed': False}})
    with pytest.raises(fetch.CollectionError, match='rights review'):
        c.fetch(SPEC)
    assert opener.calls == 0


def test_cache_is_verified_and_offline_does_not_request(tmp_path, monkeypatch):
    opener = install(monkeypatch, [Response(b'a,b\n1,2\n')])
    data, meta = fetch.Collector(tmp_path, RIGHTS).fetch(SPEC)
    c = fetch.Collector(tmp_path, RIGHTS, offline=True)
    assert c.fetch({**SPEC, 'expected_sha256': meta['sha256']})[0] == data
    assert c.cache_hits == 1 and opener.calls == 1
    (tmp_path / 'blobs' / meta['sha256']).write_bytes(b'corruption')
    with pytest.raises(fetch.CollectionError, match='mismatch'):
        c.fetch(SPEC)
    assert opener.calls == 1


def test_checksum_rejects_changed_upstream_before_cache_publish(tmp_path, monkeypatch):
    install(monkeypatch, [Response(b'changed')])
    with pytest.raises(fetch.CollectionError, match='pinned checksum'):
        fetch.Collector(tmp_path, RIGHTS).fetch({**SPEC, 'expected_sha256': '0' * 64})
    assert not (tmp_path / 'index' / 'test.json').exists()


@pytest.mark.parametrize('payload,declared,cap', [(b'', 0, 100), (b'short', 8, 100), (b'oversized', 9, 4)])
def test_empty_truncated_or_oversized_payload_is_not_accepted(tmp_path, monkeypatch, payload, declared, cap):
    install(monkeypatch, [Response(payload, declared)])
    with pytest.raises(fetch.CollectionError):
        fetch.Collector(tmp_path, RIGHTS).fetch({**SPEC, 'max_bytes': cap})
    assert not (tmp_path / 'index' / 'test.json').exists()


def test_retry_transient_status_but_not_forbidden(tmp_path, monkeypatch):
    transient = HTTPError(SPEC['url'], 429, 'rate limited', {'Retry-After': '0'}, None)
    opener = install(monkeypatch, [transient, Response(b'good')])
    fetch.Collector(tmp_path, RIGHTS).fetch(SPEC)
    assert opener.calls == 2
    denied = HTTPError(SPEC['url'], 403, 'forbidden', {}, None)
    opener = install(monkeypatch, [denied])
    with pytest.raises(fetch.CollectionError, match='HTTP 403'):
        fetch.Collector(tmp_path / 'denied', RIGHTS).fetch(SPEC)
    assert opener.calls == 1


def test_insecure_credentialed_or_cross_host_redirect_is_rejected():
    for url in ['http://example.org/data', 'https://user:secret@example.org/data']:
        with pytest.raises(fetch.CollectionError):
            fetch.safe_url(url)
    with pytest.raises(fetch.CollectionError, match='allowlist'):
        fetch.Redirects(['example.org']).redirect_request(None, None, 302, '', {}, 'https://other.org/x')


def test_csv_preserves_unknown_columns_empty_values_and_unicode():
    rows = list(a.csv_rows(io.StringIO('id,new_field,empty\n1,東京,\n')))
    assert rows == [(2, {'id': '1', 'new_field': '東京', 'empty': ''})]
    with pytest.raises(fetch.CollectionError, match='field count'):
        list(a.csv_rows(io.StringIO('id,value\n1\n')))
    with pytest.raises(fetch.CollectionError, match='duplicate'):
        list(a.csv_rows(io.StringIO('id,id\n1,2\n')))


def test_zip_reads_only_exact_member_without_extracting_paths(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as z:
        z.writestr('../escape.csv', 'id\n1\n')
    with pytest.raises(fetch.CollectionError, match='named ZIP member'):
        list(a.zipped_csv(data.getvalue(), 'expected.csv'))
    assert not (tmp_path / 'escape.csv').exists()


def test_duplicate_and_structural_empty_fields_remain_visible():
    rows = [a.record('test', '', 1, {'id': '1', 'runner': '', 'snow': '--'})] * 2
    p = a.profile(rows, ['id'])
    assert p['duplicate_keys'] == 1 and p['duplicate_full_rows'] == 1
    assert p['column_profiles']['runner']['empty_cells'] == 2
    assert p['column_profiles']['snow']['marker_counts'] == {'--': 2}
    assert a.linescore('010000(10)0x') == 11


def test_identity_join_never_guesses_from_name_or_ambiguous_id():
    plays = [a.record('test', '', 1, {'batter': 'a', 'pitcher': 'b'})]
    people = [a.record('test', '', n, {'key_retro': 'a', 'key_uuid': str(n), 'key_mlbam': '9'}) for n in (1, 2)]
    result = a.identity_join(plays, people)
    assert result['status_counts'] == {'ambiguous': 1, 'unmatched': 1}
    assert all(r['key_uuid'] is None for r in result['rows'])


def test_weather_keeps_flags_alt_text_and_24h_crosses_midnight():
    cells = ['24'] + ['12.3 )'] * 13 + ['<img alt="晴">', '', '--']
    rows = []
    for hour in range(1, 25):
        cells[0] = str(hour)
        rows.append('<tr>' + ''.join(f'<td class="data_0_1">{c}</td>' for c in cells) + '</tr>')
    data = ('東京（東京都) 2024年3月29日<table id="tablefix1">' + ''.join(rows) + '</table>').encode()
    values = a.weather(data)[-1]['values']
    assert values['timestamp_jst'] == '2024-03-30T00:00:00+09:00'
    assert values['timestamp_utc'] == '2024-03-29T15:00:00+00:00'
    assert values['temperature_c'] == '12.3 )' and values['weather'] == '晴'
    assert values['cell_attributes']['temperature_c']['class'] == 'data_0_1'


def test_database_rebuild_is_idempotent_and_duplicates_are_not_dropped(tmp_path):
    path = tmp_path / 'pilot.sqlite3'
    artifact = {'id': 'test', 'sha256': 'a' * 64}
    row = a.record('test', '', 1, {'key_uuid': 'same'})
    for _ in range(2):
        database(path, [artifact], {'people': [row, row]}, {'rows': []})
        with sqlite3.connect(path) as db:
            assert db.execute('select count(*) from people').fetchone()[0] == 2
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    before = path.read_bytes()
    with pytest.raises(sqlite3.IntegrityError):
        database(path, [], {'people': [row]}, {'rows': []})
    assert path.read_bytes() == before


def synthetic_game():
    gid = 'HOM202401010'
    g = {'game_id': gid, 'field_004': 'AWY', 'field_007': 'HOM',
         'field_010': '0', 'field_011': '1', 'field_012': '51'}
    rows = []
    for half in range(18):
        last = half == 17
        v = {'gid': gid, 'pn': str(half + 1), 'inning': str(half // 2 + 1),
             'top_bot': str(half % 2), 'vis_home': str(half % 2),
             'batteam': 'HOM' if half % 2 else 'AWY', 'outs_pre': '0',
             'outs_post': '0' if last else '3', 'score_v': '0', 'score_h': '0',
             'runs': '1' if last else '0', 'pbp': 'full', 'date': '20240101'}
        rows.append(a.record('test', '', half + 1, v))
    return [a.record('test', '', 1, g)], rows, {gid: ['fixture']}


def test_real_score_and_outs_validation_detects_corrupt_transitions():
    games, plays, selected = synthetic_game()
    assert a.validate_plays(games, plays, selected)['failures'] == []
    corrupt = copy.deepcopy(plays)
    corrupt[2]['values']['score_v'] = '1'
    corrupt[3]['values']['outs_pre'] = '1'
    result = a.validate_plays(games, corrupt, selected)
    assert {r['check'] for r in result['failures']} >= {'score_transition', 'half_inning_outs', 'total_outs'}


def test_unavailable_policy_evidence_skips_dependent_data_and_preserves_db(tmp_path, monkeypatch):
    from argparse import Namespace
    from data_collection import __main__ as runner
    policy = {'pilot_collection_allowed': True, 'attribution': 'Test', 'evidence_artifacts': ['policy']}
    plan = {'budget_bytes': 10000, 'sample_game_limit': 1, 'rights': {'open': policy},
            'artifacts': [{**SPEC, 'id': 'policy', 'purpose': 'evidence'}, {**SPEC, 'id': 'payload'}]}
    plan_path = tmp_path / 'plan.json'
    plan_path.write_text(json.dumps(plan))
    old = tmp_path / 'data' / 'pilot.sqlite3'
    old.parent.mkdir()
    old.write_bytes(b'previous-valid-snapshot')
    calls = []

    class FailingCollector:
        network_requests = 1
        cache_hits = 0
        def __init__(self, *args, **kwargs):
            pass
        def fetch(self, spec):
            calls.append(spec['id'])
            raise fetch.CollectionError('HTTP 503')

    monkeypatch.setattr(runner, 'Collector', FailingCollector)
    args = Namespace(plan=plan_path, output=old.parent, report_dir=tmp_path / 'report', offline=False, record_lock=True)
    with pytest.raises(fetch.CollectionError, match='2 artifact'):
        runner.run(args)
    assert calls == ['policy']
    assert old.read_bytes() == b'previous-valid-snapshot'
    result = json.loads((args.report_dir / 'last_failure.json').read_text())
    assert 'Rights evidence unavailable' in result['errors'][1]['error']
