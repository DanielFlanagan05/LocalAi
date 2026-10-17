import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {mkdirSync,writeFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
const root='C:/Users/danfl/dev/LocalAI';
const require=createRequire(`${root}/apps/PiWebUI/node_modules/pi-web-ui/package.json`);
const WebSocket=require('ws');
const cwd=`${root}/workspaces/writer-check`;
mkdirSync(cwd,{recursive:true});
const token=spawnSync('powershell.exe',['-NoProfile','-File',`${root}/scripts/launchers/show-pi-web-ui-token.ps1`],{encoding:'utf8',windowsHide:true}).stdout.trim();
const base='https://daniels-desktop.tail632a33.ts.net';
const login=await fetch(`${base}/?token=${encodeURIComponent(token)}`);
const cookie=login.headers.get('set-cookie')?.split(';')[0];
if(!cookie)throw Error('Login cookie missing');
const ws=new WebSocket(`${base.replace('https:','wss:')}/ws`,{headers:{Cookie:cookie,Origin:base}});
const clientId=`writer-check-${randomUUID()}`;
const send=v=>ws.send(JSON.stringify(v));
let phase=0,start=0;
const timeout=setTimeout(()=>{console.error('Writer web test timed out');process.exitCode=1;ws.terminate()},120000);
const poll=setInterval(()=>{if(ws.readyState===WebSocket.OPEN)send({type:'get_state'})},1500);
ws.on('open',()=>send({type:'hello',clientId}));
ws.on('error',e=>{console.error(e.message);process.exitCode=1});
ws.on('message',raw=>{
const m=JSON.parse(raw);
if(m.type==='notice'&&m.level==='error')console.log('Web error:',m.textEn||m.text);
if(m.type==='models'&&phase===2&&m.models?.some(v=>v.id==='lmstudio/dirty-shirley-9b-q4')){phase=3;send({type:'set_model',modelId:'lmstudio/dirty-shirley-9b-q4'})}
if(m.type!=='snapshot')return;
const s=m.state;
if(phase===0){phase=1;send({type:'set_cwd',path:cwd});return}
if(phase===1&&s.cwd.replaceAll('\\','/').toLowerCase()===cwd.toLowerCase()){phase=2;send({type:'reload_models_config'});return}
if(phase===3&&s.model?.id==='dirty-shirley-9b-q4'){phase=4;start=Date.now();send({type:'prompt',text:'Write one short sentence about a lighthouse at dawn. Include the codeword LANTERN-216.'});return}
if(phase===4&&!s.isStreaming){
const reply=s.messages?.filter(v=>v.role==='assistant').at(-1);
if(!reply)return;
const result={success:reply.stopReason==='stop'&&JSON.stringify(reply.content).includes('LANTERN-216'),base,clientId,sessionId:s.sessionId,model:s.model,seconds:(Date.now()-start)/1000,reply,stats:s.stats};
writeFileSync(`${root}/logs/dirty-shirley-functional/pi-web-result.json`,JSON.stringify(result,null,2));
console.log(JSON.stringify(result));if(!result.success)process.exitCode=1;phase=5;ws.close();
}
});
ws.on('close',()=>{clearTimeout(timeout);clearInterval(poll)});
