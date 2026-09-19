const $=id=>document.getElementById(id), keys=['language','temperature','top_k','top_p','repetition_penalty','max_new_tokens','seed','do_sample','xvec_only','instruct'];
let refs=[], history=[], selectedRef=null, selectedResult=null, localBusy=false, serverBusy=false, online=false, defaults={}, draft={}, activeModel=null, availableModels={};
try{draft=JSON.parse(localStorage.getItem('qwen-studio-draft')||localStorage.getItem('qwen-local-inputs')||'{}')||{}}catch{}
const liveAudio=new LiveAudio($('live-status'),$('live-toggle'));
const notice=t=>$('notice').textContent=t;
async function api(path,data){const response=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw Error(result.error||response.statusText);return result}
function params(){return Object.fromEntries(keys.map(k=>[k,$(k).type==='checkbox'?$(k).checked:$(k).type==='number'?Number($(k).value):$(k).value]))}
function applyParams(p){for(const k of keys)if(p[k]!==undefined){if($(k).type==='checkbox')$(k).checked=p[k];else $(k).value=p[k]}}
function remember(){try{localStorage.setItem('qwen-studio-draft',JSON.stringify({text:$('text').value,model:$('model').value,reference:selectedRef?.file,ref_name:$('ref-name').value,ref_text:$('transcript').value,settings:params()}))}catch{}}
function sync(){
  const busy=localBusy||serverBusy, available=availableModels[$('model').value]!==false;
  for(const id of ['go','load','unload','model','reuse'])$(id).disabled=busy||!online;
  $('go').disabled||=!selectedRef||!available;
  $('load').disabled||=!available||activeModel===$('model').value;
  $('unload').disabled||=!activeModel;
  $('load').textContent=activeModel===$('model').value?'模型已加载':activeModel?'切换并加载':'加载模型';
  $('reuse').disabled||=!selectedResult;
  $('save-ref').disabled=!selectedRef;$('delete').disabled=!selectedResult;
  $('chars').textContent=`${$('text').value.length} / 500 · 本地单次限制`;
  const name=$('ref-name').value||selectedRef?.name||'未选择素材';$('selected-name').textContent=name;
  $('voice-hint').textContent=selectedRef?`${name} · ${$('transcript').value.trim()&&!$('xvec_only').checked?'完整参考模式，使用音色和准确原文':'音色参考模式，仅提取声音特征'}`:'选择或添加一段声音素材，开始创作。';
  for(const k of ['temperature','top_k','top_p'])$(k).disabled=!$('do_sample').checked;
}
function card(title,body,meta,active,onClick,initial){const b=document.createElement('button');b.className='card'+(active?' active':'');b.setAttribute('aria-pressed',String(active));const h=document.createElement('div');h.className='card-title';if(initial){const a=document.createElement('span');a.className='avatar';a.textContent=initial;h.append(a)}const t=document.createElement('span');t.textContent=title;h.append(t);b.append(h);const p=document.createElement('p');p.textContent=body;b.append(p);if(meta){const s=document.createElement('small');s.textContent=meta;b.append(s)}b.onclick=onClick;return b}
function renderRefs(){ $('refs').replaceChildren();$('ref-count').textContent=refs.length;for(const r of refs)$('refs').append(card(r.name,r.text||'未填写原文 · 音色参考',r.seconds?`${r.seconds.toFixed(1)} 秒`:'本地音频',selectedRef?.file===r.file,()=>selectRef(r),r.name.slice(0,1)));if(!refs.length)$('refs').innerHTML='<div class="empty">添加第一段声音素材<br>让每个人物拥有自己的声音</div>'}
function selectRef(r){selectedRef=r;$('ref-name').value=r.name;$('transcript').value=r.text||'';$('ref-player').src='/reference/'+encodeURIComponent(r.file);renderRefs();sync();remember()}
function renderHistory(){ $('history').replaceChildren();$('history-count').textContent=history.length;for(const h of history)$('history').append(card(h.text||h.file,`${h.model||'历史作品'} · ${h.seconds??'—'} 秒 · 生成 ${h.elapsed??'—'} s`,h.file.replace('.wav',''),selectedResult?.file===h.file,()=>selectResult(h)));if(!history.length)$('history').innerHTML='<div class="empty">还没有生成作品<br>你的下一段声音，将出现在这里</div>'}
function selectResult(h,keepLive=false){if(!keepLive){liveAudio.stop();$('live-status').textContent=localBusy?'实时试听已停止，生成仍在继续':'生成时自动边生成边试听';}selectedResult=h;if(h){$('player').src=h.url;$('download').href=h.url;$('download').download=h.file;$('download').hidden=false;$('result-info').textContent=`${h.model||'历史作品'} · ${h.seconds??'—'} 秒 · ${h.mode||'本地生成'}${h.truncated?' · 达到长度上限，可能截断':''}`;}else{$('player').removeAttribute('src');$('player').load();$('download').hidden=true;$('result-info').textContent='选择作品，聆听生成结果。'}renderHistory();sync()}
async function library(){const s=await api('/library');refs=s.references;history=s.history;renderRefs();renderHistory();}
function renderStatus(s){
  online=true;serverBusy=s.task.busy;activeModel=s.active_model;availableModels=s.models;
  $('connection').textContent='本地引擎已连接';$('connection').parentElement.classList.remove('offline');
  $('model-state').textContent=activeModel?`${activeModel} 已加载`:'模型未加载 · 生成时自动加载';
  for(const option of $('model').options)option.disabled=!s.models[option.value];
  studioMonitor.render(s);sync();
}
async function poll(){try{const s=await api('/status'), wasBusy=serverBusy;renderStatus(s);if(wasBusy&&!s.task.busy&&!localBusy){await library();if(s.task.phase==='done'&&history[0])selectResult(history[0]);if(s.task.error)notice(s.task.error);}}catch{online=false;sync();$('connection').textContent='本地服务未连接';$('phase').textContent='连接中断';$('connection').parentElement.classList.add('offline');studioMonitor.offline();}setTimeout(poll,1000)}
async function action(fn){localBusy=true;sync();try{await fn()}catch(e){notice(e.message)}finally{localBusy=false;try{renderStatus(await api('/status'))}catch{online=false}sync()}}
for(const name of ['script','params'])$(name+'-tab').onclick=()=>{for(const tab of ['script','params']){$(tab+'-tab').classList.toggle('active',tab===name);$(tab+'-tab').setAttribute('aria-selected',String(tab===name));$(tab+'-pane').hidden=tab!==name}};
$('go').onclick=()=>{if(!$('text').value.trim()){notice('请输入朗读文字。');return}for(const k of keys)if(!$(k).checkValidity()){$('params-tab').click();$(k).reportValidity();return}remember();const data={text:$('text').value,reference:selectedRef.file,ref_text:$('transcript').value,model:$('model').value,settings:params()};action(async()=>{ $('player').pause();$('ref-player').pause();try{await liveAudio.start();notice('任务已提交，首段生成后自动试听。');const h=await generateStream(data,event=>{if(event.type==='audio')liveAudio.append(event)});liveAudio.finish();await library();selectResult(h,true);notice(`生成完成 · 推理 ${h.elapsed} s · 总耗时 ${h.total_elapsed} s${h.truncated?' · 达到上限，请检查结尾是否完整':''}`)}catch(e){liveAudio.stop();$('live-status').textContent='实时试听已结束 · '+e.message;throw e}})};
$('load').onclick=()=>action(async()=>{const s=await api('/model',{action:'load',model:$('model').value});notice(`模型已加载 · ${s.elapsed} s`)});
$('unload').onclick=()=>action(async()=>{await api('/model',{action:'unload'});notice('模型已卸载，显存已释放。')});
$('save-ref').onclick=async()=>{const b=$('save-ref');b.disabled=true;try{const r=await api('/references',{file:selectedRef.file,name:$('ref-name').value,text:$('transcript').value});selectedRef=r;await library();remember();notice('素材名称和原文已保存。')}catch(e){notice(e.message)}finally{b.disabled=false}};
$('add-ref').onclick=()=>{$('upload-error').hidden=true;$('add-dialog').showModal()};$('close-dialog').onclick=()=>$('add-dialog').close();
$('new-file').onchange=()=>{if(!$('new-name').value)$('new-name').value=$('new-file').files[0]?.name.replace(/\.[^.]+$/,'')||''};
$('add-form').onsubmit=async event=>{event.preventDefault();$('upload').disabled=true;try{const f=$('new-file').files[0];if(f.size>30*1024*1024)throw Error('音频不能超过 30 MB。');const audio=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('文件读取失败'));reader.readAsDataURL(f)});const r=await api('/references',{name:$('new-name').value,text:$('new-text').value,audio});await library();selectRef(r);$('add-dialog').close();$('add-form').reset();notice('新素材已添加并选中。')}catch(e){$('upload-error').hidden=false;$('upload-error').textContent=e.message}finally{$('upload').disabled=false}};
let deletingFile=null;
$('delete').onclick=()=>{
  deletingFile=selectedResult.file;
  $('delete-filename').textContent=deletingFile;
  document.querySelector('input[name="delete-mode"][value="trash"]').checked=true;
  $('delete-error').hidden=true;updateDeleteMode();$('delete-dialog').showModal();
};
function updateDeleteMode(){const permanent=document.querySelector('input[name="delete-mode"]:checked').value==='permanent';$('confirm-delete').textContent=permanent?'永久删除，不可恢复':'移入回收站';$('confirm-delete').className=permanent?'danger-solid':'primary';}
for(const radio of document.querySelectorAll('input[name="delete-mode"]'))radio.onchange=updateDeleteMode;
$('cancel-delete').onclick=()=>$('delete-dialog').close();
$('confirm-delete').onclick=async()=>{
  $('confirm-delete').disabled=true;$('cancel-delete').disabled=true;
  const mode=document.querySelector('input[name="delete-mode"]:checked').value;
  try{await api('/history/delete',{file:deletingFile,mode});$('delete-dialog').close();await library();selectResult(history[0]||null);notice(mode==='permanent'?'作品及参数文件已永久删除。':'作品已移到 generated/.trash。')}
  catch(e){$('delete-error').hidden=false;$('delete-error').textContent=e.message}
  finally{$('confirm-delete').disabled=false;$('cancel-delete').disabled=false}
};
$('reuse').onclick=()=>{const h=selectedResult;$('text').value=h.text||'';if(h.model)$('model').value=h.model;applyParams({...defaults,...h.settings,seed:h.seed??42});const r=refs.find(r=>r.file===h.reference);if(r){selectRef(r);$('transcript').value=h.ref_text||''}sync();remember();notice(r?'已复用该作品的文本、参考原文与参数。':'已复用文本与参数，请核对参考素材。')};
$('reset-params').onclick=()=>{applyParams(defaults);sync();remember()};$('refresh').onclick=async()=>{try{await library();if(selectedResult&&!history.some(h=>h.file===selectedResult.file))selectResult(history[0]||null);notice('作品列表已刷新。')}catch(e){notice(e.message)}};
for(const id of ['text','transcript','ref-name','model',...keys])for(const event of ['input','change'])$(id).addEventListener(event,()=>{sync();remember()});
for(const label of document.querySelectorAll('.param-grid label')){const help=label.querySelector('small');if(help)label.title=help.textContent;}
(async()=>{try{const s=await api('/status');defaults=s.defaults;await library();applyParams({...defaults,...draft.settings});$('text').value=draft.text??s.default_text;if(draft.model&&s.models[draft.model])$('model').value=draft.model;const savedDraft={...draft};if(refs.length)selectRef(refs.find(r=>r.file===savedDraft.reference)||refs[0]);if(selectedRef?.file===savedDraft.reference){$('transcript').value=savedDraft.ref_text??selectedRef.text;$('ref-name').value=savedDraft.ref_name||selectedRef.name}if(history.length)selectResult(history[0]);renderStatus(s);notice('工作台已就绪 · 音频与参数均保存在本机。');sync()}catch(e){notice('连接失败：'+e.message)}poll()})();

for(const id of ['player','ref-player'])$(id).addEventListener('play',()=>{liveAudio.stop();$('live-status').textContent='实时试听已停止';$(id==='player'?'ref-player':'player').pause()});
