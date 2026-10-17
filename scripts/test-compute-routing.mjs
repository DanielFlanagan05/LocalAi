import {test} from 'node:test';
import assert from 'node:assert/strict';
import {abortOwnedRun,runTarget} from '../apps/PiWebUI/node_modules/pi-web-ui/dist/server/localai-run-routing.mjs';
test('qualified duplicate conversation IDs abort only the exact owner',async()=>{
 const called=[];
 const client=owner=>({convs:new Map([['c1',{}]]),abortForPlugins:async id=>(called.push([owner,id]),{ok:true})});
 const service={clients:new Map([['phone',client('phone')],['desktop',client('desktop')]])};
 assert.deepEqual(await abortOwnedRun(service,runTarget('desktop','c1')),{ok:true});
 assert.deepEqual(called,[['desktop','c1']]);
 assert.equal((await abortOwnedRun(service,'c1')).ok,false);
 assert.equal(called.length,1);
});
test('stale owner is already stopped, never targets another browser',async()=>{
 const service={clients:new Map([['other',{convs:new Map([['c1',{}]]),abortForPlugins:()=>{throw Error('wrong client')}}]])};
 assert.equal((await abortOwnedRun(service,runTarget('gone','c1'))).alreadyStopped,true);
});
test('legacy unique IDs work and malformed qualified IDs fail closed',async()=>{
 const service={clients:new Map([['owner',{convs:new Map([['c2',{}]]),abortForPlugins:async()=>({ok:true})}]])};
 assert.equal((await abortOwnedRun(service,'c2')).ok,true);
 assert.equal((await abortOwnedRun(service,'localai-run:garbage')).ok,false);
});
