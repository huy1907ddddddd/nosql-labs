"""TicketRush lab: one file, one disposable Redis on port 6389."""
import json
import os
import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import redis

r = redis.Redis.from_url(os.getenv('REDIS_URL', 'redis://127.0.0.1:6389/0'),
                        decode_responses=True, max_connections=600)


def reset():
    # Only this lab's keys are removed, never FLUSHDB on an existing database.
    keys = list(r.scan_iter('lab02:*'))
    if keys:
        r.delete(*keys)


def race(fn, n=50):
    start = threading.Barrier(n)
    def go(i):
        start.wait(timeout=60)
        return fn(i)
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(go, range(n)))


def hold_naive(event, seat, user):
    key = f'lab02:hold:{event}:{seat}'
    if r.get(key) is None:
        time.sleep(0.01)
        r.set(key, user, ex=300)
        return True
    return False


def hold_nx(event, seat, user, ttl=300):
    return bool(r.set(f'lab02:hold:{event}:{seat}', user, nx=True, ex=ttl))


HOLD = r.register_script("""
if redis.call('SISMEMBER', KEYS[2], ARGV[2]) == 1 then return 0 end
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[3]) then return 1 end
return 0
""")
CONFIRM = r.register_script("""
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('SADD', KEYS[2], ARGV[2])
  redis.call('DEL', KEYS[1])
  return 1
end
return 0
""")
RELEASE = r.register_script("""
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
""")


def hold(event, seat, user, ttl=300):
    return bool(HOLD(keys=[f'lab02:hold:{event}:{seat}', f'lab02:sold:{event}'], args=[user, seat, ttl]))


def confirm(event, seat, user):
    return bool(CONFIRM(keys=[f'lab02:hold:{event}:{seat}', f'lab02:sold:{event}'], args=[user, seat]))


def release(event, seat, user):
    return bool(RELEASE(keys=[f'lab02:hold:{event}:{seat}'], args=[user]))


def seat_map(event, seats):
    sold = r.smembers(f'lab02:sold:{event}')
    return {s: 'sold' if s in sold else 'held' if r.exists(f'lab02:hold:{event}:{s}') else 'free' for s in seats}


def buy_general(event, user):
    left = r.decr(f'lab02:stock:{event}')
    if left < 0:
        r.incr(f'lab02:stock:{event}')
        return False
    r.sadd(f'lab02:buyers:{event}', user)
    return True


def buy_general_naive(event, user):
    if int(r.get(f'lab02:stock:{event}')) > 0:
        time.sleep(0.01)
        r.decr(f'lab02:stock:{event}')
        return True
    return False


def allow_fixed(user, limit=5, window=10):
    key = f'lab02:rl:fixed:{user}:{int(time.time() // window)}'
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window, nx=True)
    count, _ = pipe.execute()
    return count <= limit


SLIDING = r.register_script("""
local now, window, limit = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
if redis.call('ZCARD', KEYS[1]) < limit then
  redis.call('ZADD', KEYS[1], now, ARGV[4])
  redis.call('PEXPIRE', KEYS[1], window)
  return 1
end
return 0
""")


def allow_sliding(user, limit=5, window_ms=10000):
    return bool(SLIDING(keys=[f'lab02:rl:sliding:{user}'],
                        args=[int(time.time() * 1000), window_ms, limit, uuid.uuid4().hex]))


def try_hold(event, seat, user):
    if not allow_sliding(user):
        return 'rate_limited'
    return 'ok' if hold(event, seat, user) else 'taken'


def join_queue(event, user):
    r.zadd(f'lab02:queue:{event}', {user: time.time()}, nx=True)
    return r.zrank(f'lab02:queue:{event}', user) + 1


def admit(event, n):
    return [user for user, _ in r.zpopmin(f'lab02:queue:{event}', n)]


def boundary(fn, user):
    time.sleep((9.8 - time.time() % 10) % 10)
    first = [fn(user) for _ in range(5)]
    time.sleep(0.4)
    return first + [fn(user) for _ in range(5)]


def main():
    r.ping()
    reset()
    results = {}
    results['naive_winners'] = []
    for _ in range(3):
        reset()
        results['naive_winners'].append(sum(race(lambda i: hold_naive('c1', 'A1', f'u{i}'))))
    reset()
    results['nx_winners'] = sum(race(lambda i: hold_nx('c1', 'A1', f'u{i}')))
    results['hold_ttl'] = r.ttl('lab02:hold:c1:A1')
    assert results['nx_winners'] == 1 and results['hold_ttl'] > 0
    print('PASS 1: naive winners', results['naive_winners'], '; NX winners', results['nx_winners'], '; TTL', results['hold_ttl'])
    reset()
    story = [hold('c1','A1','linh'), hold('c1','A1','nam'), confirm('c1','A1','nam'),
             confirm('c1','A1','linh'), hold('c1','A1','nam')]
    assert story == [True, False, False, True, False]
    assert seat_map('c1',['A1','A2']) == {'A1':'sold','A2':'free'}
    assert hold('c1','A2','linh') and not release('c1','A2','nam') and release('c1','A2','linh')
    assert hold('c1','A3','linh',ttl=1)
    time.sleep(1.1)
    assert hold('c1','A3','nam')
    results['owner_checks'] = story
    print('PASS 2: owner checks', story, '; release and TTL expiry OK')
    reset()
    r.set('lab02:stock:g1',100)
    ok = race(lambda i: buy_general('g1', f'u{i}'), n=500)
    results['general_admission'] = [sum(ok),int(r.get('lab02:stock:g1')),r.scard('lab02:buyers:g1')]
    assert results['general_admission'] == [100,0,100]
    # Only one ticket so the incorrect GET/DECR version reliably oversells.
    r.set('lab02:stock:bad',1)
    results['naive_oversell'] = sum(race(lambda i: buy_general_naive('bad',f'u{i}')))
    print('PASS 3: sold / remaining / buyers', results['general_admission'], '; naive sold from stock=1:',results['naive_oversell'])
    reset()
    fixed = [allow_fixed('linh') for _ in range(8)]
    assert fixed == [True]*5+[False]*3
    results['fixed_boundary'] = boundary(allow_fixed,'bot-fixed')
    results['sliding_boundary'] = boundary(allow_sliding,'bot-sliding')
    assert results['fixed_boundary'] == [True]*10
    assert results['sliding_boundary'] == [True]*5+[False]*5
    bot_results = race(lambda i: try_hold('bots',f'B{i}','same-bot'), n=50)
    assert bot_results.count('ok') == 5 and bot_results.count('rate_limited') == 45
    results['bot_test'] = {x:bot_results.count(x) for x in set(bot_results)}
    print('PASS 4: fixed boundary', results['fixed_boundary'])
    print('        sliding boundary', results['sliding_boundary'], '; bot:',results['bot_test'])
    reset()
    positions = [join_queue('c1',u) for u in ['u1','u2','u3']]
    assert positions == [1,2,3] and join_queue('c1','u1') == 1
    assert admit('c1',2) == ['u1','u2'] and join_queue('c1','u3') == 1
    print('PASS 5: queue positions',positions,'; rejoin preserves position; admit FIFO')
    results['stress'] = []
    for attempt in range(10):
        reset()
        seats = [f'S{i}' for i in range(1,21)]
        def buyer(i):
            user = f'user{i}'
            for seat in seats:
                if hold('c1',seat,user):
                    time.sleep(random.random()*0.05)
                    if confirm('c1',seat,user):
                        return seat
            return None
        got = [s for s in race(buyer,n=100) if s]
        counts = [len(got),len(set(got)),r.scard('lab02:sold:c1')]
        assert counts == [20,20,20]
        results['stress'].append(counts)
        print(f'PASS 6.{attempt+1}: sold / distinct / set = {counts}')
    (Path(__file__).resolve().parent/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
