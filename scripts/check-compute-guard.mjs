import {readFileSync,writeFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {createConnection} from 'node:net';
const root='C:/Users/danfl/dev/LocalAI';
const require=createRequire(`${root}/apps/PiWebUI/node_modules/pi-web-ui/package.json`);
const WebSocket=require('ws');
const control=()=>new Promise((resolve,reject)=>{
 const socket=createConnection('\\\\.\\pipe\\pi-web-ui-8787');
 socket.on('connect',()=>socket.write('{"cmd":"status"}\n'));
 socket.on('data',raw=>{socket.end();resolve(JSON.parse(raw.toString()))});socket.on('error',reject);
});
const status=await control();
const reload=process.argv.includes('--reload');
if(reload&&(status.activeConversations||status.pendingMessages))throw Error('Pi is busy; refusing to reset the guard tracking map');
const states=JSON.parse(readFileSync(`${root}/config/pi-web-ui/client-state.json`,'utf8'));
const clientId=Object.keys(states).filter(k=>k!=='__settings__').sort((a,b)=>(states[b].lastActive||0)-(states[a].lastActive||0))[0];
const token=spawnSync('powershell.exe',['-NoProfile','-File',`${root}/scripts/launchers/show-pi-web-ui-token.ps1`],{encoding:'utf8',windowsHide:true}).stdout.trim();
const base='https://daniels-desktop.tail632a33.ts.net';
const login=await fetch(`${base}/?token=${encodeURIComponent(token)}`);
const cookie=login.headers.get('set-cookie')?.split(';')[0];
if(!cookie)throw Error('No login cookie');
const ws=new WebSocket(`${base.replace('https:','wss:')}/ws`,{headers:{Cookie:cookie,Origin:base}});
const timer=setTimeout(()=>{console.error('Guard live-status check timed out');process.exitCode=1;ws.terminate()},20000);
let sent=false,reloaded=!reload;
const requestStatus=()=>ws.send(JSON.stringify({type:'plugin_message',pluginId:'localai-resource-monitor',payload:{action:'localai-resource-monitor:status'}}));
ws.on('open',()=>ws.send(JSON.stringify({type:'hello',clientId})));
ws.on('message',raw=>{
 const m=JSON.parse(raw);
 if(m.type==='snapshot'&&!sent){sent=true;if(reload)ws.send(JSON.stringify({type:'plugins_reload'}));else requestStatus()}
 if(m.type==='plugins'&&sent&&!reloaded){reloaded=true;requestStatus()}
 if(m.type==='notice'){
  const text=m.textEn||m.text||'';
  if(text.startsWith('Compute:')){const result={success:true,authenticatedThrough:base,serverPid:status.pid,reloaded,status:text};writeFileSync(`${root}/logs/compute-guard-production-check.json`,JSON.stringify(result,null,2));console.log(JSON.stringify(result));ws.close()}
  if(text.includes('GPU counters unavailable')){console.error(text);process.exitCode=1;ws.close()}
 }
});
ws.on('close',()=>clearTimeout(timer));ws.on('error',()=>{console.error('Guard check WebSocket failed');process.exitCode=1});
