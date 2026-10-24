#!/usr/bin/env python3
"""Two-hour mixed coding load followed by overnight session continuations."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import time
from localai import ROOT, paths, profiles, running, save_json, start, validation_metadata
from benchmark import calibrated_text, completion
from telemetry import Monitor, sample

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile',choices=profiles(),default='coding-concurrent',nargs='?')
    parser.add_argument('--hours',type=float,default=8)
    args=parser.parse_args()
    if args.hours<2: parser.error('Acceptance requires at least two real elapsed hours')
    start(args.profile); p=paths(); owner=running()
    directory=p['state']/'reliability'/f'{args.profile}-{int(time.time())}'
    directory.mkdir(parents=True,mode=0o700)
    report={'profile':args.profile,**validation_metadata(args.profile),'status':'running','started':time.time(),
        'requested_hours':args.hours,'cycles':[], 'two_hour_mixed_load_passed':False,'overnight_continuation_passed':False}
    began=time.monotonic(); deadline=None
    worker_count=min(2,profiles()[args.profile]['sessions'])
    conversations={}
    env={**os.environ,'PATH':str(p['bin'])+os.pathsep+os.environ['PATH']}
    def job(script,options,label):
        with (directory/(label+'.log')).open('w') as out:
            done=subprocess.run([str(p['apps']/'support/bin/python'),str(ROOT/'scripts/linux'/script),*options],
                stdout=out,stderr=subprocess.STDOUT,env=env,timeout=3600)
        if done.returncode: raise RuntimeError(f'{label} exited {done.returncode}; inspect its private log')
    def seed(index):
        text, expected=calibrated_text('http://127.0.0.1:8080/v1',args.profile,200000,index)
        messages=[{'role':'user','content':text}]
        answer,seconds=completion('http://127.0.0.1:8080/v1',args.profile,messages,128)
        message=answer['choices'][0]['message']
        if message.get('content','').strip()!=expected or answer['usage'].get('prompt_tokens',0)<200000:
            raise RuntimeError('Initial long conversation failed actual-token or exact-recall checks')
        messages.append(message)
        conversations[index]={'expected':expected,'messages':messages}
        save_json(directory/f'conversation-{index}.json',conversations[index])
        return {'worker':index,'seconds':seconds,'usage':answer['usage']}
    def advance(index,cycle):
        state=conversations[index]
        messages=[*state['messages'],{'role':'user','content':f'Continuation check {cycle}. Return only the original project code, with no explanation.'}]
        answer,seconds=completion('http://127.0.0.1:8080/v1',args.profile,messages,128)
        message=answer['choices'][0]['message']
        passed=message.get('content','').strip()==state['expected'] and answer['usage'].get('prompt_tokens',0)>=200000
        if passed:
            state['messages']=[*messages,message]
            save_json(directory/f'conversation-{index}.json',state)
        return {'worker':index,'passed':passed,'seconds':seconds,'usage':answer['usage'],
            'messages':len(messages),'first_token_seconds':answer['transport']['first_token_seconds']}
    with Monitor() as monitor:
        try:
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                report['initial_long_context']=list(pool.map(seed,range(worker_count)))
            report['initialization_seconds']=time.monotonic()-began
            # The two-hour mixed phase starts after both long contexts are seeded.
            began=time.monotonic(); deadline=began+args.hours*3600
            index=0
            while time.monotonic()<deadline or not report['cycles']:
                if not sample()['ac_online']: raise RuntimeError('AC power disconnected; reliability run stopped')
                current=running()
                if not current or (current['pid'],current['identity'])!=(owner['pid'],owner['identity']):
                    raise RuntimeError('Runtime exited or restarted during reliability test')
                elapsed=time.monotonic()-began
                cycle={'index':index,'started':time.time(),'elapsed_seconds':elapsed}
                if elapsed<7200:
                    # Real file edits plus independently evaluated hidden assertions.
                    job('coding_benchmark.py',[args.profile,'--no-start','--cases','3'],f'coding-{index}')
                    harness=('pi','opencode','hermes')[index%3]
                    job('harness_smoke.py',['--profile',args.profile,'--no-start','--launchers','--harness',harness],f'harness-{index}')
                    cycle['mixed_harness']=harness
                with ThreadPoolExecutor(max_workers=worker_count) as pool:
                    runs=list(pool.map(lambda i:advance(i,index),range(worker_count)))
                cycle['context_runs']=runs
                if not all(r['passed'] for r in runs):
                    raise RuntimeError('Reliability exact recall or continuation failed')
                cycle['finished']=time.time(); report['cycles'].append(cycle)
                # Use actual completed elapsed time, never the configured duration, for milestones.
                report['elapsed_seconds']=time.monotonic()-began
                if report['elapsed_seconds']>=7200: report['two_hour_mixed_load_passed']=True
                save_json(directory/'results.json',report)
                if elapsed>=7200:
                    # Continue throughout the remaining overnight period without a busy loop.
                    until=min(deadline,time.monotonic()+600)
                    while time.monotonic()<until: time.sleep(max(0,min(30,until-time.monotonic())))
                index+=1
            # Finish with a full-length continuation after the entire real-duration interval.
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                final=list(pool.map(lambda i:advance(i,'final'),range(worker_count)))
            report['final_long_context']=final
            if not all(r['passed'] for r in final):
                raise RuntimeError('Final full-length overnight continuation failed')
            report['overnight_continuation_passed']=args.hours>=8
            report['status']='passed'
        except Exception as error: report.update(status='failed',error=repr(error))
    report['elapsed_seconds']=time.monotonic()-began
    report['finished']=time.time(); report['telemetry']=monitor.report()
    swaps=[s.get('runtime_process',{}).get('VmSwap',0) for s in monitor.samples]
    report['maximum_runtime_swap_bytes']=max(swaps,default=0)
    if report['maximum_runtime_swap_bytes']>64*1024*1024:
        report['status']='failed';report['swap_acceptance']='Runtime process swap exceeded the 64 MiB acceptance tolerance; reject as a no-swap configuration.'
    report['limitations']='Two independent 200K conversations are seeded once, then genuinely extended throughout the run. First two measured hours mix separate synthetic coding/tool tasks; later ten-minute continuations extend the same saved histories through eight measured hours. No suspend/reboot simulation or natural 225K harness compaction. Global swap is separate; the runtime-process acceptance tolerance is 64 MiB.'
    save_json(directory/'results.json',report)
    print(json.dumps({'status':report['status'],'report':str(directory/'results.json')}))
    return int(report['status']!='passed')

if __name__=='__main__': raise SystemExit(main())
