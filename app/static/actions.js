const swath={running:false,identity:JSON.parse(document.getElementById('identity').textContent)};
const log=document.getElementById('log');
async function command(path,data){
  if(swath.running)return;
  swath.running=true;
  log.textContent='$ running…';
  document.querySelectorAll('button').forEach(el=>el.disabled=true);
  try{
    const args={method:'POST',body:data};
    if(!(data instanceof FormData)){args.headers={'Content-Type':'application/json'};args.body=JSON.stringify(data)}
    const r=await fetch(path,args);
    const v=await r.json();
    if(!r.ok)throw new Error(v.message);
    if(v.warning){log.textContent='$ warning / '+v.warning;location.reload();return}
    if(v.manifest){location.href=location.pathname+'?run_id='+encodeURIComponent(v.manifest.run_id);return}
    location.reload();
  }catch(e){log.textContent='$ error / '+e.message}
  finally{swath.running=false;document.querySelectorAll('button').forEach(el=>el.disabled=false)}
}
document.getElementById('rerun').addEventListener('click',()=>command('/api/run',{}));
document.getElementById('calculate').addEventListener('click',()=>command('/api/run',{csv:document.getElementById('catalogue').value}));
document.getElementById('attach').addEventListener('click',()=>{const file=document.getElementById('scene-file').files[0];if(!file){log.textContent='选择目录文件后上传。';return}const form=new FormData();form.append('file',file);command('/api/run',form)});
for(const button of document.querySelectorAll('[data-status]'))button.addEventListener('click',()=>command('/api/review',{...swath.identity,decision:button.dataset.status}));
const printout=document.getElementById('printout');if(printout)printout.addEventListener('click',()=>print());
const commit=document.getElementById('commit-plan');if(commit)commit.addEventListener('click',()=>command('/api/commit',{run_id:swath.identity.id}));
const switcher=document.getElementById('catalogue-switch');
if(switcher)switcher.addEventListener('change',()=>command('/api/catalogues/switch',{id:switcher.value}));
const ledgerLog=document.getElementById('ledger-log');
async function importLedger(path){
  const csv=document.getElementById('ledger-csv').value;
  try{
    const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csv})});
    const v=await r.json();
    if(!r.ok)throw new Error(v.message);
    location.reload();
  }catch(e){ledgerLog.textContent='$ error / '+e.message}
}
const importContracts=document.getElementById('import-contracts');
if(importContracts)importContracts.addEventListener('click',()=>importLedger('/api/contracts/import'));
const importPayments=document.getElementById('import-payments');
if(importPayments)importPayments.addEventListener('click',()=>importLedger('/api/payments/import'));
