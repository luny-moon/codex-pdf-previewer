import { getDocument, GlobalWorkerOptions, TextLayer } from '/pdfjs/build/pdf.mjs';

GlobalWorkerOptions.workerSrc = '/pdfjs/build/pdf.worker.mjs';
const ui = Object.fromEntries(['page','pages','previous','next','zoom','quality','refresh','status','viewport','filename'].map(id => [id, document.getElementById(id)]));
ui.stack = document.getElementById('page-stack');
const key = 'local-pdf-preview-settings-v1';
let saved = {};
try { saved = JSON.parse(localStorage.getItem(key) || '{}'); } catch {}
ui.zoom.value = ['fit','1','1.25','1.5','2','3'].includes(saved.zoom) ? saved.zoom : '1.5';
ui.quality.value = ['1','2','3'].includes(saved.quality) ? saved.quality : '3';

let pdf = null, pages = [], pageNumber = 1, documentVersion = 0;
let wanted = [], pumpPromise = null, frame = 0, resizeTimer;
let lastDpr = window.devicePixelRatio || 1;
const cancelled = error => ['RenderingCancelledException','AbortException'].includes(error?.name);
const topOf = record => ui.stack.offsetTop + record.element.offsetTop;

function save() {
  try { localStorage.setItem(key, JSON.stringify({zoom:ui.zoom.value,quality:ui.quality.value})); } catch {}
}

function report(error) {
  if (cancelled(error)) return;
  console.error(error);
  ui.status.textContent = `预览失败：${error.message}`;
}

function clearPage(record) {
  record.canvas.width = record.canvas.height = 0;
  record.text.replaceChildren();
  record.proxy?.cleanup();
  record.proxy = null;
  record.state = 'idle';
  record.element.dataset.renderState = 'placeholder';
}

function invalidate(record) {
  record.version++;
  record.renderTask?.cancel();
  record.textTask?.cancel();
  // The active pump clears its canvas only after PDF.js has stopped drawing.
  if (record.state !== 'rendering') clearPage(record);
}

function pixels(record) {
  const viewport = record.viewport;
  const requested = Math.max(Number(ui.quality.value), window.devicePixelRatio || 1);
  const sampling = Math.min(requested, Math.sqrt(32000000 / (viewport.width * viewport.height)));
  return {sampling,width:Math.ceil(viewport.width*sampling),height:Math.ceil(viewport.height*sampling)};
}

function updateToolbar() {
  const record = pages[pageNumber-1];
  if (!record) return;
  if (document.activeElement !== ui.page) ui.page.value = pageNumber;
  ui.pages.textContent = `/ ${pages.length}`;
  ui.page.max = pages.length;
  ui.previous.disabled = pageNumber === 1;
  ui.next.disabled = pageNumber === pages.length;
  const size = pixels(record);
  const state = record.state === 'ready' ? `${size.width} × ${size.height} 像素 · ${size.sampling.toFixed(1)}倍采样` : record.state === 'error' ? '本页绘制失败，请刷新' : '正在高清绘制…';
  ui.status.textContent = `连续滚动 · 第 ${pageNumber} / ${pages.length} 页 · ${Math.round(record.zoom*100)}% · ${state}`;
}

function capturePosition() {
  if (!pages.length) return null;
  const line = Math.min(150,ui.viewport.clientHeight*.25);
  const y = ui.viewport.scrollTop + line;
  const record = pages.find(page => topOf(page)+page.viewport.height > y) || pages.at(-1);
  return {number:record.number,fraction:Math.max(0,Math.min(1,(y-topOf(record))/record.viewport.height)),line,horizontal:(ui.viewport.scrollLeft+ui.viewport.clientWidth/2)/Math.max(1,ui.viewport.scrollWidth)};
}

function layout(position) {
  const style = getComputedStyle(ui.viewport);
  const available = ui.viewport.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
  for (const record of pages) {
    invalidate(record);
    record.zoom = ui.zoom.value === 'fit' ? Math.max(.2,available/(record.base.width*96/72)) : Number(ui.zoom.value);
    record.viewport = record.base.clone({scale:record.zoom*96/72});
    record.element.style.width = record.canvas.style.width = `${record.viewport.width}px`;
    record.element.style.height = record.canvas.style.height = `${record.viewport.height}px`;
    record.element.style.setProperty('--total-scale-factor',record.viewport.scale);
    record.text.style.setProperty('--total-scale-factor',record.viewport.scale);
  }
  if (position) {
    const record = pages[Math.min(position.number,pages.length)-1];
    ui.viewport.scrollTop = Math.max(0,topOf(record)+record.viewport.height*position.fraction-position.line);
    ui.viewport.scrollLeft = Math.max(0,ui.viewport.scrollWidth*position.horizontal-ui.viewport.clientWidth/2);
  } else {
    ui.viewport.scrollTop = 0;
    ui.viewport.scrollLeft = Math.max(0,(ui.viewport.scrollWidth-ui.viewport.clientWidth)/2);
  }
  schedule();
}

function reconcile() {
  frame = 0;
  if (!pdf || !pages.length) return;
  const top = ui.viewport.scrollTop, bottom = top+ui.viewport.clientHeight;
  const line = top+Math.min(150,ui.viewport.clientHeight*.25);
  const atBottom = top>0 && bottom>=ui.viewport.scrollHeight-2;
  const current = atBottom ? pages.at(-1) : pages.find(record => topOf(record)+record.viewport.height > line) || pages.at(-1);
  pageNumber = current.number;
  const visible = pages.filter(record => topOf(record)<bottom && topOf(record)+record.viewport.height>top);
  const essential = [...new Set([current,...visible])];
  const nearby = [pages[current.number],pages[current.number-2],pages[current.number+1]].filter(Boolean);
  wanted = [...essential];
  let pixelBudget = essential.reduce((sum,record)=>{const size=pixels(record);return sum+size.width*size.height;},0);
  for (const record of nearby) {
    if (wanted.includes(record) || wanted.length>=3) continue;
    const size = pixels(record), cost = size.width*size.height;
    if (pixelBudget+cost>48000000) continue;
    wanted.push(record);
    pixelBudget += cost;
  }
  for (const record of pages) {
    if (!wanted.includes(record) && ['ready','rendering','error'].includes(record.state)) invalidate(record);
  }
  updateToolbar();
  startPump();
}

function schedule() {
  if (!frame) frame = requestAnimationFrame(reconcile);
}

function startPump() {
  if (pumpPromise || !pdf) return;
  pumpPromise = renderNearby().catch(report).finally(()=>{
    pumpPromise = null;
    if (pdf && wanted.some(record=>record.state==='idle')) schedule();
  });
}

async function renderNearby() {
  for (;;) {
    const record = wanted.find(item=>item.state==='idle');
    if (!record || !pdf) return;
    const source = pdf, documentToken = documentVersion, token = record.version;
    const valid = () => pdf===source && documentVersion===documentToken && record.version===token && wanted.includes(record);
    record.state = 'rendering';
    record.element.dataset.renderState = 'rendering';
    try {
      record.proxy = await source.getPage(record.number);
      if (!valid()) continue;
      const viewport = record.viewport, size = pixels(record);
      record.canvas.width = size.width;
      record.canvas.height = size.height;
      record.renderTask = record.proxy.render({canvas:record.canvas,viewport,transform:[size.width/viewport.width,0,0,size.height/viewport.height,0,0]});
      await record.renderTask.promise;
      if (!valid()) continue;
      record.textTask = new TextLayer({textContentSource:record.proxy.streamTextContent(),container:record.text,viewport});
      await record.textTask.render();
      if (!valid()) continue;
      record.state = 'ready';
      record.element.dataset.renderState = 'ready';
    } catch (error) {
      if (valid() && !cancelled(error)) {
        record.state = 'error';
        record.element.dataset.renderState = 'error';
        report(error);
      }
    } finally {
      record.renderTask = record.textTask = null;
      if (!valid() || record.state==='rendering') clearPage(record);
      if (pdf===source) updateToolbar();
    }
  }
}

function makePage(number,base) {
  const element = document.createElement('section');
  element.className = 'pdf-page';
  element.dataset.page = number;
  element.dataset.renderState = 'placeholder';
  element.setAttribute('aria-label',`第 ${number} 页`);
  element.setAttribute('role','group');
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 0;
  canvas.setAttribute('aria-label',`第 ${number} 页内容`);
  const text = document.createElement('div');
  text.className = 'textLayer';
  const placeholder = document.createElement('span');
  placeholder.className = 'page-placeholder';
  placeholder.textContent = `第 ${number} 页`;
  placeholder.setAttribute('aria-hidden','true');
  element.append(canvas,text,placeholder);
  return {number,base,element,canvas,text,state:'idle',version:0,renderTask:null,textTask:null,proxy:null};
}

async function load() {
  const previousNumber = pageNumber;
  ui.refresh.disabled = true;
  ui.status.textContent = '正在准备连续页面…';
  const old = pdf;
  pdf = null;
  documentVersion++;
  wanted = [];
  for (const record of pages) invalidate(record);
  if (pumpPromise) await pumpPromise;
  if (old) await old.destroy();
  pages = [];
  ui.stack.replaceChildren();
  try {
    const meta = await fetch('/meta.json').then(response=>response.json());
    ui.filename.textContent = meta.name;
    const source = await getDocument({url:`/document.pdf?t=${Date.now()}`,isEvalSupported:false,cMapUrl:'/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/pdfjs/standard_fonts/',wasmUrl:'/pdfjs/wasm/'}).promise;
    for (let number=1;number<=source.numPages;number++) {
      const page = await source.getPage(number);
      const record = makePage(number,page.getViewport({scale:1}));
      pages.push(record);
      ui.stack.append(record.element);
    }
    pdf = source;
    pageNumber = Math.max(1,Math.min(previousNumber,pages.length));
    document.title = `${meta.name} · Codex PDF Previewer`;
    layout(null);
    if (pageNumber>1) go(pageNumber);
  } finally {
    ui.refresh.disabled = false;
  }
}

function go(number) {
  if (!pdf) return;
  pageNumber = Math.max(1,Math.min(pages.length,Math.floor(Number(number)||1)));
  ui.page.value = pageNumber;
  ui.viewport.scrollTop = topOf(pages[pageNumber-1]);
  schedule();
}

ui.viewport.addEventListener('scroll',schedule,{passive:true});
ui.previous.addEventListener('click',()=>go(pageNumber-1));
ui.next.addEventListener('click',()=>go(pageNumber+1));
ui.page.addEventListener('change',()=>go(ui.page.value));
ui.page.addEventListener('keydown',event=>{if(event.key==='Enter')go(ui.page.value);});
ui.page.addEventListener('blur',updateToolbar);
ui.zoom.addEventListener('change',()=>{save();if(pdf)layout(capturePosition());});
ui.quality.addEventListener('change',()=>{save();for(const record of pages)invalidate(record);schedule();});
ui.refresh.addEventListener('click',()=>load().catch(report));
window.addEventListener('resize',()=>{
  clearTimeout(resizeTimer);
  resizeTimer=setTimeout(()=>{
    if (!pdf) return;
    const dpr = window.devicePixelRatio || 1;
    if (ui.zoom.value==='fit') layout(capturePosition());
    else if (dpr!==lastDpr) {for(const record of pages)invalidate(record);schedule();}
    else schedule();
    lastDpr = dpr;
  },150);
});
document.addEventListener('keydown',event=>{
  if (event.target.matches('input,select') || event.ctrlKey || event.metaKey || event.altKey) return;
  if(event.key==='ArrowRight'){event.preventDefault();go(pageNumber+1);}
  if(event.key==='ArrowLeft'){event.preventDefault();go(pageNumber-1);}
});
load().catch(report);
