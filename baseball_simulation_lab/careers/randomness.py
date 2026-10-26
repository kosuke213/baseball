"""Independent, keyed streams. No future draws are stored on player profiles."""
import hashlib,hmac,json,random


def keyed(root,kind,player_id,scope,version='career-rng-1'):
    if type(root) is not int or root<0:raise ValueError('Nonnegative private root seed required')
    secret=root.to_bytes(max(32,(root.bit_length()+7)//8),'big')
    message=json.dumps([version,kind,player_id,scope],ensure_ascii=False,separators=(',',':')).encode()
    return random.Random(int.from_bytes(hmac.new(secret,message,hashlib.sha256).digest(),'big'))


def event_seed(root,kind,player_id,scope):return keyed(root,kind,player_id,scope).getrandbits(63)
