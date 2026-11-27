'use strict';
const $ = (id) => document.getElementById(id);
const input = $('inputText');
const state = {analysis:null, cleaned:null, source:'sample.txt', filter:'all', chart:null, barChart:null, revision:0};
const sample = '# A little more clarity\n\nGood writing is about more than the words we see.\u200b Sometimes, the smallest details are hidden in plain sight.\n\nHere’s a short note—with a few characters worth reviewing:\n\n• Take a closer look at your text\n• Keep the details that matter\n☐ Review the document\n☑ Share with confidence\n\nA non-breaking\u00a0space, a hidden marker\ufeff, and a direction override\u202e live here.\nNames and words matter too: ı, š, Ö, Ç, ğ, ć, Ü, Ş, č.';
let toastTimer;
function toast(message) { const el=$('toast'); el.textContent=message; el.classList.add('show'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>el.classList.remove('show'),4500); }
async function api(path, options={}) {
  let response;
  try { response=await fetch(path, options); } catch { throw new Error('Cannot reach the Python engine. Check that the server is running.'); }
  if (!response.ok) { let data; try {data=await response.json();} catch {data={};} const detail=data.detail; throw new Error(typeof detail==='string'?detail:`Request failed (${response.status}).`); }
  return response;
}
function post(path, data) {return api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});}
function setBusy(button, busy, label) {if(busy){button.dataset.label=button.innerHTML;button.disabled=true;button.textContent=label;}else{button.innerHTML=button.dataset.label||button.innerHTML;button.disabled=false;}}
function updateEditorCount(){ $('editorCount').textContent=Array.from(input.value).length.toLocaleString(); }
function invalidate() {
  state.revision++; state.analysis=null; state.cleaned=null;
  updateEditorCount(); render();
}
function resetSample() {input.value=sample;state.source='sample.txt';$('sourceName').textContent=state.source;$('documentLabel').textContent='Sample document';invalidate(); analyze();}
async function analyze() {
  const text=input.value, revision=state.revision;
  if (!text) {toast('Add some text before analyzing.');return;}
  setBusy($('analyzeBtn'),true,'Analyzing…');
  try {const res=await post('/api/analyze',{text}); const data=await res.json();if(revision!==state.revision){toast('Text changed; please analyze again.');return;} state.analysis=data;state.cleaned=null;render();toast('Analysis complete. Findings are not proof of an AI watermark.');}
  catch(e){toast(e.message);} finally{setBusy($('analyzeBtn'),false);}
}
async function clean() {
  const text=input.value, revision=state.revision;
  if (!text){toast('Add some text before cleaning.');return;}
  const mode=$('mode').value;
  if(mode==='aggressive'&&!confirm('Aggressive mode drops non-ASCII characters and can damage languages, emoji and code. Continue?')) return;
  const custom_exclusions=$('exclusions').value.split(',').map(x=>x.trim().toUpperCase()).filter(Boolean);
  setBusy($('cleanBtn'),true,'Cleaning…');
  try {const res=await post('/api/clean',{text,mode,custom_exclusions});const data=await res.json();if(revision!==state.revision){toast('Text changed; please clean again.');return;} state.analysis=data.before;state.cleaned=data;render();selectTab('diff');toast(`${data.summary.changed} character changes. Please review the result before exporting.`);}
  catch(e){toast(e.message);}finally{setBusy($('cleanBtn'),false);}
}
function setText(id,value){$(id).textContent=value;}
function renderMetrics(){
  const s=state.analysis?.stats;
  setText('totalChars',s?s.total_chars.toLocaleString():'—');setText('totalWords',s?`${s.total_words.toLocaleString()} words`:'— words');
  setText('totalFindings',s?s.total_findings.toLocaleString():'—');setText('findingsSub',s?`${s.invisible_count} invisible · ${s.visible_count} visible`:'Analyze text to inspect');
  setText('attention',s?s.attention_index:'—');setText('density',s?`${s.watermark_density} per 1,000 chars`:'— per 1,000 chars');
  setText('docStatus',state.cleaned?'Changes ready':s?(s.total_findings?'Review suggested':'No findings'):'Ready to inspect');
  setText('statusSub',state.cleaned?`${state.cleaned.summary.changed} changes made`:'Your original stays intact');
  setText('chartTotal',s?s.total_findings:0);setText('formatCount',s?s.format_count:0);setText('separatorCount',s?s.separator_count:0);
  setText('visibleCount',s?s.visible_count:0);setText('otherCount',s?s.other_invisible_count:0);
  drawChart(s); drawBarChart();
}
function drawChart(s) {
  if(typeof Chart==='undefined') return;
  const values=s?[s.format_count,s.separator_count,s.visible_count,s.other_invisible_count]:[0,0,0,0];
  const empty=!values.some(Boolean);
  if(!state.chart){state.chart=new Chart($('donutChart'),{type:'doughnut',data:{labels:['Format controls','Special spaces','Visible characters','Other invisible'],datasets:[{data:empty?[1]:values,backgroundColor:empty?['#343340']:['#e58d81','#e8b978','#a994f5','#69b6a6'],borderWidth:0,spacing:3,borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,cutout:'79%',plugins:{legend:{display:false},tooltip:{enabled:!empty}}}});}
  else{state.chart.data.datasets[0].data=empty?[1]:values;state.chart.data.datasets[0].backgroundColor=empty?['#343340']:['#e58d81','#e8b978','#a994f5','#69b6a6'];state.chart.options.plugins.tooltip.enabled=!empty;state.chart.update();}
}
function drawBarChart(){
  if(typeof Chart==='undefined') return;
  const findings=(state.analysis?.detected_characters||[]).slice(0,8);
  $('barEmpty').hidden=findings.length>0;
  if(!state.barChart){state.barChart=new Chart($('barChart'),{type:'bar',data:{labels:[],datasets:[{label:'Occurrences',data:[],backgroundColor:'#a994f5',borderRadius:4,barThickness:11}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{beginAtZero:true,grid:{color:'#393848'},ticks:{color:'#8b8c9d',precision:0}},y:{grid:{display:false},ticks:{color:'#a8a5b8'}}}}});}
  state.barChart.data.labels=findings.map(f=>f.unicode_code);state.barChart.data.datasets[0].data=findings.map(f=>f.count);state.barChart.update();
}
function renderXray(){
  const box=$('xrayText');box.replaceChildren();const findings=state.analysis?.detected_characters||[];
  setText('xrayCount',state.analysis?.stats.total_findings??0);$('xrayLimit').hidden=true;
  if(!state.analysis){box.textContent=input.value?'Analyze your text to reveal flagged characters.':'Your inspected text will appear here.';return;}
  const lookup=new Map(findings.map(f=>[f.original_char,f]));const frag=document.createDocumentFragment();let plain='',count=0;
  function flush(){if(plain){frag.append(document.createTextNode(plain));plain='';}}
  for(const ch of input.value){const f=lookup.get(ch);if(!f||count>=10000){plain+=ch;continue;}flush();count++;
    const span=document.createElement('span');span.className=f.kind==='visible'?'xray-visible':'xray-badge';span.textContent=f.kind==='visible'?ch:`[${f.unicode_code}]`;span.title=`${f.unicode_code} · ${f.name} · ${f.clean_action}`;frag.append(span);}
  flush();box.append(frag);$('xrayLimit').hidden=(state.analysis.stats.total_findings<=10000);
}
function renderFindings(){
 const body=$('findingsBody');body.replaceChildren();const all=state.analysis?.detected_characters||[];
 const list=all.filter(f=>state.filter==='all'||(state.filter==='visible'?f.kind==='visible':f.kind!=='visible'));
 setText('findingTypes',`${all.length} ${all.length===1?'type':'types'}`);setText('tableSummary',`${list.length} of ${all.length} character types`);
 if(!list.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=6;td.className='empty-row';td.textContent=state.analysis?'No characters in this filter.':'Analyze your text to see findings.';tr.append(td);body.append(tr);return;}
 const fragment=document.createDocumentFragment();
 for(const f of list){const tr=document.createElement('tr');const td=()=>{const e=document.createElement('td');tr.append(e);return e;};
  let cell=td(),tag=document.createElement('span');tag.className='char-tag'+(f.kind==='visible'?' visible':'');tag.textContent=f.char;cell.append(tag);
  cell=td();cell.className='code';cell.textContent=f.unicode_code;td().textContent=f.name_type;td().textContent=f.count.toLocaleString();
  cell=td();f.positions.slice(0,10).forEach((p,index)=>{const btn=document.createElement('button');btn.className='position-button';btn.textContent=p+(index<Math.min(f.positions.length,10)-1?',':'');btn.title='Select in editor';btn.addEventListener('click',()=>jumpTo(p));cell.append(btn);});
  if(f.positions.length>10){const more=document.createElement('button');more.className='more-positions';more.textContent=`View all ${f.count.toLocaleString()} positions →`;more.addEventListener('click',()=>showPositions(f));cell.append(more);}
  td().textContent=f.clean_action;fragment.append(tr);
 }body.append(fragment);
}
function jumpTo(position){ const offset=Array.from(input.value).slice(0,position).join('').length;const length=Array.from(input.value)[position]?.length||1;input.focus();input.setSelectionRange(offset,offset+length);input.scrollIntoView({behavior:'smooth',block:'center'}); }
function showPositions(f){
 const box=$('allPositions');let page=0;const pageSize=200;const pages=Math.ceil(f.positions.length/pageSize);
 setText('dialogTitle',`${f.unicode_code} · ${f.count.toLocaleString()} positions`);
 function drawPage(){box.replaceChildren();const nav=document.createElement('div');nav.className='position-pagination';
  const previous=document.createElement('button'),next=document.createElement('button'),label=document.createElement('span');previous.textContent='← Previous';next.textContent='Next →';previous.disabled=page===0;next.disabled=page===pages-1;label.textContent=`Page ${page+1} of ${pages}`;previous.onclick=()=>{page--;drawPage();};next.onclick=()=>{page++;drawPage();};nav.append(previous,label,next);box.append(nav);
  const frag=document.createDocumentFragment();for(const position of f.positions.slice(page*pageSize,(page+1)*pageSize)){const b=document.createElement('button');b.textContent=position;b.onclick=()=>{$('positionsDialog').close();jumpTo(position);};frag.append(b);}box.append(frag);box.scrollTop=0;
 }drawPage();$('positionsDialog').showModal();
}
function renderPreview(){
  const text=state.cleaned?.cleaned_text??input.value;const root=$('markdownPreview');root.replaceChildren();let list=null,codeBlock=null;
  for(const line of text.split('\n')){
    if(line.startsWith('```')){if(codeBlock){codeBlock=null;}else{codeBlock=document.createElement('pre');root.append(codeBlock);}list=null;continue;}
    if(codeBlock){codeBlock.textContent+=line+'\n';continue;}
    const heading=line.match(/^(#{1,6})\s+(.+)$/),item=line.match(/^\s*[-*+]\s+(.+)$/);
    if(heading){const el=document.createElement('h'+Math.min(heading[1].length,3));el.textContent=heading[2];root.append(el);list=null;}
    else if(item){if(!list){list=document.createElement('ul');root.append(list);}const el=document.createElement('li');el.textContent=item[1];list.append(el);}
    else{list=null;const el=document.createElement('p');el.textContent=line||'\u00a0';root.append(el);}
  }
}
function render(){renderMetrics();renderXray();renderFindings();setText('beforeText',input.value||'Your original text will appear here.');setText('afterText',state.cleaned?state.cleaned.cleaned_text:'Clean your text to see the result here.');renderPreview();}
function selectTab(name){document.querySelectorAll('.tab').forEach(t=>{const active=t.dataset.tab===name;t.classList.toggle('active',active);t.setAttribute('aria-selected',String(active));});document.querySelectorAll('.tab-content').forEach(el=>el.classList.toggle('active',el.id===name));}
async function loadReference(){try{const response=await api('/api/reference');const data=await response.json();const root=$('referenceList');root.replaceChildren();for(const item of data.hidden){const row=document.createElement('div');row.className='reference-item';const code=document.createElement('span');code.className='code';code.textContent=item.unicode_code;const detail=document.createElement('span');const name=document.createElement('strong');name.textContent=item.name;const description=document.createElement('small');description.textContent=item.why_it_matters;detail.append(name,description);const cat=document.createElement('span');cat.className='ref-cat';cat.textContent=item.type;row.append(code,detail,cat);root.append(row);}}catch(e){$('referenceList').textContent=e.message;}}
async function upload(file){
 if(!file)return;if(file.size>10*1024*1024){toast('File exceeds 10 MB.');return;}const form=new FormData();form.append('file',file);const revision=state.revision;
 try{toast('Reading document…');const res=await api('/api/upload-analyze',{method:'POST',body:form});const data=await res.json();if(revision!==state.revision){toast('Text changed while uploading; try again.');return;}input.value=data.text;state.source=data.filename;$('sourceName').textContent=data.filename;$('documentLabel').textContent='Uploaded document';invalidate();state.analysis=data.analysis;render();toast(data.notice);}catch(e){toast(e.message);}finally{$('fileInput').value='';}
}
function downloadBlob(blob,name){const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function downloadFile(format){if(!state.cleaned){toast('Clean your text first, then export the reviewed result.');return;}try{const res=await post('/api/export-file',{text:state.cleaned.cleaned_text,format,filename:'unicodeguard-clean'});downloadBlob(await res.blob(),`unicodeguard-clean.${format}`);toast(`${format.toUpperCase()} downloaded.`);}catch(e){toast(e.message);}}
function exportAudit(format){if(!state.analysis){toast('Analyze text first to export the audit.');return;}let data,mime;if(format==='json'){data=JSON.stringify({analysis:state.analysis,cleaning:state.cleaned},null,2);mime='application/json';}else{const rows=[['Char','Unicode','Name / Type','Count','Positions','Clean Action'],...state.analysis.detected_characters.map(f=>[f.char,f.unicode_code,f.name_type,f.count,f.positions.join('; '),f.clean_action])];data=rows.map(r=>r.map(x=>{let v=String(x);if(/^[=+@\-\t\r]/.test(v))v="'"+v;return '"'+v.replace(/"/g,'""')+'"';}).join(',')).join('\r\n');mime='text/csv';}downloadBlob(new Blob([data],{type:mime+';charset=utf-8'}),`unicodeguard-audit.${format}`);}

$('loadSample').addEventListener('click',resetSample);$('clearInput').addEventListener('click',()=>{input.value='';state.source='';$('sourceName').textContent='';$('documentLabel').textContent='Untitled document';invalidate();});input.addEventListener('input',invalidate);
$('analyzeBtn').addEventListener('click',analyze);$('cleanBtn').addEventListener('click',clean);
$('mode').addEventListener('change',()=>{state.revision++;if(state.cleaned){state.cleaned=null;render();toast('Mode changed. Clean again before exporting.');}});$('exclusions').addEventListener('input',()=>{state.revision++;if(state.cleaned){state.cleaned=null;render();}});
document.querySelectorAll('.tab').forEach(el=>el.addEventListener('click',()=>selectTab(el.dataset.tab)));
document.querySelectorAll('.filter').forEach(el=>el.addEventListener('click',()=>{document.querySelectorAll('.filter').forEach(x=>x.classList.remove('active'));el.classList.add('active');state.filter=el.dataset.filter;renderFindings();}));
$('closeDialog').addEventListener('click',()=>$('positionsDialog').close());$('csvBtn').onclick=()=>exportAudit('csv');$('jsonBtn').onclick=()=>exportAudit('json');
$('fileInput').addEventListener('change',e=>upload(e.target.files[0]));const drop=$('dropzone');drop.onclick=e=>{if(e.target!==$('fileInput'))$('fileInput').click();};drop.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('fileInput').click();}};for(const event of ['dragenter','dragover'])drop.addEventListener(event,e=>{e.preventDefault();drop.classList.add('dragging');});for(const event of ['dragleave','drop'])drop.addEventListener(event,e=>{e.preventDefault();drop.classList.remove('dragging');});drop.addEventListener('drop',e=>upload(e.dataTransfer.files[0]));
$('copyBtn').onclick=async()=>{if(!state.cleaned){toast('Clean your text first.');return;}try{await navigator.clipboard.writeText(state.cleaned.cleaned_text);toast('Cleaned text copied.');}catch{toast('Clipboard unavailable. Use a download instead.');}};
document.querySelectorAll('[data-export]').forEach(b=>b.onclick=()=>downloadFile(b.dataset.export));
$('themeToggle').onclick=()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;try{localStorage.setItem('unicodeguard-theme',theme);}catch{}};try{document.documentElement.dataset.theme=localStorage.getItem('unicodeguard-theme')||'dark';}catch{}
async function init(){try{await api('/api/health');$('connection').innerHTML='<i></i><span>Python engine connected</span>';}catch{$('connection').classList.add('offline');$('connection').innerHTML='<i></i><span>Engine disconnected</span>';}await loadReference();resetSample();}init();
