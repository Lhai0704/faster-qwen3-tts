// One audio clock schedules every chunk, including while playback is paused.
class LiveAudio {
  constructor(status, button) { this.status=status; this.button=button; this.context=null; this.timer=null; }
  async start() {
    this.stop();
    const Context=window.AudioContext||window.webkitAudioContext;
    if(!Context)throw Error('浏览器不支持实时试听，请使用新版 Chrome 或 Edge。');
    this.context=new Context();
    this.end=0;this.received=0;this.finished=false;this.stopped=false;
    this.button.hidden=false;this.button.textContent='暂停试听';
    this.button.onclick=()=>this.toggle();
    await this.context.resume();
    this.timer=setInterval(()=>this.render(),150);this.render();
  }
  append(event) {
    if(this.stopped)return;
    const bytes=Uint8Array.from(atob(event.pcm),c=>c.charCodeAt(0));
    if(bytes.length%4||!event.sample_rate)throw Error('收到无效音频片段。');
    const view=new DataView(bytes.buffer), samples=new Float32Array(bytes.length/4);
    for(let i=0;i<samples.length;i++)samples[i]=view.getFloat32(i*4,true);
    if(!samples.length)return;
    const buffer=this.context.createBuffer(1,samples.length,event.sample_rate);
    buffer.copyToChannel(samples,0);
    const source=this.context.createBufferSource();source.buffer=buffer;source.connect(this.context.destination);
    // Small initial/rebuffer delay absorbs delivery jitter; contiguous chunks share a clock.
    const at=this.end>this.context.currentTime?this.end:this.context.currentTime+0.25;
    source.start(at);source.onended=()=>source.disconnect();
    this.end=at+buffer.duration;this.received+=buffer.duration;this.render();
  }
  async toggle() {
    if(!this.context)return;
    try {
      if(this.context.state==='running')await this.context.suspend();else await this.context.resume();
      this.button.textContent=this.context.state==='running'?'暂停试听':'继续试听';this.render();
    } catch { this.status.textContent='试听无法恢复，可在生成完成后播放作品。'; }
  }
  render() {
    if(!this.context||this.stopped)return;
    const left=Math.max(0,this.end-this.context.currentTime);
    if(this.finished&&left===0){this.stop();this.status.textContent='实时试听结束 · 可用下方播放器重播';return;}
    const state=this.context.state!=='running'?'试听已暂停':left>0?'正在试听':this.received?'缓冲中':'等待首段音频';
    this.status.textContent=`${state} · 已接收 ${this.received.toFixed(1)} 秒 · 缓冲 ${left.toFixed(1)} 秒`;
  }
  finish(){this.finished=true;this.render();}
  stop(){clearInterval(this.timer);if(this.context)this.context.close().catch(()=>{});this.context=null;this.stopped=true;this.button.hidden=true;}
}

async function generateStream(data, onEvent) {
  const response=await fetch('/generate/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(!response.ok){const error=await response.json();throw Error(error.error||response.statusText);}
  if(!response.body)throw Error('浏览器不支持流式响应。');
  const reader=response.body.getReader(), decoder=new TextDecoder();
  let pending='', result=null;
  function consume(line){
    if(!line.trim())return;
    const event=JSON.parse(line);
    if(event.type==='error')throw Error(event.error);
    if(event.type==='done')result=event.result;
    onEvent(event);
  }
  try {
    while(true){const {value,done}=await reader.read();pending+=decoder.decode(value,{stream:!done});let index;
      while((index=pending.indexOf('\n'))!==-1){consume(pending.slice(0,index));pending=pending.slice(index+1);}
      if(done)break;
    }
    consume(pending);
    if(!result)throw Error('试听连接中断，请查看任务进度；完成的音频仍会保存在作品列表。');
    return result;
  } finally {await reader.cancel().catch(()=>{});reader.releaseLock();}
}
