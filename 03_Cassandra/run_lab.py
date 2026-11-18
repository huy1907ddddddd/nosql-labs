"""Run SensorRing steps 0-4 on the dedicated nosql-lab03 cluster."""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
RESULT={}


def docker(*args):
    p=subprocess.run(['docker','compose','-f',str(HERE/'compose.yaml'),*args],
                     capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)
    if p.returncode:
        raise RuntimeError(p.stdout+p.stderr)
    return p.stdout


def cql(node,query):
    # Docker CLI on Windows mishandles multiline -e arguments; CQL needs no newlines.
    return docker('exec','-T',node,'cqlsh','--request-timeout=120','--connect-timeout=30','-e',' '.join(query.splitlines()))


def node(node,*args):
    return docker('exec','-T',node,'nodetool',*args)


def save(name,text):
    (HERE/name).write_text(text,encoding='utf-8')


def wait_healthy(names=('cass1','cass2','cass3')):
    end=time.monotonic()+300
    while time.monotonic()<end:
        raw=docker('ps','--format','json')
        if raw.strip().startswith('['):
            states=json.loads(raw)
        else:
            states=[json.loads(x) for x in raw.splitlines() if x.strip()]
        healthy={s['Service'] for s in states if s.get('Health')=='healthy'}
        if set(names)<=healthy:
            return
        time.sleep(5)
    raise TimeoutError('Cassandra healthcheck did not become healthy: '+str(names))


def wait_ring(live,coordinator='cass1'):
    end=time.monotonic()+180
    while time.monotonic()<end:
        status=node(coordinator,'status')
        if len(re.findall(r'^UN\s',status,re.M))==live and len(re.findall(r'^DN\s',status,re.M))==3-live:
            return status
        time.sleep(3)
    raise TimeoutError('Gossip did not reach expected live-node count')


def exercises():
    # Execute schema changes separately after node recovery, with a generous timeout.
    statements=(HERE/'exercises.cql').read_text(encoding='utf-8').split(';')
    for statement in statements:
        if statement.strip():
            cql('cass1',statement.strip()+';')
    output=cql('cass1',"SELECT * FROM iot.latest_orders_by_customer WHERE customer_id='C01' LIMIT 10; SELECT * FROM iot.orders_by_day WHERE day='2026-11-17'; SELECT * FROM iot.readings_by_sensor_month WHERE sensor_id='hn-01' AND month='2026-10';")
    assert output.count('(1 rows)')==3,output
    save('exercises-output.txt',output)
    print('PASS exercises: customer orders, orders per day, monthly sensor bucket',flush=True)


def main():
    wait_healthy()
    status=wait_ring(3)
    save('step0-status.txt',status)
    print('STEP 0: three nodes healthy and UN',flush=True)
    # The entire compose project is an isolated scratch cluster for this lab.
    cql('cass1','DROP KEYSPACE IF EXISTS iot; DROP KEYSPACE IF EXISTS ring1;')
    import sensorring as sr
    from cassandra import ConsistencyLevel, Unavailable
    from cassandra.query import SimpleStatement
    sr.setup()
    sr.load()
    n=sr.session.execute('SELECT count(*) FROM iot.readings_by_sensor').one()[0]
    assert n==3000
    RESULT['loaded_rows']=n
    print('PASS 0: 3000 rows / 30 sensors',flush=True)

    cql('cass1',"CREATE KEYSPACE ring1 WITH replication={'class':'SimpleStrategy','replication_factor':1}; CREATE TABLE ring1.sensors(sensor_id text PRIMARY KEY);")
    tokens={r.sensor_id:r[1] for r in sr.session.execute("SELECT DISTINCT sensor_id,token(sensor_id) FROM iot.readings_by_sensor")}
    ring=node('cass1','ring')
    save('step1-ring.txt',ring)
    owner_tokens=[]
    for line in ring.splitlines():
        parts=line.split()
        if len(parts)>=7 and re.match(r'^\d+\.\d+\.\d+\.\d+$',parts[0]) and re.fullmatch(r'-?\d+',parts[-1]):
            owner_tokens.append((int(parts[-1]),parts[0]))
    owner_tokens.sort()
    assert owner_tokens, 'No token ring parsed'
    endpoints={}
    for i in range(1,7):
        sensor=f'hn-{i:02d}'
        sr.session.execute('INSERT INTO ring1.sensors(sensor_id) VALUES (%s)',(sensor,))
        endpoint=node('cass1','getendpoints','ring1','sensors',sensor).strip()
        endpoints[sensor]=endpoint
    for sensor in ('hn-01','hn-02'):
        expected=next((ip for token,ip in owner_tokens if token>=tokens[sensor]),owner_tokens[0][1])
        assert expected==endpoints[sensor],(sensor,expected,endpoints[sensor])
    rf3=node('cass1','getendpoints','iot','readings_by_sensor','hn-01').strip().splitlines()
    assert len(rf3)==3
    RESULT['tokens']={s:tokens[s] for s in ('hn-01','hn-02')}
    RESULT['ring1_endpoints']=endpoints
    RESULT['rf3_endpoints']=rf3
    save('step1-ownership.txt',node('cass1','status','ring1')+'\n'+node('cass1','status','iot'))
    print('PASS 1: RF1 ownership:',endpoints,'; checked clockwise rule for hn-01 and hn-02',flush=True)

    try:
        sr.session.execute('SELECT * FROM iot.readings_by_sensor WHERE temperature>31.5')
    except Exception as e:
        RESULT['missing_partition_error']=type(e).__name__+': '+str(e)
        save('step2-rejected-query.txt',RESULT['missing_partition_error'])
        assert type(e).__name__=='InvalidRequest'
    else:
        raise AssertionError('Query without partition key should be rejected')
    partition=cql('cass1',"PAGING OFF; CONSISTENCY ONE; TRACING ON; SELECT ts,temperature FROM iot.readings_by_sensor WHERE sensor_id='hn-01' LIMIT 3;")
    scan=cql('cass1',"PAGING OFF; CONSISTENCY ONE; TRACING ON; SELECT count(*) FROM iot.readings_by_sensor WHERE temperature>31.5 ALLOW FILTERING;")
    save('step2-partition-trace.txt',partition)
    save('step2-scan-trace.txt',scan)
    matched=sr.session.execute('SELECT count(*) FROM iot.readings_by_sensor WHERE temperature>31.5 ALLOW FILTERING').one()[0]
    def rows_read(text):
        return sum(int(n) for n in re.findall(r'Read (\d+) live rows',text))
    RESULT['trace']={'partition_rows_read':rows_read(partition),'scan_rows_read':rows_read(scan),'matched_rows':matched,
                     'partition_request_us':re.findall(r'Request complete[^\n]*',partition),
                     'scan_request_us':re.findall(r'Request complete[^\n]*',scan)}
    assert 'single-partition' in partition
    assert ('range' in scan or 'seq scan' in scan)
    print('PASS 2:',RESULT['trace'],flush=True)

    def levels():
        result={}
        for name in ('ONE','QUORUM','ALL'):
            cl=getattr(ConsistencyLevel,name)
            try:
                sr.session.execute(SimpleStatement("INSERT INTO iot.readings_by_sensor(sensor_id,ts,temperature,humidity) VALUES('cl-test',toTimestamp(now()),25,60)",consistency_level=cl))
                count=sr.session.execute(SimpleStatement("SELECT count(*) FROM iot.readings_by_sensor WHERE sensor_id='cl-test'",consistency_level=cl)).one()[0]
                result[name]={'status':'OK','rows':count}
            except Unavailable as e:
                result[name]={'status':'Unavailable','required':e.required_replicas,'alive':e.alive_replicas}
        return result
    RESULT['consistency']={'3':levels()}
    assert [v['status'] for v in RESULT['consistency']['3'].values()]==['OK','OK','OK']
    docker('stop','cass3')
    save('step3-two-live.txt',wait_ring(2))
    RESULT['consistency']['2']=levels()
    assert [v['status'] for v in RESULT['consistency']['2'].values()]==['OK','OK','Unavailable']
    docker('stop','cass2')
    save('step3-one-live.txt',wait_ring(1))
    RESULT['consistency']['1']=levels()
    assert [v['status'] for v in RESULT['consistency']['1'].values()]==['OK','Unavailable','Unavailable']
    print('PASS 3:',json.dumps(RESULT['consistency']),flush=True)
    sr.cluster.shutdown()

    docker('start','cass2')
    wait_healthy(('cass1','cass2'))
    wait_ring(2)
    node('cass1','disablehandoff')
    node('cass2','disablehandoff')
    cql('cass1',"CONSISTENCY QUORUM; INSERT INTO iot.readings_by_sensor(sensor_id,ts,temperature,humidity) VALUES('hn-99','2026-11-01 09:00:00',41,30);")
    docker('start','cass3')
    wait_healthy()
    wait_ring(3)
    docker('stop','cass1','cass2')
    wait_ring(1,'cass3')
    stale=cql('cass3',"CONSISTENCY ONE; SELECT * FROM iot.readings_by_sensor WHERE sensor_id='hn-99';")
    save('step4-stale.txt',stale)
    assert '(0 rows)' in stale,stale
    docker('start','cass1','cass2')
    wait_healthy()
    wait_ring(3,'cass3')
    fresh=cql('cass3',"CONSISTENCY ALL; SELECT * FROM iot.readings_by_sensor WHERE sensor_id='hn-99';")
    save('step4-fresh.txt',fresh)
    assert '(1 rows)' in fresh and '41' in fresh,fresh
    repair=node('cass3','repair','iot')
    save('step4-repair.txt',repair)
    for n in ('cass1','cass2','cass3'):
        node(n,'enablehandoff')
    RESULT['stale_rows']=0
    RESULT['fresh_rows']=1
    save('results.json',json.dumps(RESULT,indent=2))
    print('PASS 4: stale ONE=0 rows; ALL=1 row; repair completed',flush=True)
    # Three short end-of-lesson exercises, executed without adding an app.
    exercises()
    save('results.json',json.dumps(RESULT,indent=2))
    print('ALL SENSORRING STEPS PASSED',flush=True)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='exercises':
        exercises()
    else:
        main()
