const $ = (id) => document.getElementById(id);
const input = $('inputText');
const state = {analysis:null, cleaned:null, source:'sample.txt', filter:'all', chart:null, barChart:null, revision:0, request:0, dirty:false};
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

export { $, input, state, sample, toast, api, post, setBusy, updateEditorCount };
