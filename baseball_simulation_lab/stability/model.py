"""Same window/outcome/route draws, plus an explicit independent order generator."""
from dataclasses import replace
import hashlib,json
from pathlib import Path

from ..calibrated.rules import canonical, frame_dict, Move, Plan, UnsupportedRule
from ..completion.model import GameModel as PreviousModel, bind, NoRoute, Draw
from ..fullgame.model import assumed_play
from .probability import legal_terminal
from .timeline import generate
from .rules import Credit, Play, realize, apply_play

PA_CLASSES=('single','double','triple','home_run','sacrifice_bunt','sacrifice_fly','hit_by_pitch','walk',
            'strikeout','interference','reached_on_error','fielders_choice','other_out')


def terminal_play(frame,rng):
    if not legal_terminal(frame.outs*8+frame.base_mask):raise ValueError('Not enough runners for a no-PA third out')
    needed=3-frame.outs
    # Choose distinct identities once. This models hypothetical pickoff/tag outs,
    # not the identities of unobserved real-world double/triple retirements.
    retired=set(rng.sample([r.player_id for r in frame.bases if r],needed))
    moves=tuple(Move(r.player_id,i,'OUT' if r.player_id in retired else 'LOB') for i,r in enumerate(frame.bases,1) if r)
    plan=Plan('caught_stealing',moves,False,'assumption','generated-no-pa-retirements-1')
    return Play(plan,Credit(False,source='assumption'),event_text='GENERATED_TAG_RETIREMENTS')


class GameModel(PreviousModel):
    def __init__(self,previous,support,probability_policy='posterior_support'):
        if probability_policy not in ('posterior_support','mle_baseline'):raise ValueError('Unknown probability policy')
        self.previous=previous;self.support=support;self.probability_policy=probability_policy
        self.base=previous.base;self.routes=previous.routes;self.terminal=previous.terminal;self._choices={}
        if support['training_seasons']!=[2023,2024]:raise ValueError('2025 cannot train posterior support')
        if set(support['states'])!={str(i) for i in range(24)}:raise ValueError('24 posterior states required')
        for pre in range(24):
            c=support['states'][str(pre)]
            original=self.terminal['states'][str(pre)]
            if c['exposure']!=original['exposure'] or c['half_end_no_pa']!=original['half_end_no_pa']:
                raise ValueError('Posterior counts differ from frozen 2023-2024 cohort')
            expected=(c['half_end_no_pa']+.5)/(c['exposure']+1) if legal_terminal(pre) else 0.
            if c['p']!=expected:raise ValueError('Posterior differs from declared Jeffreys estimator')
            if c['legal']!=legal_terminal(pre) or (c['p']>0)!=c['legal'] or not 0<=c['p']<1:
                raise ValueError('Posterior structural support is invalid')
        self.version='stability-model-1:'+hashlib.sha256(canonical({'parent':previous.version,'support':support,
            'policy':probability_policy,'pa_classes':PA_CLASSES,'timing':'legal-linear-extension-1'}).encode()).hexdigest()

    @classmethod
    def load(cls,stage7,stage9_dir,support_path,probability_policy='posterior_support'):
        from ..empirical.common import sha_file
        manifest=json.loads((Path(support_path).parent/'support_manifest.json').read_text())
        if sha_file(support_path)!=manifest['support_sha256']:raise ValueError('Support model checksum mismatch')
        previous=PreviousModel.load(stage7,Path(stage9_dir)/'routes.json.gz',Path(stage9_dir)/'terminal_model.json')
        if previous.version!=manifest['parent_stage9_model_version']:raise ValueError('Parent Stage 9 version mismatch')
        return cls(previous,json.loads(Path(support_path).read_text()),probability_policy)

    def predict_pa(self,frame,**actors):
        original=self.previous.predict_pa(frame,**actors)
        total=sum(original[k] for k in PA_CLASSES)
        return {k:original[k]/total for k in PA_CLASSES}

    def predict_step(self,frame,**actors):
        p=self.predict_pa(frame,**actors);pre=frame.outs*8+frame.base_mask
        q=(self.support['states'][str(pre)]['p'] if self.probability_policy=='posterior_support'
           else self.terminal['states'][str(pre)]['p_half_end_no_pa'])
        return {**{k:(1-q)*v for k,v in p.items()},'runner_only_end':q}

    def resolve_outcome(self,frame,outcome,rng,*,allow_assumptions=False,probability=1.):
        if outcome not in (*PA_CLASSES,'runner_only_end'):raise UnsupportedRule('unknown_PA_taxonomy: quarantine, never map to an arbitrary out')
        rows=self.previous.choices(frame,outcome,allow_assumptions)
        if not rows:
            if outcome=='runner_only_end' and allow_assumptions and legal_terminal(frame.outs*8+frame.base_mask):
                actions=None;source='assumption';reference='generated-no-pa-retirements-1'
                selected=terminal_play(frame,rng)
            else:raise NoRoute(outcome,{'pre_state':frame.outs*8+frame.base_mask,'training_n':0,'allow_assumptions':allow_assumptions})
        else:
            actions,_,source,reference=rng.choices(rows,weights=[r[1] for r in rows],k=1)[0]
            selected=assumed_play(frame,outcome) if source=='assumption' else None
        mapping={'B':frame.batter,**{str(i):r.player_id for i,r in enumerate(frame.bases,1) if r}}
        plays=[]
        for index,action in enumerate(actions if actions is not None else [None]):
            if frame.finished:break
            p=selected if action is None else bind(action,mapping,source,reference)
            try:
                if allow_assumptions:p=realize(frame,p,generate(frame,p,rng))
                frame=apply_play(frame,p).transition.after
            except ValueError as exc:
                exc.context={'route_ref':reference,'source':source,'action_index':index,'attempted_action':action,
                    'attempted_frame':frame_dict(frame),'generated_timeline':getattr(p,'timeline',None).to_dict() if getattr(p,'timeline',None) else None,'original_source':self.routes['sources'].get(reference)}
                raise
            plays.append(p)
        return Draw(outcome,tuple(plays),probability,reference)

    def support_report(self,frame,*,allow_assumptions=False,**actors):
        pre=frame.outs*8+frame.base_mask
        return [{'outcome':k,'probability':p,'empirical_n':sum(r[1] for r in self.previous.choices(frame,k,False)),
                 'generated_terminal_available':k=='runner_only_end' and allow_assumptions and legal_terminal(pre),
                 'declared_assumption':any(r[2]=='assumption' for r in self.previous.choices(frame,k,allow_assumptions))}
                for k,p in self.predict_step(frame,**actors).items()]
