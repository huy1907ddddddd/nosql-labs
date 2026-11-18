"""CampusGraph - seven tasks, using the dataset and check supplied by CADA."""
import json
import os
import sys
from pathlib import Path
from neo4j import GraphDatabase

URI = os.getenv('NEO4J_URI', 'bolt://127.0.0.1:7688')
AUTH = (os.getenv('NEO4J_USER', 'neo4j'), os.getenv('NEO4J_PASSWORD', 'learnneo4j'))
driver = GraphDatabase.driver(URI, auth=AUTH)
COURSES = [
    ('CS101','Intro to Programming',3),('MATH101','Calculus',3),
    ('MATH102','Linear Algebra',3),('STAT101','Probability and Statistics',3),
    ('CS102','Data Structures',3),('DB201','Databases',3),
    ('VIZ201','Data Visualization',2),('ML201','Machine Learning',4),
    ('DE301','Data Engineering',3),('DB301','NoSQL Databases',3),
    ('DL301','Deep Learning',4),('NLP401','Natural Language Processing',3),
    ('CAP401','Capstone Project',6),
]
REQUIRES = [('MATH102','MATH101'),('STAT101','MATH101'),('CS102','CS101'),
    ('DB201','CS102'),('VIZ201','CS101'),('VIZ201','STAT101'),('ML201','CS102'),
    ('ML201','MATH102'),('ML201','STAT101'),('DE301','DB201'),('DE301','CS102'),
    ('DB301','DB201'),('DL301','ML201'),('NLP401','DL301'),('CAP401','DB301'),('CAP401','ML201')]
STUDENTS = [('S01','An',3),('S02','Binh',2),('S03','Chi',3),('S04','Dung',1),
    ('S05','Giang',2),('S06','Hoa',3),('S07','Khoa',2),('S08','Lan',1),
    ('S09','Minh',3),('S10','Phuong',2)]
PASSED = {
    'S01':{'CS101':8.5,'MATH101':7.0,'CS102':8.0,'MATH102':6.5,'STAT101':7.5,'DB201':9.0},
    'S02':{'CS101':7.0,'MATH101':8.0,'STAT101':8.5,'VIZ201':9.0},
    'S03':{'CS101':9.0,'MATH101':9.5,'MATH102':9.0,'STAT101':8.0,'CS102':8.5,'ML201':9.0,'DB201':7.5},
    'S04':{'CS101':6.5,'MATH101':7.5},
    'S05':{'CS101':8.0,'CS102':7.5,'DB201':8.0,'MATH101':6.0},
    'S06':{'CS101':9.5,'MATH101':8.5,'MATH102':8.0,'STAT101':9.0,'CS102':9.0,'DB201':8.5,'DB301':9.0,'ML201':8.0},
    'S07':{'CS101':7.5,'MATH101':7.0,'STAT101':6.5,'CS102':7.0},
    'S08':{'CS101':8.0},
    'S09':{'CS101':8.0,'MATH101':8.0,'MATH102':7.5,'STAT101':7.0,'CS102':8.0,'DB201':8.0,'ML201':7.5,'DL301':8.5,'VIZ201':8.0},
    'S10':{'CS101':9.0,'MATH101':9.0,'STAT101':8.0,'VIZ201':8.5,'CS102':7.5},
}
FRIENDS = [('S01','S02'),('S01','S05'),('S02','S04'),('S04','S08'),('S05','S07'),
    ('S07','S10'),('S03','S06'),('S03','S09'),('S06','S09'),('S09','S10'),('S08','S10')]


def setup():
    # Only run on this lab's dedicated Docker instance, not an existing database.
    q = lambda cypher, **params: driver.execute_query(cypher, params)
    q('MATCH (n) DETACH DELETE n')
    q('CREATE CONSTRAINT student_id IF NOT EXISTS FOR (s:Student) REQUIRE s.id IS UNIQUE')
    q('CREATE CONSTRAINT course_code IF NOT EXISTS FOR (c:Course) REQUIRE c.code IS UNIQUE')
    q('UNWIND $rows AS r MERGE (c:Course {code:r[0]}) SET c.title=r[1],c.credits=r[2]',rows=[list(c) for c in COURSES])
    q('UNWIND $rows AS r MATCH (c:Course {code:r[0]}),(p:Course {code:r[1]}) MERGE (c)-[:REQUIRES]->(p)',rows=[list(r) for r in REQUIRES])
    q('UNWIND $rows AS r MERGE (s:Student {id:r[0]}) SET s.name=r[1],s.year=r[2]',rows=[list(s) for s in STUDENTS])
    q('UNWIND $rows AS r MATCH (s:Student {id:r.sid}),(c:Course {code:r.code}) MERGE (s)-[p:PASSED]->(c) SET p.grade=r.grade',
      rows=[{'sid':s,'code':c,'grade':g} for s,d in PASSED.items() for c,g in d.items()])
    q('UNWIND $rows AS r MATCH (a:Student {id:r[0]}),(b:Student {id:r[1]}) MERGE (a)-[:FRIEND]->(b)',rows=[list(f) for f in FRIENDS])
    records=q('MATCH (n) RETURN labels(n)[0] AS label,count(*) AS n ORDER BY label').records
    print('loaded:',{r['label']:r['n'] for r in records})


def passed_courses(student_id):
    records=driver.execute_query('''MATCH (:Student {id:$sid})-[p:PASSED]->(c:Course)
        RETURN c.code AS code,p.grade AS grade ORDER BY grade DESC,code''',sid=student_id).records
    return [(r['code'],r['grade']) for r in records]


def prerequisite_chain(code):
    records=driver.execute_query('''MATCH p=(:Course {code:$code})-[:REQUIRES*1..]->(c:Course)
        RETURN c.code AS code,min(length(p)) AS depth ORDER BY depth,code''',code=code).records
    return [(r['code'],r['depth']) for r in records]


ELIGIBLE_QUERY = '''MATCH (s:Student {id:$sid})
MATCH (c:Course)
WHERE NOT EXISTS { MATCH (s)-[:PASSED]->(c) }
  AND NOT EXISTS {
    MATCH (c)-[:REQUIRES]->(p:Course)
    WHERE NOT EXISTS { MATCH (s)-[:PASSED]->(p) }
  }
RETURN c.code AS code ORDER BY code'''


def eligible_courses(student_id):
    return [r['code'] for r in driver.execute_query(ELIGIBLE_QUERY,sid=student_id).records]


def suggest_friends(student_id,k=3):
    records=driver.execute_query('''MATCH (s:Student {id:$sid})-[:PASSED]->(c:Course)<-[:PASSED]-(other:Student)
        WHERE other <> s AND NOT EXISTS { MATCH (s)-[:FRIEND]-(other) }
        RETURN other.name AS name,count(DISTINCT c) AS shared
        ORDER BY shared DESC,name LIMIT $k''',sid=student_id,k=k).records
    return [(r['name'],r['shared']) for r in records]


def connection(a_id,b_id):
    records=driver.execute_query('''MATCH (a:Student {id:$a}),(b:Student {id:$b})
        MATCH p=shortestPath((a)-[:FRIEND*0..]-(b))
        RETURN [n IN nodes(p) | n.name] AS names''',a=a_id,b=b_id).records
    return records[0]['names'] if records else []


def bottleneck_courses(k=3):
    records=driver.execute_query('''MATCH (dependent:Course)-[:REQUIRES*1..]->(c:Course)
        RETURN c.code AS code,count(DISTINCT dependent) AS dependents
        ORDER BY dependents DESC,code LIMIT $k''',k=k).records
    return [(r['code'],r['dependents']) for r in records]


def _record_pass_tx(tx,student_id,code,grade):
    exists=tx.run('MATCH (s:Student {id:$sid}),(c:Course {code:$code}) RETURN s.id AS sid',sid=student_id,code=code).single()
    if exists is None:
        raise ValueError(f'unknown student or course: {student_id}, {code}')
    missing=tx.run('''MATCH (s:Student {id:$sid}),(c:Course {code:$code})-[:REQUIRES]->(p:Course)
        WHERE NOT EXISTS { MATCH (s)-[:PASSED]->(p) }
        RETURN p.code AS code ORDER BY code''',sid=student_id,code=code).value()
    if missing:
        raise ValueError(f'missing prerequisites: {missing}')
    tx.run('''MATCH (s:Student {id:$sid}),(c:Course {code:$code})
        MERGE (s)-[p:PASSED]->(c) SET p.grade=$grade''',sid=student_id,code=code,grade=grade).consume()


def record_pass(student_id,code,grade):
    with driver.session() as session:
        session.execute_write(_record_pass_tx,student_id,code,grade)


def check():
    setup()
    def expect_error(fn):
        try:
            fn()
        except ValueError as e:
            return str(e)
        return None
    def after_record():
        record_pass('S08','CS102',7.0)
        record_pass('S08','CS102',7.5)
        n=driver.execute_query("MATCH (:Student {id:'S08'})-[p:PASSED]->(:Course {code:'CS102'}) RETURN count(p) AS n,max(p.grade) AS g").records[0]
        return n['n'],n['g'],eligible_courses('S08')
    tests=[
        ('1 passed_courses',lambda:passed_courses('S04'),[('MATH101',7.5),('CS101',6.5)]),
        ('2 prerequisite_chain',lambda:prerequisite_chain('DE301'),[('CS102',1),('DB201',1),('CS101',2)]),
        ('3 eligible_courses',lambda:eligible_courses('S01'),['DB301','DE301','ML201','VIZ201']),
        ('4 suggest_friends',lambda:suggest_friends('S02'),[('Minh',4),('Phuong',4),('Chi',3)]),
        ('5 connection',lambda:connection('S01','S08'),['An','Binh','Dung','Lan']),
        ('6 bottleneck_courses',lambda:bottleneck_courses(),[('CS101',9),('CS102',7),('MATH101',7)]),
        ('7a record_pass refuses',lambda:expect_error(lambda:record_pass('S04','ML201',8.0)),"missing prerequisites: ['CS102', 'MATH102', 'STAT101']"),
        ('7b record_pass writes',after_record,(1,7.5,['DB201','MATH101'])),
    ]
    failures=0
    for name,fn,expected in tests:
        got=fn()
        if got == expected:
            print('PASS ',name)
        else:
            failures+=1
            print('FAIL ',name,'expected',expected,'got',got)
    assert not failures, f'{failures} task(s) failed'


def profile():
    setup()
    def read_profile():
        result=driver.execute_query('PROFILE '+ELIGIBLE_QUERY,sid='S01')
        def walk(node):
            return [node]+[n for c in node.get('children',[]) for n in walk(c)]
        nodes=walk(result.summary.profile)
        leaves=[n['operatorType'] for n in nodes if not n.get('children')]
        # The Student access operator is the relevant first data-access operator.
        student=[n['operatorType'] for n in nodes if 's' in n.get('identifiers',[]) and ('Seek' in n['operatorType'] or 'Scan' in n['operatorType'])]
        return {'student_access':student,'leaf_operators':leaves,
                'db_hits':sum(n.get('dbHits',0) for n in nodes),'rows':[r['code'] for r in result.records],
                'plan':result.summary.profile}
    with_constraint=read_profile()
    try:
        driver.execute_query('DROP CONSTRAINT student_id')
        without_constraint=read_profile()
    finally:
        driver.execute_query('CREATE CONSTRAINT student_id IF NOT EXISTS FOR (s:Student) REQUIRE s.id IS UNIQUE')
    paths=driver.execute_query("MATCH p=(:Course {code:'CAP401'})-[:REQUIRES*1..]->(:Course {code:'CS101'}) RETURN [n IN nodes(p)|n.code] AS path").records
    output={'with_constraint':with_constraint,'without_constraint':without_constraint,
            'cap401_to_cs101_paths':[r['path'] for r in paths]}
    Path(__file__).with_name('profile-results.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    for label,data in [('with constraint',with_constraint),('without constraint',without_constraint)]:
        print(label,':',data['student_access'],'; leaf operators:',data['leaf_operators'],'; total db hits:',data['db_hits'])
    print('CAP401 -> CS101 path count:',len(paths))
    for r in paths:
        print(' -> '.join(r['path']))


if __name__ == '__main__':
    try:
        {'setup':setup,'check':check,'profile':profile}[sys.argv[1] if len(sys.argv)>1 else 'check']()
    finally:
        driver.close()
