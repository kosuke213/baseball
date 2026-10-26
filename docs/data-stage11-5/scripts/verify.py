"""Verify delivered public parameters and saved local histories independently.

Requires the administrator-only research artifacts in this workspace; does not
publish them. No network, probability fitting or historical resampling occurs.
"""
from pathlib import Path
import sys,json,hashlib,subprocess,shutil,tempfile,platform,sqlite3,re
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from data_collection.npb_profiles import dump
out=ROOT/'data_sources/stage11_5';rawroot=ROOT/'data/research/stage11_5'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
base='522aa7507d0d6330a0ab45eba84959f7baf5128c'
oldpaths=subprocess.check_output(['git','ls-tree','-r','--name-only',base],cwd=ROOT,text=True).splitlines()
changed=subprocess.check_output(['git','diff','--name-only',base,'--',*oldpaths],cwd=ROOT,text=True).strip()
assert not changed,changed
count=0
for meta in (rawroot/'raw').glob('*.json'):
    m=json.loads(meta.read_text())
    if m['status']==200:assert sha(meta.with_suffix('.html'))==m['sha256'];count+=1
folder=Path(tempfile.mkdtemp(prefix='baseball-stage11-5-independent-'))
for name in ('baseball_simulation_lab','data_collection'):
    shutil.copytree(ROOT/name,folder/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(folder/'data_sources/stage11_5').mkdir(parents=True)
shutil.copy2(out/'parameters.json',folder/'data_sources/stage11_5/parameters.json')
script='''import sys,json
from pathlib import Path
from dataclasses import asdict
from baseball_simulation_lab.npb_profiles.model import Distribution,initial_rosters
from baseball_simulation_lab.npb_profiles.storage import PhysicalStore,public_player
from baseball_simulation_lab.careers.storage import CareerStore
from baseball_simulation_lab.careers.domain import state_dict
from baseball_simulation_lab.careers.public import player_view
from baseball_simulation_lab.calibrated.rules import canonical
from baseball_simulation_lab.stability.model import GameModel
def forbidden(*args,**kwargs):raise AssertionError('Probability model unexpectedly required')
GameModel.load=forbidden
root=Path(sys.argv[1]);out=Path(sys.argv[2]);store=CareerStore(root/'private_careers.sqlite3');body=PhysicalStore(root/'physical.sqlite3')
w=store.restore('npb-profile-world');generated=initial_rosters(w.world_id,w.created_on,115026,distribution=Distribution.load())
for e in generated:
 pid=e.profile.player_id
 assert asdict(e.profile)==asdict(w.profiles[pid])
 assert state_dict(e.state)==state_dict(w.current(pid))
 assert asdict(e.talent)==asdict(w.talents[pid])
 assert asdict(e.physical)==body.profiles[pid]['physical']
public=[public_player(player_view(e.profile,w.current(e.profile.player_id),w.now),body.at(e.profile.player_id,w.now)) for e in generated]
assert canonical(public)==canonical(json.loads((out/'fictional_players.json').read_text()))
count=0
for gid, in store.db.execute('SELECT game_id FROM games ORDER BY game_id'):store.load(gid);count+=1
for forbidden_key in ('private_talent','current_internal','maturation_offset','private_root_seed'):
 assert forbidden_key not in json.dumps(public)
assert not Path('data_sources/stage7').exists()
print(json.dumps({'players_regenerated_exactly':len(generated),'profile_state_talent_and_body_equal':True,
 'saved_games_replayed':count,'public_dtos_equal':True,'third_party_site_packages_required':False,
 'probability_model_files_present_or_loaded':False}))
store.close();body.close()'''
private=rawroot/'compatibility';before={n:sha(private/n) for n in ('physical.sqlite3','private_careers.sqlite3')}
r=subprocess.run([sys.executable,'-S','-c',script,str(private),str(out)],cwd=folder,text=True,capture_output=True)
assert r.returncode==0,(r.stdout,r.stderr)
independent=json.loads(r.stdout)
assert before=={n:sha(private/n) for n in before}
testlog=Path('/tmp/stage11-5-pytest-final.log').read_text();match=re.search(r'(\d+) passed in ([\d.]+)s',testlog);assert match
assert int(match[1])==593
assert not any(p.suffix in ('.sqlite3','.db','.html') for p in out.rglob('*') if p.is_file())
sourcefiles=sorted((ROOT/'baseball_simulation_lab/npb_profiles').glob('*.py'))+[ROOT/'data_collection/npb_profiles.py']
fingerprint=hashlib.sha256(json.dumps({str(p.relative_to(ROOT)):sha(p) for p in sourcefiles},sort_keys=True).encode()).hexdigest()
verification={'base_commit':base,'old_tracked_files_unchanged':len(oldpaths),'all_old_tracked_files_preserved':True,
 'raw_documents_sha256_verified':count,'model_parameter_sha256':json.loads((out/'parameters.json').read_text())['parameter_sha256'],
 'implementation_sha256':fingerprint,'independent_directory':str(folder),'independent_standard_library_run':independent,
 'new_saved_databases_unchanged_by_replay':True,'private_databases_in_public_directory':False,
 'old_history_replay':json.loads((out/'legacy_replay.json').read_text()),
 'tests':{'passed':int(match[1]),'old_retained':567,'new':26,'elapsed_seconds':float(match[2])},
 'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'windows_native_tested':False,
 'scope':'experimental sampled listed profiles, not official NPB census or calibrated rookie/body-ability/platoon model'}
dump(out/'verification.json',verification)
# Private snapshot manifest includes source originals and real-person linkage;
# only this hash and a public-output manifest are published, never those records.
private_files={str(p.relative_to(rawroot)):sha(p) for p in sorted(rawroot.rglob('*')) if p.is_file() and 'plot-cache' not in p.parts and p.name!='final_manifest.json'}
dump(rawroot/'final_manifest.json',{'files':private_files,'privacy':'local research/admin artifacts, do not publish'})
dump(out/'build.json',{'base_commit':base,'implementation_sha256':fingerprint,'parameter_sha256':verification['model_parameter_sha256'],
 'private_manifest_sha256':sha(rawroot/'final_manifest.json'),'public_artifact_sha256':{p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file() and p.name!='build.json'}})
print(json.dumps(verification,ensure_ascii=False,indent=2))
