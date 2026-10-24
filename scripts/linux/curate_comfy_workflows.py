#!/usr/bin/env python3
"""Prepare/collect four native workflows using ComfyUI's own frontend converter.

Only graph construction and serialization; never submits a generation request.
Existing workflows are archived outside the active sidebar before migration.
"""
import argparse
import hashlib
import json
import shutil
import time
from localai import ROOT, paths, save_json
from media_probe import image_graph, video_graph

BOOTSTRAP = '''import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";
app.registerExtension({name:"LocalAi.CurateNativeWorkflows", setup() { setTimeout(async () => {
 const bundle = await (await fetch(new URL("graphs.json", import.meta.url))).json();
 const previous = await api.getUserData("localai/curation.json");
 if (previous.status === 200) { const saved=await previous.json(); if(saved.status === "passed" && saved.revision === bundle.revision) return; }
 const report = {revision:bundle.revision, status:"running", results:[]};
 try {
  for (const item of bundle.graphs) {
   await app.loadApiJson(item.graph, item.name);
   const {workflow, output} = await app.graphToPrompt();
   if (!workflow.nodes?.length || !Object.keys(output).length) throw Error("Empty converted graph: " + item.name);
   await api.storeUserData("workflows/Ready-to-use/" + item.name + ".json", workflow);
   await api.storeUserData("localai/" + item.id + "-roundtrip.json", output);
   report.results.push({name:item.name, nodes:workflow.nodes.length});
  }
  report.status="passed";
 } catch(error) { report.status="failed"; report.error=String(error); console.error(error); }
 await api.storeUserData("localai/curation.json", report);
 if (report.status === "passed") await app.loadGraphData((await app.graphToPrompt()).workflow);
}, 2000); }});
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect',action='store_true')
    args=parser.parse_args();p=paths()
    installed=p['state']/'comfyui/default/workflows'
    extension=p['apps']/'ComfyUI/custom_nodes/localai_curate'
    names=[('qwen-image','01 Image - Qwen Image 2.1'),('chroma','02 Image - Chroma permissive'),
           ('h3','03 Video with audio - H3'),('wan-aio','04 Video - Wan AIO permissive')]
    if args.collect:
        report=json.loads((p['state']/'comfyui/default/localai/curation.json').read_text())
        if report['status']!='passed':raise RuntimeError(report)
        target=ROOT/'workflows/linux/ready';target.mkdir(parents=True,exist_ok=True)
        for key,name in names:
            source=installed/'Ready-to-use'/(name+'.json')
            graph=json.loads(source.read_text())
            if not graph.get('nodes'):raise RuntimeError('Not a native workflow: '+name)
            shutil.copy2(source,target/source.name)
        shutil.rmtree(extension)
        print('Saved four native workflows and removed the one-time converter.');return
    if installed.exists():
        archive=p['state']/'workflow-archive'/str(int(time.time()))
        archive.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(installed),str(archive))
        print('Previous workflows preserved at',archive)
    (installed/'Ready-to-use').mkdir(parents=True,exist_ok=True)
    graphs=[]
    for key,name in names:
        graph=image_graph(key,1024,28 if key=='chroma' else 40,48271) if key in ('qwen-image','chroma') else video_graph(key,8 if key=='h3' else 4,124 if key=='h3' else 81,832,480)
        if key=='wan-aio':
            # Unconditioned latent video: no fake first-frame requirement.
            del graph['4'];graph['5']['inputs'].pop('start_image',None)
        for node in graph.values():
            if 'filename_prefix' in node['inputs']:node['inputs']['filename_prefix']='LocalAI/'+key
        graphs.append({'id':key,'name':name,'graph':graph})
    revision=hashlib.sha256(json.dumps(graphs,sort_keys=True).encode()).hexdigest()
    web=extension/'web';web.mkdir(parents=True,exist_ok=True)
    (extension/'__init__.py').write_text('NODE_CLASS_MAPPINGS = {}\nWEB_DIRECTORY = "./web"\n')
    (web/'curate.js').write_text(BOOTSTRAP)
    save_json(web/'graphs.json',{'revision':revision,'graphs':graphs})
    print('Prepared graph-only conversion. Restart ComfyUI and open its UI, then use --collect.')

if __name__=='__main__':main()
