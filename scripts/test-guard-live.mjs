// End-to-end Pi Web UI test with an isolated fake SSE backend, never real GPUs.
import {createServer} from 'node:http';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {mkdirSync,cpSync,openSync,readFileSync,writeFileSync,readdirSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import assert from 'node:assert/strict';
const root='C:/Users/danfl/dev/LocalAI';
const base=`${root}/tests/compute-guard-integration`;
const data=`${base}/data-${Date.now()}`;
mkdirSync(`${data}/plugins`,{recursive:true});
cpSync(`${root}/config/pi-web-ui/plugins/localai-resource-monitor`,`${data}/plugins/localai-resource-monitor`,{recursive:true});
// Wrapper is imported from its fixture location so its relative imports stay valid.
writeFileSync(`${data}/plugins/localai-resource-monitor/index.mjs`,`export {default} from ${JSON.stringify('file:///'+base+'/forced-policy.mjs')};\n`);
const require=createRequire(`${root}/apps/PiWebUI/node_modules/pi-web-ui/package.json`);
const WebSocket=require('ws');
const token=randomUUID();
let requests=0,oldDisconnected=false;
const mock=createServer((req,res)=>{
 if(req.url==='/v1/models'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({data:[{id:'guard-test',object:'model'}]}));return}
 if(req.url!=='/v1/chat/completions'){res.writeHead(404);res.end();return}
 let body='';req.on('data',d=>body+=d);req.on('end',()=>{
 const payload=JSON.parse(body);const current=++requests;
 res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache'});
 let n=0;const text=current===1?'OLD-PARTIAL ':'NEW-RUN-OK';
 const chunk=(delta,finish=null)=>res.write(`data: ${JSON.stringify({id:`test-${current}`,object:'chat.completion.chunk',created:Math.floor(Date.now()/1000),model:'guard-test',choices:[{index:0,delta,finish_reason:finish}]})}\n\n`);
 chunk({role:'assistant'});
 const timer=setInterval(()=>{
   if(current===1){chunk({content:n++===0?text:'still-writing '});return}
   chunk({content:text});chunk({},'stop');res.write('data: [DONE]\n\n');clearInterval(timer);res.end();
 },current===1?200:7000);
 res.on('close',()=>{clearInterval(timer);if(current===1)oldDisconnected=true});
 });
});
await new Promise((resolve,reject)=>{mock.once('error',reject);mock.listen(18792,'127.0.0.1',resolve)});
const log=openSync(`${data}/server.log`,'a');
const child=spawn(process.execPath,[`${root}/apps/PiWebUI/node_modules/pi-web-ui/bin/pi-web-ui.mjs`,'--no-browser','--agent-dir',`${base}/agent`,'--cwd',base,'--data-dir',data,'--host','127.0.0.1','--port','18791'],{env:{...process.env,PI_CODING_AGENT_DIR:`${base}/agent`,PI_CODING_AGENT_SESSION_DIR:`${data}/sessions`,PI_WEB_DATA_DIR:data,PI_WEB_TOKEN:token,PI_WEB_PORT:'18791',PI_WEB_HOST:'127.0.0.1'},windowsHide:true,stdio:['ignore',log,log]});
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const sockets=[];const notices=[];
async function until(check,seconds=45){const until=Date.now()+seconds*1000;while(Date.now()<until){if(await check())return;await delay(150)}throw Error('Timed out waiting for isolated test condition')}
async function client(id){
const ws=new WebSocket('ws://127.0.0.1:18791/ws',{headers:{Authorization:`Bearer ${token}`,Origin:'http://127.0.0.1:18791'}});sockets.push(ws);
const view={state:null};
ws.on('message',raw=>{const m=JSON.parse(raw);if(m.type==='snapshot')view.state=m.state;if(m.type==='notice'){notices.push(m.textEn||m.text);console.log('Test notice:',m.textEn||m.text)}});
await new Promise((r,j)=>{ws.once('open',r);ws.once('error',j)});
ws.send(JSON.stringify({type:'hello',clientId:id}));
const poll=setInterval(()=>{if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'get_state'}))},300);ws.on('close',()=>clearInterval(poll));
await until(()=>view.state);
const workspace=`${data}/workspaces/${id}`;
mkdirSync(workspace,{recursive:true});
ws.send(JSON.stringify({type:'set_cwd',path:workspace}));
await until(()=>view.state?.cwd?.replaceAll('\\','/').toLowerCase()===workspace.toLowerCase());
return {ws,view};
}
try {
await until(async()=>{try{return (await fetch('http://127.0.0.1:18791/api/health')).ok}catch{return false}});
console.log('Isolated server ready');
const a=await client('guard-owner-a');
console.log('First client ready',a.view.state.model);
a.ws.send(JSON.stringify({type:'prompt',text:'Keep writing the first test response.'}));
await until(()=>requests===1&&a.view.state?.isStreaming);
const b=await client('guard-owner-b');
assert.equal(a.view.state.conversationId,b.view.state.conversationId,'Test must exercise duplicate conversation IDs across clients');
b.ws.send(JSON.stringify({type:'prompt',text:'Reply NEW-RUN-OK.'}));
await until(()=>requests>=2);
await until(()=>oldDisconnected);
await until(()=>!b.view.state.isStreaming&&b.view.state.messages.some(m=>m.role==='assistant'&&JSON.stringify(m.content).includes('NEW-RUN-OK')));
assert(!notices.some(n=>n.includes('could not')),'No failed-preemption warning expected');
await until(()=>!a.view.state.isStreaming);
const firstPath=a.view.state.sessionFile;
const transcript=readFileSync(firstPath,'utf8');
assert(transcript.includes('Keep writing the first test response.'));
assert(transcript.includes('OLD-PARTIAL'));
const result={success:true,duplicateConversationId:a.view.state.conversationId,oldStreamInterrupted:oldDisconnected,newRunCompleted:true,oldTranscriptRetained:true,notices,data};
writeFileSync(`${root}/logs/compute-guard-live-result.json`,JSON.stringify(result,null,2));console.log(JSON.stringify(result));
} finally {
 for(const ws of sockets)ws.close();
 // Only this test-owned server is stopped; never touch the production Pi PID.
 child.kill();mock.closeAllConnections();mock.close();
}
