"""Bounded, cached Wikipedia article sampling. No NPB roster scraping.

Raw HTML and normalized real-person records stay in ignored data/research.
Only CC BY-SA article pages allowed by robots are fetched, serially.
"""
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlparse
from urllib.robotparser import RobotFileParser
from datetime import datetime, timezone
import hashlib, json, re, time, random, math

ROOT = Path(__file__).resolve().parents[1]
TEAMS = ('読売ジャイアンツ','阪神タイガース','横浜DeNAベイスターズ','広島東洋カープ',
         '東京ヤクルトスワローズ','中日ドラゴンズ','福岡ソフトバンクホークス',
         '北海道日本ハムファイターズ','千葉ロッテマリーンズ','東北楽天ゴールデンイーグルス',
         'オリックス・バファローズ','埼玉西武ライオンズ')
POSITIONS = {'投手':'P','捕手':'C','内野手':'IF','外野手':'OF'}
UA = 'BaseballProfileResearch/0.1 (bounded aggregate research; serial cached requests)'

def new_stage_path(path):
    path=Path(path).resolve()
    for prefix in ('data/research','data_sources','docs'):
        for stage in ('pilot','warehouse',*(f'stage{i}' for i in range(1,12)),*(f'data-stage{i}' for i in range(1,12))):
            old=(ROOT/prefix/stage).resolve()
            if path.is_relative_to(old) or old.is_relative_to(path):raise ValueError('Previous-stage output or ancestor is protected')
    return path

def dump(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')

class Fetcher:
    def __init__(self, root, config):
        self.root = new_stage_path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.config = config; self.last = 0.; self.new_requests = 0
        self.robots = RobotFileParser()
        robots = self.get('https://ja.wikipedia.org/robots.txt', check=False)
        self.robots.parse(robots.splitlines())
        # Re-read the license before any article population acquisition.
        self.get('https://ja.wikipedia.org/wiki/Wikipedia:'+quote('著作権'))

    def get(self, url, check=True):
        if urlparse(url).netloc != 'ja.wikipedia.org': raise ValueError('Only reviewed host allowed')
        if check and not self.robots.can_fetch(UA, url): raise ValueError('robots.txt denies '+url)
        key = hashlib.sha256(url.encode()).hexdigest(); meta = self.root/(key+'.json'); raw = self.root/(key+'.html')
        if meta.exists():
            m = json.loads(meta.read_text())
            if m['status'] != 200: raise ValueError('Previously failed URL: '+url)
            b = raw.read_bytes()
            if hashlib.sha256(b).hexdigest() != m['sha256']: raise ValueError('Raw cache modified')
            return b.decode('utf-8')
        if self.new_requests >= self.config['maximum_new_requests']: raise ValueError('Research request budget exhausted')
        time.sleep(max(0., self.config['request_interval_seconds']-(time.monotonic()-self.last)))
        self.new_requests += 1
        try:
            with urlopen(Request(url, headers={'User-Agent':UA}), timeout=40) as response:
                if urlparse(response.url).netloc != 'ja.wikipedia.org': raise ValueError('Unreviewed redirect')
                b = response.read(4_000_001)
                if len(b)>4_000_000: raise ValueError('Article exceeds request size limit')
                status = response.status
        except HTTPError as exc:
            dump(meta, {'url':url,'status':exc.code,'retrieved_at':datetime.now(timezone.utc).isoformat()})
            if exc.code in (401,403,429): raise RuntimeError('Access restriction; acquisition stopped') from exc
            raise
        finally: self.last = time.monotonic()
        raw.write_bytes(b)
        dump(meta, {'url':url,'status':status,'retrieved_at':datetime.now(timezone.utc).isoformat(),
                    'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'license':'CC BY-SA 4.0; Wikipedia contributors'})
        return b.decode('utf-8')

def roster(text, year, team, url):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(text, 'html.parser'); heading = soup.find(id='選手・スタッフ')
    if heading is None: raise ValueError('No season roster heading')
    # Some years omit an explicit 支配下 header; the initial position lists
    # precede a separately labelled 育成 section. Preserve this source definition.
    table = heading.find_next('table'); rows = []; group = 'primary'
    for tr in table.find_all('tr'):
        th = tr.find('th', recursive=False)
        if th is None: continue
        label = th.get_text(' ',strip=True)
        if label == '支配下選手': group = 'primary'; continue
        if label == '育成選手': group = 'development'; continue
        if label in POSITIONS and group:
            td = tr.find('td', recursive=False)
            if td is None: continue
            for a in td.find_all('a'):
                href = a.get('href','')
                if href.startswith('https://ja.wikipedia.org/wiki/'): href = urlparse(href).path
                if href.startswith('./'): href = '/wiki/'+href[2:]
                if not href.startswith('/wiki/') or ':' in unquote(href[len('/wiki/'):]): continue
                if 'new' in a.get('class',[]): continue
                title = unquote(href.split('/wiki/',1)[1].split('#')[0])
                rows.append({'year':year,'team':team,'registration':group,'position':POSITIONS[label],
                             'source_position_label':label,'title':title,'source_url':url,
                             'membership_definition':'listed in Wikipedia season player/staff navbox, including departures/promotion notes'})
    if not rows: raise ValueError('No classified roster players')
    return rows

def parse_profile(text, url):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(text, 'html.parser'); box = soup.select_one('table.infobox')
    if box is None: raise ValueError('No player infobox')
    fields = {}
    for tr in box.find_all('tr'):
        th = tr.find('th', recursive=False); td = tr.find('td', recursive=False)
        if th and td:
            for sup in td.find_all('sup'): sup.decompose()
            fields[th.get_text('',strip=True)] = td.get_text(' ',strip=True)
    def number(label, unit):
        value = fields.get(label,'') or next((v for k,v in fields.items() if label in k),'')
        match = re.search(r'(\d+(?:\.\d+)?)\s*'+unit,value)
        return float(match[1]) if match else None
    hand = fields.get('投球・打席',''); throws = re.search(r'([右左])投',hand); bats = re.search(r'([右左両])打',hand)
    born = box.select_one('.bday'); dob = born.get_text(strip=True) if born else None
    if not dob:
        m = re.search(r'(\d{4})年\s*(\d+)月\s*(\d+)日',fields.get('生年月日',''))
        if m: dob=f'{int(m[1]):04}-{int(m[2]):02}-{int(m[3]):02}'
    nationality = fields.get('国籍') or None
    group = 'unknown'
    if nationality and not any(word in nationality for word in ('亡命','不明','非公開')):
        group = 'japan' if nationality.strip() == '日本' else 'multiple' if '日本' in nationality else 'non_japan'
    oldid = next((a.get('href') for a in soup.find_all('a') if 'oldid=' in a.get('href','')),None)
    canonical=soup.find('link',rel='canonical')
    canonical_url=canonical.get('href') if canonical else url
    return {'height_cm':number('身長','cm'),'weight_kg':number('体重','kg'),'birth_date':dob,'canonical_url':canonical_url,
            'throws':{'右':'R','左':'L'}.get(throws[1]) if throws else None,
            'bats':{'右':'R','左':'L','両':'S'}.get(bats[1]) if bats else None,
            'raw_handedness':hand,'nationality_text':nationality,'citizenship_group':group,
            'raw_position':fields.get('ポジション'),'draft_text':fields.get('プロ入り'),
            'source_url':url,'article_revision_link':oldid,'measurement_date':None,
            'profile_time_definition':'article observation at retrieval; not historical annual measured body values'}

def collect(config=None, root=None):
    config = config or json.loads((ROOT/'data_sources/stage11_5/config.json').read_text())
    root = new_stage_path(root or ROOT/'data/research/stage11_5'); fetch = Fetcher(root/'raw',config)
    memberships=[]; failures=[]; coverage=[]
    for year in config['years']:
        for team in TEAMS:
            title = f'{year}年の{team}'; url='https://ja.wikipedia.org/wiki/'+quote(title)
            try:
                text=fetch.get(url); rows=roster(text,year,team,url); memberships.extend(rows)
                coverage.append({'year':year,'team':team,'rows':len(rows),'status':'parsed','url':url})
            except (HTTPError,ValueError) as exc:
                coverage.append({'year':year,'team':team,'rows':0,'status':'unavailable','url':url,'error':str(exc)})
            print(f'roster {year} {team}: {coverage[-1]["rows"]}',flush=True)
    # Stratify across union of all five article years. Never replace a missing
    # profile by another player or choose seeds for favorable statistics.
    cells={}
    for r in memberships: cells.setdefault((r['team'],r['registration'],r['position']),set()).add(r['title'])
    selected=set(); not_selected_probability={}
    sampling=[]
    for key,titles in sorted(cells.items()):
        k=min(len(titles),config['primary_per_team_position'] if key[1]=='primary' else config['development_per_team_position'])
        seed=hashlib.sha256(json.dumps([config['sampling_seed'],key],ensure_ascii=False).encode()).digest()
        chosen=random.Random(seed).sample(sorted(titles),k);selected.update(chosen)
        sampling.append({'team':key[0],'registration':key[1],'position':key[2],'population':len(titles),'sample':k})
        for title in titles:not_selected_probability[title]=not_selected_probability.get(title,1.)*(1-k/len(titles))
    dump(root/'memberships.json',memberships);dump(root/'coverage.json',coverage);dump(root/'sampling.json',sampling)
    profiles={}
    for i,title in enumerate(sorted(selected)):
        url='https://ja.wikipedia.org/wiki/'+quote(title)
        try:
            p=parse_profile(fetch.get(url),url);p['inclusion_probability']=1-not_selected_probability[title];profiles[title]=p
        except (HTTPError,ValueError) as exc:failures.append({'title':title,'url':url,'error':str(exc)})
        print(f'profile {i+1}/{len(selected)} {title}: {"ok" if title in profiles else "missing"}',flush=True)
        dump(root/'profiles.json',profiles);dump(root/'profile_failures.json',failures)
    dump(root/'collection.json',{'selected_unique_players':len(selected),'parsed_profiles':len(profiles),'new_requests':fetch.new_requests,
                               'raw_originals_public':False,'sampling_plan_frozen_before_acquisition':config})
    return root

def reparse_cached(root=None):
    """Rebuild parser outputs from verified original bytes, without HTTP."""
    root=new_stage_path(root or ROOT/'data/research/stage11_5');profiles=json.loads((root/'profiles.json').read_text())
    for title,p in profiles.items():
        key=hashlib.sha256(p['source_url'].encode()).hexdigest();meta=json.loads((root/'raw'/(key+'.json')).read_text())
        raw=(root/'raw'/(key+'.html')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise ValueError('Original was modified')
        profiles[title]={**parse_profile(raw.decode('utf-8'),p['source_url']),'inclusion_probability':p['inclusion_probability']}
    dump(root/'profiles.json',profiles)
    memberships=json.loads((root/'memberships.json').read_text())
    for r in memberships:
        if 'official_position_label' in r:r['source_position_label']=r.pop('official_position_label')
    dump(root/'memberships.json',memberships)
    return len(profiles)

if __name__=='__main__':collect()
