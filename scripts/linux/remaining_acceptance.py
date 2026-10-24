#!/usr/bin/env python3
"""Run the remaining device acceptance jobs serially with durable private progress.

No cloud inference or model downloads. SIGTERM cancels the active test process
group and stops only the exact runtime this coordinator recorded as its own.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from localai import ROOT, GIB, paths, profiles, read_json, running, save_json, sha256, start, stop, process_identity
from telemetry import sample

def jobs():
    result=[]
    def add(label,profile,script,*args,timeout=7200):
        result.append({'label':label,'profile':profile,'script':script,'args':list(args),'timeout':timeout})
    add('native-harness-recovery','coding-concurrent','harness_recovery.py','--profile','coding-concurrent','--harness','pi','hermes')
    add('opencode-lifecycle','coding-concurrent','harness_recovery.py','--profile','coding-concurrent','--harness','opencode')
    add('cache-restart-pilot','coding-concurrent','cache_restart.py','coding-concurrent','--input-tokens','32768')
    add('cache-restart-200k','coding-concurrent','cache_restart.py','coding-concurrent','--input-tokens','200000')
    add('primary-context-ladder','coding-concurrent','campaign.py','coding-concurrent','--context-only','--repeats','1',
        '--directory','@primary-context-directory',timeout=21600)
    add('claude-recovery','messages-compatible','harness_recovery.py','--profile','messages-compatible','--harness','claude')
    add('qwen-500k-coding','qwen-exl3-512k-plain','coding_benchmark.py','qwen-exl3-512k-plain','--no-start','--input-tokens','485000',timeout=14400)
    add('qwen-27b-512k','qwen-512k','benchmark.py','qwen-512k','--no-start','--input-tokens','500000','--repeats','1',timeout=14400)
    add('qwen-27b-1m','qwen-1m','benchmark.py','qwen-1m','--no-start','--input-tokens','950000','--repeats','1',timeout=21600)
    add('glm-512k','glm-512k','benchmark.py','glm-512k','--no-start','--input-tokens','500000','--repeats','1',timeout=14400)
    add('q8-concurrent-200k','coding-concurrent-q8','benchmark.py','coding-concurrent-q8','--no-start','--input-tokens','200000','--workers','2','--repeats','1',timeout=14400)
    for profile,workers in [('vision-small',2),('vision-small-four',4)]:
        add(profile+'-200k-image',profile,'benchmark.py',profile,'--no-start','--input-tokens','200000','--workers',str(workers),'--repeats','1','--image','@synthetic-page',timeout=14400)
    for profile,workers in [('vision-clearcase',2),('vision-clearcase',4),('vision-balanced',1),('vision-quality',1),('vision-max',1)]:
        for mode in (['constrained','prompt-only'] if profile in ('vision-clearcase','vision-balanced') else ['prompt-only']):
            options=['--profile',profile,'--no-start','--workers',str(workers),'--variants','low','high','rotated','crop']
            if mode=='prompt-only': options.append('--prompt-only-schema')
            add(f'clearcase-{profile}-{workers}-{mode}',profile,'clearcase_benchmark.py',*options,timeout=10800)
    scenes={
        'portrait':'A studio photograph of a fictional 40-year-old person wearing a blue linen jacket, natural skin texture, neutral grey background, soft window lighting, both hands with five fingers resting on a wooden table.',
        'layout':'A realistic photograph of a small red toy sailboat beside two blue ceramic cups and one yellow lemon on a wooden table. A clearly readable white card says CEDAR 48271. Soft daylight.'}
    for family,steps in [('z-image',9),('qwen-image',40),('chroma',28),('flux2',28)]:
        for scene,prompt in scenes.items():
            add(f'image-{family}-1024-{scene}','comfyui','media_probe.py','--model',family,'--size','1024','--steps',str(steps),'--prompt',prompt)
    for family,steps in [('qwen-image',40),('flux2',28)]:
        add(f'image-{family}-identity-edit','comfyui','media_probe.py','--model',family,'--size','1024','--steps',str(steps),
            '--reference','@portrait-reference','--prompt','Edit the supplied portrait: change only the blue linen jacket to a red linen jacket. Preserve the same fictional person, face, pose, hands, lighting, table and background.')
    for width,height,label in [(832,480,'480p'),(1280,736,'720p-padded'),(1920,1088,'1080p-padded')]:
        for family,frames,steps in [('h3',124,8),('ltx',121,8),('wan-aio',81,4)]:
            reference=['--reference','@layout-reference'] if family=='wan-aio' else []
            add(f'video-{family}-{label}','comfyui','media_probe.py','--model',family,'--frames',str(frames),
                '--steps',str(steps),'--width',str(width),'--height',str(height),*reference,timeout=3900)
    # Do this last so manual review can begin with all shorter results available.
    add('two-hour-soak-and-eight-hour-continuation','coding-concurrent','reliability.py','coding-concurrent','--hours','8',timeout=39600)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--after-report',type=Path)
    parser.add_argument('--retry-failed',action='store_true')
    parser.add_argument('--reuse-harness-report',type=Path,action='append',default=[])
    args=parser.parse_args(); p=paths()
    args.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    destination=args.directory/'results.json'
    report=read_json(destination,{'started':time.time(),'results':[]})
    oldpid=report.get('coordinator_pid')
    if oldpid and process_identity(oldpid)==report.get('coordinator_identity') and oldpid!=os.getpid():
        parser.error('This acceptance run already has a live coordinator')
    report.update(status='running',coordinator_pid=os.getpid(),coordinator_identity=process_identity(os.getpid()),
        coordinator_sha256=sha256(Path(__file__)),jobs=jobs(),pending_manual_review=[
            'Inspect full-resolution images and video frames/audio; generation is not a quality score.',
            'Inspect reference-edit identity consistency and Wan I2V conditioning with generated samples.',
            'Review failed harness and memory/context experiments before selecting final defaults.',
            'Synthetic document tests do not establish real-case production accuracy.'])
    child=None; owned=None; interrupted=False
    def save(): save_json(destination,report)
    def cancel(signum,_):
        nonlocal interrupted
        interrupted=True
        report.update(status='cancelled',cancelled_at=time.time(),signal=signum); save()
        if child and child.poll() is None:
            try: os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError: pass
    signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
    save()
    try:
        if args.after_report:
            report['current']={'label':'waiting-for-context-campaign','report':str(args.after_report)};save()
            deadline=time.monotonic()+21600
            while not interrupted:
                previous=read_json(args.after_report,{})
                if previous.get('status') in ('passed','failed'):
                    report['prerequisite_campaign']=previous
                    if args.after_report in args.reuse_harness_report:
                        for item in previous.get('results',[]):
                            if item.get('harness')=='opencode' and item.get('same_model_runtime') and item.get('status') in ('passed','failed'):
                                report['results'].append({'label':'opencode-lifecycle','profile':previous.get('profile'),
                                    'status':'passed' if item['status']=='passed' else 'rejected',
                                    'validation_report':str(args.after_report),
                                    'reason':'Completed external native lifecycle probe; retain the result without repeating it unchanged.'})
                    save();break
                if time.monotonic()>deadline: raise RuntimeError('Prerequisite campaign did not finish within six hours')
                time.sleep(5)
        completed={r['label']:r for r in report['results']}
        for job in jobs():
            if interrupted: break
            past=completed.get(job['label'])
            if past and (past['status'] in ('passed','rejected') or not args.retry_failed): continue
            if job['script']=='reliability.py':
                latest={r['label']:r for r in report['results']}
                prerequisites=['native-harness-recovery','cache-restart-200k']
                if report.get('prerequisite_campaign',{}).get('status')!='passed' or any(latest.get(k,{}).get('status')!='passed' for k in prerequisites):
                    report['results'].append({**job,'status':'skipped','reason':'Short primary-profile acceptance must pass before the long reliability run.'});save();continue
            if not sample()['ac_online']: raise RuntimeError('AC disconnected; reconnect before resuming acceptance')
            if shutil.disk_usage(p['data']).free<40*GIB: raise RuntimeError('40 GiB free-disk floor reached')
            current=running()
            if owned and current and (owned['pid'],owned['identity'])!=(current['pid'],current['identity']):
                raise RuntimeError('Another runtime replaced the recorded owner; coordinator stopped')
            report['current']={**job,'started':time.time()};save()
            begin=time.monotonic(); record={**job,'started':time.time()}
            try:
                if current and current['profile']!=job['profile']: stop()
                owned=start(job['profile'])
                options=job['args'][:]
                if '@primary-context-directory' in options:
                    campaign_directory=args.directory/f'context-campaign-{int(time.time())}'
                    options[options.index('@primary-context-directory')]=str(campaign_directory)
                    record['campaign_report']=str(campaign_directory/'results.json')
                if job['label'] in ('native-harness-recovery','opencode-lifecycle'):
                    for source in args.reuse_harness_report: options += ['--reuse-passes',str(source)]
                if '@synthetic-page' in options:
                    from clearcase_benchmark import fixtures
                    fixture_dir=args.directory/'synthetic-vision';fixture_dir.mkdir(exist_ok=True)
                    options[options.index('@synthetic-page')]=str(fixtures(fixture_dir)[0]['image'])
                for placeholder,scene in [('@portrait-reference','portrait'),('@layout-reference','layout')]:
                    if placeholder not in options: continue
                    matches=[]
                    for path in sorted((p['state']/'benchmarks').glob('media-*.json'),key=lambda f:f.stat().st_mtime,reverse=True):
                        value=read_json(path,{})
                        parameters=value.get('parameters',{})
                        prompt=parameters.get('prompt') or ''
                        if value.get('status')!='passed' or parameters.get('size')!=1024 or parameters.get('reference'): continue
                        if (scene=='portrait' and 'blue linen jacket' not in prompt) or (scene=='layout' and 'two blue ceramic cups' not in prompt): continue
                        for image in value.get('images',[]):
                            source=Path(image['path'])
                            if source.is_file(): matches.append(source)
                        if matches: break
                    if not matches: raise RuntimeError(f'No passing generated {scene} reference is available')
                    options[options.index(placeholder)]=str(matches[0])
                script=ROOT/'scripts/linux'/job['script']
                record.update(adapter_sha256=sha256(script),runtime_pid=owned['pid'],runtime_identity=owned['identity'])
                with (args.directory/(job['label']+'.log')).open('w') as out:
                    child=subprocess.Popen([str(p['apps']/'support/bin/python'),str(script),*options],
                        stdout=out,stderr=subprocess.STDOUT,start_new_session=True,
                        env={**os.environ,'PATH':str(p['bin'])+os.pathsep+os.environ['PATH']})
                    report['current'].update(test_pid=child.pid,test_identity=process_identity(child.pid));save()
                    deadline=time.monotonic()+job['timeout']
                    while child.poll() is None and not interrupted:
                        if time.monotonic()>deadline:
                            os.killpg(child.pid,signal.SIGTERM)
                            raise TimeoutError('Acceptance job exceeded its bounded runtime')
                        time.sleep(2)
                    if interrupted: break
                    record.update(exit_code=child.returncode,status='passed' if child.returncode==0 else 'failed')
                    if job['label']=='primary-context-ladder':
                        report['prerequisite_campaign']=read_json(Path(record['campaign_report']),{})
                    if job['script']=='cache_restart.py':
                        restarted=running()
                        if restarted and restarted['profile']==job['profile']: owned=restarted
            except Exception as error:
                record.update(status='failed',error=repr(error))
                if child and child.poll() is None:
                    try: os.killpg(child.pid,signal.SIGTERM);child.wait(15)
                    except (ProcessLookupError,subprocess.TimeoutExpired):
                        try: os.killpg(child.pid,signal.SIGKILL)
                        except ProcessLookupError: pass
            record['seconds']=time.monotonic()-begin
            report['results'].append(record);save()
            # A timed-out Comfy request can still run on the server. Stop it here.
            if record['status']=='failed' and running():
                current=running()
                if owned and (current['pid'],current['identity'])==(owned['pid'],owned['identity']): stop()
                owned=None
        if not interrupted:
            report.update(status='automated_jobs_finished',finished=time.time(),current=None)
            current=running()
            if current and current['profile']!='coding-concurrent': stop()
            start('coding-concurrent')
    except Exception as error: report.update(status='needs_attention',error=repr(error),attention_at=time.time())
    finally:
        if interrupted:
            if child and child.poll() is None:
                try: child.wait(15)
                except subprocess.TimeoutExpired:
                    try: os.killpg(child.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
            current=running()
            if current and owned and (current['pid'],current['identity'])==(owned['pid'],owned['identity']): stop()
        save()
    print(json.dumps({'status':report['status'],'report':str(destination)}))
    return int(report['status']!='automated_jobs_finished')

if __name__=='__main__': raise SystemExit(main())
