const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function setup(fetch){
  const starts=[];
  class AudioContext {
    constructor(){this.currentTime=0;this.state='suspended';}
    async resume(){this.state='running';}
    async suspend(){this.state='suspended';}
    async close(){this.state='closed';}
    createBuffer(channels,length,rate){return {duration:length/rate,copyToChannel(){}};}
    createBufferSource(){return {connect(){},disconnect(){},start(at){starts.push(at)}};}
  }
  const context=vm.createContext({window:{AudioContext},setInterval:()=>1,clearInterval(){},atob,Uint8Array,Float32Array,DataView,TextDecoder,fetch});
  vm.runInContext(fs.readFileSync('studio-stream.js','utf8')+'\nthis.LiveAudio=LiveAudio;this.generateStream=generateStream;',context);
  return {...context,starts};
}
test('chunks share a clock, pause preserves queue, underrun adds buffer, finish drains',async()=>{
  const {LiveAudio,starts}=setup();const status={},button={};const player=new LiveAudio(status,button);
  await player.start();
  const chunk={pcm:Buffer.from(new Float32Array(24000).buffer).toString('base64'),sample_rate:24000};
  player.append(chunk);player.append(chunk);
  assert.deepEqual(starts,[.25,1.25]);
  await player.toggle();assert.equal(player.context.state,'suspended');
  player.append(chunk);assert.equal(starts[2],2.25);
  await player.toggle();assert.equal(player.context.state,'running');
  player.context.currentTime=4;player.append(chunk);assert.equal(starts[3],4.25);
  player.finish();assert.ok(player.context);
  player.context.currentTime=6;player.render();assert.equal(player.context,null);assert.equal(button.hidden,true);
});
test('stopping preview ignores later chunks',async()=>{
  const {LiveAudio,starts}=setup();const player=new LiveAudio({},{});await player.start();player.stop();player.append({});assert.equal(starts.length,0);
});
function response(text){
  const bytes=new TextEncoder().encode(text);let i=0;
  return {ok:true,body:{getReader:()=>({async read(){return i<bytes.length?{value:bytes.slice(i,i+=3),done:false}:{done:true}},async cancel(){},releaseLock(){}})}};
}
test('NDJSON survives split UTF-8 and split lines',async()=>{
  const {generateStream}=setup(async()=>response('{"type":"start"}\n{"type":"audio"}\n{"type":"done","result":{"text":"你好"}}\n'));
  const events=[];const result=await generateStream({},e=>events.push(e.type));
  assert.equal(result.text,'你好');assert.deepEqual(events,['start','audio','done']);
});
test('partial response and explicit server error fail instead of reporting success',async()=>{
  for(const text of ['{"type":"start"}\n','{"type":"error","error":"busy"}\n']){
    const {generateStream}=setup(async()=>response(text));await assert.rejects(()=>generateStream({},()=>{}));
  }
});
