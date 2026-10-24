#!/usr/bin/env python3
"""Fresh, actual-token prefill measurements; do not score cached input as work."""
import argparse
import json
import statistics
import signal
import time
from benchmark import calibrated_text, completion
from localai import paths, profiles, start, stop, running, save_json, validation_metadata, read_json, catalog
from telemetry import Monitor, sample

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile',choices=profiles())
    parser.add_argument('--tokens',type=int,nargs='+',default=[2048,8192,32768,131072,200000])
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--wait-model',action='store_true',help='Wait up to two hours for this model download to finish verification.')
    parser.add_argument('--continuation',action='store_true',help='Also verify cache reuse after the final fresh request; excluded from prefill medians.')
    args=parser.parse_args()
    if running():
        parser.error('A runtime already owns the GPU. Finish its work and run localai stop before benchmarking.')
    destination=paths()['state']/'prefill-acceptance'/f'{args.profile}-{int(time.time())}.json'
    report={'profile':args.profile,'started':time.time(),'status':'running','runs':[],
            'threshold_tokens_per_second':1200,'goal_tokens_per_second':1500,
            'method':'OpenAI streaming API, greedy, thinking off, cache_prompt=false. Actual newly evaluated prompt tokens divided by engine prefill time. Recall outputs are short; no sustained decode claim.'}
    save_json(destination,report)
    def interrupt(*_): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupt)
    if args.wait_model:
        key=profiles()[args.profile]['model'];deadline=time.monotonic()+7200
        report['status']='waiting_for_verified_model';save_json(destination,report)
        while read_json(paths()['state']/'verified-models.json',{}).get(key,{}).get('revision')!=catalog()['models'][key]['revision']:
            if time.monotonic()>deadline:raise RuntimeError('Model download did not finish within two hours')
            time.sleep(5)
        report['status']='running';save_json(destination,report)
    owner=None
    with Monitor() as monitor:
        try:
            if running():
                raise RuntimeError('A runtime acquired the GPU while waiting; leave it running and retry after its work finishes.')
            owner=start(args.profile)
            report.update(validation_metadata(args.profile))
            # Calibrated warmup is deliberately excluded from measured rows.
            warm,_=calibrated_text('http://127.0.0.1:8080/v1',args.profile,512,91)
            completion('http://127.0.0.1:8080/v1',args.profile,[{'role':'user','content':warm}],32,cache_prompt=False)
            for target in args.tokens:
                if target+256>profiles()[args.profile]['context']:raise ValueError('Input exceeds configured context')
                text,expected=calibrated_text('http://127.0.0.1:8080/v1',args.profile,target,92)
                for repeat in range(args.repeats if target<=32768 else 1):
                    if not running() or running()['identity']!=owner['identity']:raise RuntimeError('Owned runtime changed or exited')
                    before=sample()
                    if not before['ac_online']: raise RuntimeError('AC power disconnected')
                    answer,seconds=completion('http://127.0.0.1:8080/v1',args.profile,[{'role':'user','content':text}],128,cache_prompt=False)
                    after=sample()
                    usage=answer['usage'];g=usage.get('gufo',{});timings=answer.get('timings',{})
                    fresh=g.get('prefill_tokens',timings.get('prompt_n',0))
                    elapsed_ms=g.get('prefill_ms',timings.get('prompt_ms',0))
                    cached=usage.get('prompt_tokens_details',{}).get('cached_tokens',usage.get('cached_tokens',0))
                    row={'platform_profile_before':before.get('platform_profile'),'platform_profile_after':after.get('platform_profile'),
                         'gpu_policy_before':before.get('gpu_clock_state',{}).get('power_dpm_force_performance_level'),
                         'gpu_policy_after':after.get('gpu_clock_state',{}).get('power_dpm_force_performance_level'),
                         'target_tokens':target,'repeat':repeat,'actual_input_tokens':usage.get('prompt_tokens',0),
                         'fresh_tokens':fresh,'cached_tokens':cached,'prefill_ms':elapsed_ms,
                         'prefill_tokens_per_second':fresh/(elapsed_ms/1000) if elapsed_ms else None,
                         'wall_seconds':seconds,'first_token_seconds':answer['transport']['first_token_seconds'],
                         'recall_passed':answer['choices'][0]['message'].get('content','').strip()==expected,
                         'usage':usage,'timings':timings}
                    row['valid']=row['actual_input_tokens']>=target and fresh>=target and cached==0 and row['recall_passed'] and before.get('platform_profile')==after.get('platform_profile') and row['gpu_policy_before']==row['gpu_policy_after'] and after['ac_online']
                    report['runs'].append(row);save_json(destination,report)
                    print(json.dumps({k:row[k] for k in ('target_tokens','repeat','fresh_tokens','cached_tokens','prefill_tokens_per_second','wall_seconds','valid')}),flush=True)
                    if not row['valid']:raise RuntimeError('Actual-token, fresh-work or recall check failed')
            if args.continuation:
                messages=[{'role':'user','content':text},answer['choices'][0]['message'],
                          {'role':'user','content':'Repeat that exact project code. No other text.'}]
                warm,seconds=completion('http://127.0.0.1:8080/v1',args.profile,messages,128,cache_prompt=True)
                used=warm['usage'];cached=used.get('prompt_tokens_details',{}).get('cached_tokens',used.get('cached_tokens',0))
                report['continuation']={'usage':used,'wall_seconds':seconds,
                    'recall_passed':warm['choices'][0]['message'].get('content','').strip()==expected,
                    'first_token_seconds':warm['transport']['first_token_seconds'],
                    'cache_reused':cached>=.9*used.get('prompt_tokens',1)}
                save_json(destination,report)
                if not report['continuation']['recall_passed'] or not report['continuation']['cache_reused']:
                    raise RuntimeError('Continuation recall or cache reuse failed')
            report['medians']={str(n):statistics.median(r['prefill_tokens_per_second'] for r in report['runs'] if r['target_tokens']==n) for n in args.tokens}
            report['minimum_median']=min(report['medians'].values())
            report['threshold_passed']=report['minimum_median']>=1200
            report['goal_passed']=report['minimum_median']>=1500
            report['status']='passed' if report['threshold_passed'] else 'below_threshold'
        except KeyboardInterrupt:report.update(status='cancelled')
        except Exception as error:report.update(status='failed',error=repr(error))
        finally:
            current=running()
            if current and owner and current['identity']==owner['identity']:stop()
    report.update(finished=time.time(),telemetry=monitor.report())
    save_json(destination,report)
    print(json.dumps({'status':report['status'],'report':str(destination),'medians':report.get('medians')}),flush=True)
    return int(report['status'] not in ('passed','below_threshold'))

if __name__=='__main__':raise SystemExit(main())
