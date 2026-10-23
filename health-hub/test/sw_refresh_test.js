const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
async function check(fetcher,cached,options={}) {
  const writes=[];
  const context={self:{addEventListener(){}},caches:{open:async()=>({match:async key=>options.indexOnly ? (key==='index.html' ? new Response('offline index') : undefined) : (cached ? new Response(cached) : undefined),put:async(key,value)=>{if(options.storageFull)throw Error('quota');writes.push(await value.text());}})},fetch:fetcher,URL,Response,Headers,Date};
  vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/../web/sw.js','utf8'),context);
  const response=await context.shell({mode:'navigate'});
  return {status:response.status,body:await response.text(),writes};
}
(async()=>{
  assert.deepEqual(await check(async()=>new Response('fresh'),'old'),{status:200,body:'fresh',writes:['fresh']});
  assert.equal((await check(async()=>{throw Error('offline');},'old')).body,'old');
  assert.equal((await check(async()=>new Response('fresh'),'old',{storageFull:true})).body,'fresh');
  assert.equal((await check(async()=>new Response('unavailable',{status:503}),null,{indexOnly:true})).body,'offline index');
  assert.equal((await check(async()=>new Response('unavailable',{status:503}),'old')).body,'old');
  assert.equal((await check(async()=>new Response('unavailable',{status:503}))).status,503);
  await assert.rejects(()=>check(async()=>{throw Error('offline');}),/offline/);
  console.log('service-worker refresh and offline-fallback tests passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
