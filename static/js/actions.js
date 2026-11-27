import { $, input, state, sample, toast, api, post, setBusy, updateEditorCount } from './core.js';
import { render, selectTab } from './views.js';

function invalidate() {
  state.revision++; state.analysis=null; state.cleaned=null;
  updateEditorCount(); render();
}
function resetSample() {input.value=sample;state.dirty=false;state.source='sample.txt';$('sourceName').textContent=state.source;$('documentLabel').textContent='Sample document';invalidate(); analyze();}
async function analyze() {
  const text=input.value, revision=state.revision, request=++state.request;
  if (!text) {toast('Add some text before analyzing.');return;}
  setBusy($('analyzeBtn'),true,'Analyzing…');
  try {const res=await post('/api/analyze',{text}); const data=await res.json();if(revision!==state.revision || request!==state.request){return;} state.analysis=data;state.cleaned=null;render();toast('Analysis complete. Findings are not proof of an AI watermark.');}
  catch(e){toast(e.message);} finally{setBusy($('analyzeBtn'),false);}
}
async function clean() {
  const text=input.value, revision=state.revision, request=++state.request;
  if (!text){toast('Add some text before cleaning.');return;}
  const mode=$('mode').value;
  if(mode==='aggressive'&&!confirm('Aggressive mode drops non-ASCII characters and can damage languages, emoji and code. Continue?')) return;
  const custom_exclusions=$('exclusions').value.split(',').map(x=>x.trim().toUpperCase()).filter(Boolean);
  setBusy($('cleanBtn'),true,'Cleaning…');
  try {const res=await post('/api/clean',{text,mode,custom_exclusions});const data=await res.json();if(revision!==state.revision || request!==state.request){return;} state.analysis=data.before;state.cleaned=data;render();selectTab('diff');toast(`${data.summary.changed} character changes. Please review the result before exporting.`);}
  catch(e){toast(e.message);}finally{setBusy($('cleanBtn'),false);}
}
async function upload(file){
 if(!file)return;if(state.dirty && input.value && !confirm('Replace the current text with the selected file?')){$('fileInput').value='';return;}if(file.size>10*1024*1024){toast('File exceeds 10 MB.');return;}const form=new FormData();form.append('file',file);const revision=state.revision, request=++state.request;
 try{toast('Reading document…');const res=await api('/api/upload-analyze',{method:'POST',body:form});const data=await res.json();if(revision!==state.revision || request!==state.request){return;}input.value=data.text;state.dirty=false;state.source=data.filename;$('sourceName').textContent=data.filename;$('documentLabel').textContent='Uploaded document';invalidate();state.analysis=data.analysis;render();toast(data.notice);}catch(e){toast(e.message);}finally{$('fileInput').value='';}
}
function downloadBlob(blob,name){const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function downloadFile(format){if(!state.cleaned){toast('Clean your text first, then export the reviewed result.');return;}try{const res=await post('/api/export-file',{text:state.cleaned.cleaned_text,format,filename:'unicodeguard-clean'});downloadBlob(await res.blob(),`unicodeguard-clean.${format}`);toast(`${format.toUpperCase()} downloaded.`);}catch(e){toast(e.message);}}
function exportAudit(format){if(!state.analysis){toast('Analyze text first to export the audit.');return;}let data,mime;if(format==='json'){data=JSON.stringify({analysis:state.analysis,cleaning:state.cleaned},null,2);mime='application/json';}else{const rows=[['Char','Unicode','Name / Type','Count','Positions','Clean Action'],...state.analysis.detected_characters.map(f=>[f.char,f.unicode_code,f.name_type,f.count,f.positions.join('; '),f.clean_action])];data=rows.map(r=>r.map(x=>{let v=String(x);if(/^[=+@\-\t\r]/.test(v))v="'"+v;return '"'+v.replace(/"/g,'""')+'"';}).join(',')).join('\r\n');mime='text/csv';}downloadBlob(new Blob([data],{type:mime+';charset=utf-8'}),`unicodeguard-audit.${format}`);}


export { invalidate, resetSample, analyze, clean, upload, downloadFile, exportAudit };
