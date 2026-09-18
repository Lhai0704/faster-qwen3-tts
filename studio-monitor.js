/* Live charts contain only samples returned by the local monitoring service. */
window.studioMonitor = (() => {
  const get = id => document.getElementById(id);
  const number = (value, digits = 0) => Number.isFinite(value) ? value.toFixed(digits) : '—';
  const metrics = {
    cpu: {key:'cpu_utilization', label:'CPU 使用率', unit:'%', color:'#5472d3', ceiling:100},
    gpu: {key:'gpu_utilization', label:'GPU 使用率', unit:'%', color:'#269080', ceiling:100},
    memory: {key:'gpu_memory', label:'GPU 显存', unit:'GB', color:'#269080', divisor:1024, digits:1},
    temperature: {key:'gpu_temperature', label:'GPU 温度', unit:'°C', color:'#c18440', ceiling:100},
    power: {key:'gpu_power', label:'GPU 功率', unit:'W', color:'#9270c5', digits:1},
  };
  const cards = [];
  let latest = null;
  function initialize() {
    if (cards.length) return;
    for (const [index, name] of ['cpu','gpu','temperature','power'].entries()) {
      const root = document.createElement('div');
      root.className = 'chart-card';
      root.innerHTML = `<div class="chart-title"></div><div class="chart-value"></div><div class="chart-plot"><svg viewBox="0 0 220 70" preserveAspectRatio="none" role="img"></svg><div class="chart-tip" hidden></div></div><div class="chart-axis"><span>−60s</span><span>现在</span></div><div class="chart-caption"></div>`;
      const chart = {root, metric:name, index, samples:[]};
      if (name === 'gpu') {
        const select = document.createElement('select');
        select.setAttribute('aria-label','GPU 图表指标');
        for (const key of ['gpu','memory']) {const option=document.createElement('option');option.value=key;option.textContent=metrics[key].label;select.append(option);}
        select.onchange=()=>{chart.metric=select.value;if(latest)draw(chart,latest);};
        root.querySelector('.chart-title').append(select);
      } else root.querySelector('.chart-title').textContent=metrics[name].label;
      const plot = root.querySelector('.chart-plot');
      plot.onpointermove = event => {
        const samples = chart.samples.filter(s=>Number.isFinite(s.value));
        const tip=root.querySelector('.chart-tip');
        if (!samples.length) {tip.hidden=true;return;}
        const bounds=plot.getBoundingClientRect(), fraction=Math.min(1,Math.max(0,(event.clientX-bounds.left)/bounds.width));
        const target=chart.end-60+fraction*60;
        const point=samples.reduce((a,b)=>Math.abs(a.at-target)<Math.abs(b.at-target)?a:b);
        const m=metrics[chart.metric];
        tip.textContent=`${new Date(point.at*1000).toLocaleTimeString()} · ${number(point.value,m.digits||0)} ${m.unit}`;
        tip.hidden=false;
      };
      plot.onpointerleave=()=>root.querySelector('.chart-tip').hidden=true;
      get('charts').append(root);cards.push(chart);
    }
  }
  function draw(chart, state) {
    const m=metrics[chart.metric], raw=state.telemetry||[], end=raw.at(-1)?.at||Date.now()/1000;
    const samples=raw.map(s=>({at:s.at,value:Number.isFinite(s[m.key])?s[m.key]/(m.divisor||1):null}));
    chart.samples=samples;chart.end=end;
    const value=samples.at(-1)?.value;
    let ceiling=m.ceiling||(chart.metric==='memory'?state.gpu.total_mb/1024:Math.max(30,...samples.map(s=>s.value||0)));
    if(!Number.isFinite(ceiling)||ceiling<=0)ceiling=1;
    if(chart.metric==='power')ceiling=Math.ceil(ceiling/10)*10;
    const root=chart.root, svg=root.querySelector('svg');
    root.style.setProperty('--chart-color',m.color);
    const heading=root.querySelector('.chart-value');heading.replaceChildren(document.createTextNode(number(value,m.digits||0)));
    const unit=document.createElement('span');unit.textContent=m.unit;heading.append(unit);
    const segments=[];let segment=[];
    for(const s of samples) {
      if(s.value===null){if(segment.length)segments.push(segment);segment=[];continue;}
      if(segment.length&&s.at-segment.at(-1).at>3){segments.push(segment);segment=[];}
      segment.push({...s,x:Math.max(0,Math.min(220,(s.at-end+60)/60*220)),y:65-Math.min(1,Math.max(0,s.value/ceiling))*57});
    }
    if(segment.length)segments.push(segment);
    let content=`<defs><linearGradient id="fade-${chart.index}" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="${m.color}" stop-opacity=".18"/><stop offset="100%" stop-color="${m.color}" stop-opacity=".015"/></linearGradient></defs>`;
    for(const y of [8,36,65])content+=`<path d="M0 ${y}H220" stroke="#e6ebf3" stroke-width=".8" stroke-dasharray="3 3"/>`;
    content+=`<text x="0" y="7" fill="#8995a6" font-size="8">${number(ceiling,chart.metric==='memory'?1:0)}</text>`;
    for(const points of segments){const line=points.map((p,i)=>`${i?'L':'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');content+=`<path d="${line} L${points.at(-1).x} 65 L${points[0].x} 65 Z" fill="url(#fade-${chart.index})"/><path d="${line}" stroke="${m.color}" fill="none" stroke-width="1.8" stroke-linejoin="round"/>`;}
    const last=segments.at(-1)?.at(-1);if(last&&value!==null&&value!==undefined)content+=`<circle cx="${last.x}" cy="${last.y}" r="2.5" fill="${m.color}"/>`;
    if(!samples.some(s=>s.value!==null))content+='<text x="110" y="40" text-anchor="middle" fill="#8b96a5" font-size="10">等待有效采样</text>';
    svg.innerHTML=content;
    svg.setAttribute('aria-label',`${m.label}，当前 ${number(value,m.digits||0)} ${m.unit}，最近 60 秒趋势`);
    const g=state.gpu;
    const captions={cpu:`${state.cpu?.cores||'—'} 逻辑核心 · 整机占用`,gpu:`显存 ${number(g.used_mb==null?null:g.used_mb/1024,1)} / ${number(g.total_mb==null?null:g.total_mb/1024,1)} GB`,memory:`GPU 当前使用率 ${number(g.utilization)} %`,temperature:g.fan==null?'风扇转速：未提供':`风扇 ${number(g.fan)} %`,power:'实际采样 · 自动纵轴'};
    root.querySelector('.chart-caption').textContent=captions[chart.metric];
  }
  function render(state) {
    initialize();latest=state;
    for(const card of cards)draw(card,state);
    get('charts').style.opacity='1';
    get('sampling-note').textContent='最近 60 秒 · 每秒采样';
    get('gpu-name').textContent=state.gpu.available?state.gpu.name:'GPU 监控暂不可用';
    get('cpu-sensors').title=state.cpu?.sensor_note||'CPU 温度与功率未提供';
    renderTask(state);
  }
  function renderTask(state) {
    const t=state.task, generating=t.kind==='generate'||!t.kind;
    const phases=generating?['loading','preparing','encoding','generating','saving']:[t.kind==='unloading'?'unloading':'loading'];
    const labels={loading:t.load_reused?'模型就绪':'加载模型',preparing:'处理素材',encoding:'编码预热',generating:'生成声音',saving:'保存作品',unloading:'释放显存'};
    const index=phases.indexOf(t.phase), done=t.phase==='done', failed=t.phase==='error';
    const panel=document.querySelector('.task-panel');panel.classList.toggle('running',t.busy);panel.classList.toggle('failed',failed);
    get('phase').textContent=done?(generating?'声音已生成':t.kind==='unloading'?'模型已卸载':'模型已就绪'):failed?'任务失败':t.phase==='idle'?'准备就绪':labels[t.phase]||t.phase;
    get('task-label').textContent=t.busy?`步骤 ${Math.max(1,index+1)} / ${phases.length} · 进行中`:done?`已完成 · ${phases.length} / ${phases.length}`:failed?'任务已停止':'生成任务';
    get('task-icon').textContent=done?'✓':failed?'!':t.busy?'◌':'○';
    get('elapsed').textContent=t.phase==='idle'?'—':`${number(t.elapsed,1)} s`;
    get('stages').replaceChildren();
    for(const [i,phase] of phases.entries()){
      const li=document.createElement('li'),complete=done||(t.completed||[]).includes(phase),current=phase===t.phase;
      li.className=complete?'complete':current?'current':'';
      if(current)li.setAttribute('aria-current','step');
      const circle=document.createElement('b');circle.textContent=complete?'✓':String(i+1);
      li.append(circle,document.createTextNode(labels[phase]));get('stages').append(li);
    }
    get('progress-detail').textContent=failed?t.error:t.audio_seconds?`已生成 ${number(t.audio_seconds,2)} 秒音频 · ${t.steps} tokens`:t.busy?`${labels[t.phase]||'正在处理'} · 当前阶段 ${number(t.phase_elapsed,1)} s`:done?(t.kind==='unloading'?'显存已释放，可重新加载模型。':'模型已准备好，可以开始生成。'):'选择素材，输入文字后开始生成。';
    const last=state.last_load;
    get('load-time').textContent=t.phase==='loading'&&!t.load_reused?'正在加载模型…':last?`${t.load_reused?'复用模型 · 最近加载':'最近加载'} ${last.model} / ${number(last.seconds,2)} s`:'尚无加载记录';
    get('gen-time').textContent=t.kind==='generate'&&t.phase!=='loading'?`生成用时 ${number(Math.max(0,t.elapsed-(t.load_elapsed||0)),1)} s`:'生成用时 —';
    get('task-detail').textContent=t.load_reused?'本次复用已加载模型，无需重新加载。':t.phase==='encoding'?'首次生成可能包含 CUDA 图预热。':t.busy?'按实际阶段推进，音频时长持续更新。':'阶段进度不代表预计完成百分比。';
  }
  function offline(){get('sampling-note').textContent='连接中断 · 曲线暂停';get('charts').style.opacity='.5';}
  return {render,offline};
})();
