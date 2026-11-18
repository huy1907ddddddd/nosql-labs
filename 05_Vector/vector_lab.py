"""Three exercises using local Milvus Lite and all-MiniLM-L6-v2."""
import json
import os
from pathlib import Path
HERE=Path(__file__).resolve().parent
os.environ.setdefault('HF_HOME',str(HERE.parent/'.cache'/'huggingface'))

import numpy as np
from pymilvus import MilvusClient
from sentence_transformers import SentenceTransformer

ORIGINAL=[
    ('How to teach a young dog to sit','pets'),
    ('Best exercises for a healthy back','health'),
    ('Feeding a kitten: what and when','pets'),
    ('Stock market basics for beginners','finance'),
]
EXTRA=[
    ('Puppy obedience training: reward your puppy when it sits on command.','pets'),
    ('Leash training teaches a young dog to walk calmly beside its owner.','pets'),
    ('House train a puppy with regular outdoor toilet breaks.','pets'),
    ('Kittens need small meals of suitable cat food several times a day.','pets'),
    ('Take a pet dog to the veterinarian for vaccinations.','pets'),
    ('A cat needs clean water, a litter box and a quiet place to sleep.','pets'),
    ('Positive reinforcement helps dogs learn new commands.','pets'),
    ('Regular exercise strengthens your back muscles and improves posture.','health'),
    ('Gentle back stretches can reduce stiffness after sitting at a desk.','health'),
    ('Walking every day supports heart health and physical fitness.','health'),
    ('A balanced diet includes vegetables, fruit and enough protein.','health'),
    ('Adults should sleep for seven to nine hours each night.','health'),
    ('Drink water regularly to prevent dehydration during exercise.','health'),
    ('Good posture reduces pressure on the spine while working.','health'),
    ('Diversifying a stock portfolio reduces concentration risk.','finance'),
    ('A savings account pays interest on deposited money.','finance'),
    ('Make a monthly budget to track income and expenses.','finance'),
    ('Bonds pay interest and have credit and interest rate risks.','finance'),
    ('An emergency fund covers unexpected expenses.','finance'),
    ('Compound interest earns returns on previously accumulated interest.','finance'),
]


def main():
    docs=[{'id':i+1,'text':text,'topic':topic} for i,(text,topic) in enumerate(ORIGINAL+EXTRA)]
    assert len(EXTRA)==20 and len({d['topic'] for d in docs})==3
    model=SentenceTransformer('all-MiniLM-L6-v2')
    vectors=model.encode([d['text'] for d in docs],normalize_embeddings=True)
    client=MilvusClient(str(HERE/'lab_vectors.db'))
    for collection,metric in [('docs_cosine','COSINE'),('docs_l2','L2')]:
        if client.has_collection(collection):
            client.drop_collection(collection)
        client.create_collection(collection_name=collection,dimension=384,metric_type=metric)
        client.insert(collection,[{**d,'vector':v.tolist()} for d,v in zip(docs,vectors)])
    results={'original_documents':4,'added_documents':20,'topics':3,'searches':{}}
    queries={'pets':'puppy training tips','health':'exercises for a healthy back','finance':'stock portfolio diversification'}
    for topic,question in queries.items():
        query=model.encode([question],normalize_embeddings=True)
        kwargs={'data':query.tolist(),'limit':3,'output_fields':['text','topic']}
        cosine=client.search('docs_cosine',**kwargs)[0]
        l2=client.search('docs_l2',**kwargs)[0]
        cosine_ids=[h['id'] for h in cosine]
        l2_ids=[h['id'] for h in l2]
        assert all(h['entity']['topic']==topic for h in cosine),cosine
        assert cosine_ids==l2_ids,(cosine_ids,l2_ids)
        # Compare the exact scores too; Milvus reports squared Euclidean distance.
        for a,b in zip(cosine,l2):
            assert abs(b['distance']-(2-2*a['distance']))<1e-4
        filtered=client.search('docs_cosine',**kwargs,filter=f'topic == "{topic}"')[0]
        assert all(h['entity']['topic']==topic for h in filtered)
        results['searches'][topic]={'query':question,'cosine':cosine,'l2':l2,'filtered':filtered}
        print('PASS topic:',topic,'; top-3 IDs:',cosine_ids,'; all in topic; cosine/L2 order identical')
    query=model.encode(['How can I teach my puppy to sit?'],normalize_embeddings=True)
    chunks=client.search('docs_cosine',data=query.tolist(),limit=3,output_fields=['text','topic'])[0]
    context='\n'.join(f'[{i+1}] '+hit['entity']['text'] for i,hit in enumerate(chunks))
    prompt=('Answer only using the context below. If it is insufficient, say you do not know.\n\n'
            'CONTEXT:\n'+context+'\n\nQUESTION: How can I teach my puppy to sit?\nANSWER:')
    (HERE/'RAG-PROMPT.txt').write_text(prompt,encoding='utf-8')
    print('PASS tiny RAG: retrieved 3 chunks; prompt only, no LLM API call\n'+prompt)
    results['rag_chunk_ids']=[h['id'] for h in chunks]
    (HERE/'documents.json').write_text(json.dumps(docs,indent=2),encoding='utf-8')
    # Convert numpy scalar IDs if the database client returns them.
    (HERE/'results.json').write_text(json.dumps(results,indent=2,default=lambda x:x.item() if hasattr(x,'item') else str(x)),encoding='utf-8')
    client.close()


if __name__=='__main__':
    main()

