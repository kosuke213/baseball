"""Posterior support is an explicit generative option, not an accuracy claim."""
import math


def legal_terminal(pre):
    outs,bases=divmod(pre,8)
    return bases.bit_count()>=3-outs


def _fraction(a,b,x):
    tiny=1e-300;qab=a+b;qap=a+1;qam=a-1;c=1.;d=1-qab*x/qap
    if abs(d)<tiny:d=tiny
    d=1/d;h=d
    for m in range(1,400):
        m2=2*m;aa=m*(b-m)*x/((qam+m2)*(a+m2));d=1+aa*d;c=1+aa/c
        if abs(d)<tiny:d=tiny
        if abs(c)<tiny:c=tiny
        d=1/d;h*=d*c
        aa=-(a+m)*(qab+m)*x/((a+m2)*(qap+m2));d=1+aa*d;c=1+aa/c
        if abs(d)<tiny:d=tiny
        if abs(c)<tiny:c=tiny
        d=1/d;change=d*c;h*=change
        if abs(change-1)<3e-12:return h
    raise ArithmeticError('Incomplete beta did not converge')


def beta_cdf(x,a,b):
    if x<=0:return 0.
    if x>=1:return 1.
    scale=math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)+a*math.log(x)+b*math.log1p(-x))
    if x<(a+1)/(a+b+2):return scale*_fraction(a,b,x)/a
    return 1-scale*_fraction(b,a,1-x)/b


def beta_quantile(q,a,b):
    lo=0.;hi=1.
    for _ in range(65):
        mid=(lo+hi)/2
        if beta_cdf(mid,a,b)<q:lo=mid
        else:hi=mid
    return (lo+hi)/2


def fit(cells,alpha=.5):
    states={}
    for pre in range(24):
        c=cells[str(pre)];n=c['exposure'];k=c['half_end_no_pa'];legal=legal_terminal(pre)
        a=k+alpha;b=n-k+alpha
        states[str(pre)]={'exposure':n,'half_end_no_pa':k,'legal':legal,
            'prior_alpha':alpha if legal else None,'prior_beta':alpha if legal else None,
            'p':a/(a+b) if legal else 0.,'posterior_95':[beta_quantile(.025,a,b),beta_quantile(.975,a,b)] if legal else [0.,0.]}
    return {'version':'terminal-posterior-1','training_seasons':[2023,2024],'states':states,
        'selection':'Jeffreys Beta(.5,.5), opt-in coverage policy; predictive MLE baseline remains available',
        'prior_is_assumption':True,'legal_mask':'starting runner count >= outs needed; no completed PA or new batter-runner',
        'limits':['support improvement, not established predictive accuracy improvement','multi-retirement routes may be generated, never labelled observed']}
