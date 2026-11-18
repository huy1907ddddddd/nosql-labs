"""Three MongoDB exercises. Uses only the dedicated nosql_lab01 database."""
import json
import os
from pathlib import Path
from pymongo import MongoClient

HERE = Path(__file__).resolve().parent


def main():
    client = MongoClient(os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27027'), serverSelectionTimeoutMS=15000)
    db = client.nosql_lab01
    orders = db.orders
    orders.drop()
    docs = [
        {'_id': 1001, 'customer': {'name': 'Linh', 'city': 'Hanoi'}, 'status': 'paid',
         'items': [{'sku': 'BK-01', 'qty': 2, 'price': 12.5}, {'sku': 'BK-07', 'qty': 1, 'price': 18.0}]},
        {'_id': 1002, 'customer': {'name': 'Nam', 'city': 'Da Nang'}, 'status': 'shipped',
         'items': [{'sku': 'BK-03', 'qty': 1, 'price': 22.0}], 'tags': ['gift']},
        {'_id': 1003, 'customer': {'name': 'Mai', 'city': 'Hanoi'}, 'status': 'paid',
         'items': [{'sku': 'BK-01', 'qty': 1, 'price': 12.5}], 'coupon': 'WELCOME10'},
        {'_id': 1004, 'customer': {'name': 'Hung', 'city': 'Hue'}, 'status': 'paid',
         'items': [{'sku': 'BK-05', 'qty': 3, 'price': 10}], 'delivery': {'express': True}},
        {'_id': 1005, 'customer': {'name': 'An', 'city': 'Hanoi'}, 'status': 'pending',
         'items': [{'sku': 'BK-01', 'qty': 1, 'price': 12.5}], 'note': 'not paid yet'},
    ]
    orders.insert_many(docs)
    found = list(orders.find({'items.sku': 'BK-01'}, {'_id': 1}).sort('_id', 1))
    assert found == [{'_id': 1001}, {'_id': 1003}, {'_id': 1005}]
    print('PASS 1: five different-shaped orders; BK-01 order IDs:', [d['_id'] for d in found])
    pipeline = [
        {'$match': {'status': {'$in': ['paid', 'shipped']}}},
        {'$unwind': '$items'},
        {'$group': {'_id': '$customer.city', 'revenue': {'$sum': {'$multiply': ['$items.qty', '$items.price']}}}},
        {'$sort': {'_id': 1}},
    ]
    revenue = list(orders.aggregate(pipeline))
    assert revenue == [{'_id': 'Da Nang', 'revenue': 22.0}, {'_id': 'Hanoi', 'revenue': 55.5}, {'_id': 'Hue', 'revenue': 30}]
    print('PASS 2: paid/shipped revenue per city:', revenue)
    # Separate collection keeps the five exercise orders unchanged.
    perf = db.orders_10000
    perf.drop()
    perf.insert_many({'_id': i, 'customer': {'city': 'City-%03d' % (i % 100)},
                      'status': 'paid' if i % 2 == 0 else 'pending', 'amount': i % 50 + 1}
                     for i in range(10000))
    query = {'customer.city': 'City-000', 'status': 'paid'}
    before = db.command('explain', {'find': perf.name, 'filter': query}, verbosity='executionStats')
    perf.create_index([('customer.city', 1), ('status', 1)])
    after = db.command('explain', {'find': perf.name, 'filter': query}, verbosity='executionStats')
    def summary(plan):
        stats = plan['executionStats']
        return {k: stats[k] for k in ('nReturned', 'totalDocsExamined', 'totalKeysExamined', 'executionTimeMillis')}
    assert 'COLLSCAN' in json.dumps(before['queryPlanner']['winningPlan'])
    assert 'IXSCAN' in json.dumps(after['queryPlanner']['winningPlan'])
    assert before['executionStats']['nReturned'] == after['executionStats']['nReturned'] == 100
    assert after['executionStats']['totalDocsExamined'] < before['executionStats']['totalDocsExamined']
    print('PASS 3: before COLLSCAN', summary(before))
    print('        after IXSCAN ', summary(after))
    result = {'orders': docs, 'sku_matches': found, 'revenue_per_city': revenue,
              'before': summary(before), 'after': summary(after)}
    (HERE / 'results.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    for name, plan in [('explain-before.json', before), ('explain-after.json', after)]:
        (HERE / name).write_text(json.dumps(plan, indent=2, default=str), encoding='utf-8')
    client.close()


if __name__ == '__main__':
    main()
