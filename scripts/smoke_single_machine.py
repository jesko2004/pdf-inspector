"""Real loopback HTTP + real PDF cold restore; no paid model calls."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.backup import create_backup, restore_backup
from backend.process_isolation import WindowsJob

checks=[]
def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def main():
    (ROOT/'tmp').mkdir(exist_ok=True)
    pdf=(ROOT/'tests/fixtures/thermo-freon12.pdf').read_bytes()
    with tempfile.TemporaryDirectory(prefix='single-machine-smoke-', dir=ROOT/'tmp') as temporary:
        root=Path(temporary)
        processes=[]
        jobs={}
        logs=[]
        def start(data):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            env={**os.environ,'PYTHONUTF8':'1','PDF_INSPECTOR_DATA_DIR':str(data),
                 'PDF_INSPECTOR_HOST':'127.0.0.1','PDF_INSPECTOR_PORT':str(port),
                 'PDF_INSPECTOR_API_KEYS_JSON':'[]','PDF_INSPECTOR_WORKERS':'1',
                 'PDF_INSPECTOR_VECTOR_STORE':'sqlite','PDF_INSPECTOR_OCR_PROVIDER':'none',
                 'PDF_INSPECTOR_EMBEDDING_PROVIDER':'hash','PDF_INSPECTOR_EMBEDDING_MODEL':'hash-v1',
                 'PDF_INSPECTOR_EMBEDDING_DIMENSIONS':'256','PDF_INSPECTOR_LLM_PROVIDER':'extractive',
                 'PDF_INSPECTOR_LLM_MODEL':'extractive-v1','PDF_INSPECTOR_RERANK_PROVIDER':'none'}
            log=open(ROOT/'tmp'/f'single-machine-smoke-{len(processes)+1}.log','wb');logs.append(log)
            process=subprocess.Popen([sys.executable,'-c','import sys; sys.stdin.readline(); from backend.server import run; run()'],cwd=ROOT,env=env,
                stdin=subprocess.PIPE,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
                start_new_session=os.name!='nt')
            processes.append(process)
            if os.name=='nt':jobs[process]=WindowsJob(process,4096*1024*1024)
            process.stdin.write(b'go\n');process.stdin.flush();process.stdin.close()
            base=f'http://127.0.0.1:{port}'
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if process.poll() is not None: raise RuntimeError('server did not start; inspect smoke log')
                try:
                    with urlopen(base+'/health',timeout=1) as response:
                        if response.status==200:return process,base
                except OSError:time.sleep(.1)
            raise TimeoutError('server health deadline')
        def stop(process):
            job=jobs.pop(process,None)
            if job is not None:
                job.terminate();job.close()
            elif process.poll() is None:
                import signal
                os.killpg(process.pid,signal.SIGKILL)
            process.wait(10)
        def call(base,path,payload=None,key=None,raw=None,content_type=None):
            body=json.dumps(payload).encode() if payload is not None else raw
            headers={}
            if body is not None: headers['Content-Type']=content_type or 'application/json'
            if key:headers['Idempotency-Key']=key
            with urlopen(Request(base+path,data=body,headers=headers),timeout=20) as response:
                result=response.read()
                return json.loads(result) if response.headers.get('Content-Type','').startswith('application/json') else result
        def upload(base,key,source=pdf,filename='thermo-freon12.pdf'):
            boundary='boundary-'+str(uuid4())
            body=(f'--{boundary}\r\nContent-Disposition: form-data; name="profile_id"\r\n\r\nmanual_query\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n'.encode()+source+f'\r\n--{boundary}--\r\n'.encode())
            return call(base,'/v1/tasks',key=key,raw=body,content_type='multipart/form-data; boundary='+boundary)
        def ready(base,path):
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                row=call(base,path)
                if row['status'] in ('ready','needs_review'):return row
                if row['status']=='failed':raise RuntimeError('work failed: '+json.dumps(row.get('error')))
                time.sleep(.1)
            raise TimeoutError('task/index readiness')
        try:
            data=root/'source';process,base=start(data)
            task=upload(base,'smoke-upload')
            check('same-key upload returns original task',upload(base,'smoke-upload')['id']==task['id'])
            ready(base,'/v1/tasks/'+task['id'])
            kb=call(base,'/v1/knowledge-bases',{'name':'Reliability smoke'})['id']
            path='/v1/knowledge-bases/'+kb
            document=call(base,path+'/documents',{'task_id':task['id'],'document_key':'freon'})
            ready(base,path+'/documents/'+document['id'])
            answer=call(base,path+'/ask',{'question':'Critical Temperature','retrieval_mode':'bm25','min_score':0},key='smoke-ask')
            check('real PDF produces cited evidence',bool(answer['citations']))
            check('same-key answer replays stable answer identity',call(base,path+'/ask',{'question':'Critical Temperature','retrieval_mode':'bm25','min_score':0},key='smoke-ask')['answer_id']==answer['answer_id'])
            archive=root/'backup.tar.gz'
            try:create_backup(data,archive)
            except RuntimeError:check('active executor refuses cold backup',not archive.exists())
            else:raise AssertionError('active backup unexpectedly succeeded')
            stop(process)
            create_backup(data,archive)
            check('stopped executor permits verified backup',archive.is_file())
            data.rename(root/'source-unavailable')
            restored=root/'restored';restore_backup(archive,restored)
            process,base=start(restored)
            check('restored source does not depend on old directory',not data.exists())
            check('restored original PDF bytes match',call(base,'/v1/tasks/'+task['id']+'/source')==pdf)
            check('restored structured result loads',bool(call(base,'/v1/tasks/'+task['id']+'/result')['chunks']))
            restored_answer=call(base,path+'/ask',{'question':'Critical Temperature','retrieval_mode':'bm25','min_score':0},key='smoke-ask')
            check('restored saved answer and citations replay exactly',restored_answer==answer)
            new_answer=call(base,path+'/ask',{'question':'Critical Pressure','retrieval_mode':'bm25','min_score':0},key='new-ask')
            check('new retrieval after restore returns citations',bool(new_answer['citations']))
            next_pdf=(ROOT/'tests/fixtures/nexo-price-en.pdf').read_bytes()
            next_task=upload(base,'new-upload',next_pdf,'nexo-price-en.pdf');ready(base,'/v1/tasks/'+next_task['id'])
            next_document=call(base,path+'/documents',{'task_id':next_task['id'],'document_key':'second'})
            ready(base,path+'/documents/'+next_document['id'])
            check('new ingestion after restore succeeds',next_document['id']!=document['id'])
            stop(process)
        finally:
            for process in processes:stop(process)
            for log in logs:log.close()
    result={'date':'2026-10-05','checks':checks,'passed':len(checks),'real_pdf':True,'source_sha256':hashlib.sha256(pdf).hexdigest(),
        'server':'real loopback HTTP, one executor','vector_store':'sqlite','embedding':'hash-v1','llm':'extractive-v1',
        'real_model_validation':False,'human_reviewed':0,'answer_quality_claim':False}
    (ROOT/'tmp/single-machine-smoke-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':len(checks),'real_pdf':True,'real_model_validation':False}))


if __name__=='__main__':main()
