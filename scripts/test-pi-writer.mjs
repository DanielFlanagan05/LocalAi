import {mkdirSync,writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const root='C:/Users/danfl/dev/LocalAI';
process.env.PI_CODING_AGENT_DIR=`${root}/config/pi`;
process.env.PI_CODING_AGENT_SESSION_DIR=`${root}/config/pi/sessions`;
const {createAgentSession,SessionManager,ModelRuntime}=await import(pathToFileURL(`${root}/apps/PiHarness/runtime/pi-1.2.0/node_modules/@earendil-works/pi-coding-agent/dist/index.js`).href);
const runtime=await ModelRuntime.create({modelsPath:`${root}/config/pi/models.json`,authPath:`${root}/config/pi/auth.json`});
const model=runtime.getAllModels('lmstudio').find(m=>m.id==='dirty-shirley-9b-q4');
if(!model) throw Error('Writer not in Pi model list');
const out=`${root}/logs/dirty-shirley-functional`;
mkdirSync(out,{recursive:true});
const {session}=await createAgentSession({cwd:root,agentDir:`${root}/config/pi`,modelRuntime:runtime,model,thinkingLevel:'off',sessionManager:SessionManager.create(root,`${out}/sessions`)});
const results=[];
try {
for(const prompt of ['Remember the codeword MAPLE-593. Reply with only MAPLE-593.','What codeword did I give you? Reply with only the codeword.']){
const started=Date.now();await session.prompt(prompt);
const last=[...session.messages].reverse().find(m=>m.role==='assistant');
const result={seconds:(Date.now()-started)/1000,text:session.getLastAssistantText(),stopReason:last?.stopReason,error:last?.errorMessage,usage:last?.usage};
results.push(result);console.log(JSON.stringify(result));
if(last?.stopReason==='error'||!result.text?.includes('MAPLE-593'))throw Error('Writer Pi response failed');
}
writeFileSync(`${out}/pi-sdk-result.json`,JSON.stringify({success:true,model,results},null,2));
if(process.argv.includes('--switch')){
const qwen=runtime.getAllModels('strata').find(m=>m.id==='qwen3.6-35b-a3b-ud-q4_k_xl');
await session.setModel(qwen);
await session.prompt('Do not use tools. Reply exactly: QWEN-SWITCH-OK');
const qwenText=session.getLastAssistantText();
if(!qwenText?.includes('QWEN-SWITCH-OK'))throw Error(`Qwen switch failed: ${qwenText}`);
console.log('Qwen switch response:',qwenText);
await session.setModel(model);
await session.prompt('Reply exactly: WRITER-RETURN-OK');
const writerText=session.getLastAssistantText();
if(!writerText?.includes('WRITER-RETURN-OK'))throw Error(`Writer return failed: ${writerText}`);
writeFileSync(`${out}/switch-result.json`,JSON.stringify({success:true,qwenText,writerText},null,2));
console.log('PASS: writer -> Qwen/Strata -> writer, with sequential model loading.');
}
} finally {await session.dispose()}
