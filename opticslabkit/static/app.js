"use strict";
const $ = id => document.getElementById(id);
const colors = ["#176b82", "#d78736", "#735ab8", "#3d8b63", "#c3536b", "#556878"];
let datasets = [], curves = [], plot = null, busy = false, revision = 0, timer;
const fmt = n => Number(n).toLocaleString("en-US", {maximumSignificantDigits: 6});
const element = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
};
function status(message, kind = "") { $("status").textContent = message; $("status").className = kind; }
function toggleBusy(value) {
  busy = value;
  for (const id of ["files", "demo", "demoEmpty"]) $(id).disabled = value;
  $("apply").disabled = value || !datasets.length;
  $("export").disabled = value || !curves.length;
}
async function request(path, data, binary = false) {
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
  if (!response.ok) { const err = await response.json(); throw new Error(err.error || "操作失败"); }
  return binary ? response.blob() : response.json();
}
function parsing() {
  return {skip_rows: Number($("skip").value), header: $("header").value, delimiter: $("delimiter").value, decimal: $("decimal").value};
}
function fileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]);
    reader.onerror = () => reject(new Error("无法读取文件"));
    reader.readAsDataURL(file);
  });
}
function addDataset(data, file = null) {
  const numeric = data.numeric_columns;
  data.x = numeric[0] || data.columns[0];
  data.ys = numeric.slice(1, file ? 2 : 3);
  data.file = file;
  datasets.push(data);
  if (datasets.length === 1) {
    $("xLabel").value = data.x;
    $("yLabel").value = data.ys.length === 1 ? data.ys[0] : "Response";
  }
}
async function importFiles(files) {
  if (busy) return;
  const selected = [...files];
  if (!selected.length) return;
  toggleBusy(true);
  const errors = [];
  for (const file of selected) {
    try {
      if (file.size > 20 * 1024 * 1024) throw new Error("单个文件最大 20 MB");
      status(`正在读取 ${file.name}…`, "busy");
      const data = await request("/api/import", {name: file.name, data: await fileBase64(file), settings: parsing()});
      addDataset(data, file);
    } catch (error) { errors.push(`${file.name}：${error.message}`); }
  }
  toggleBusy(false); renderDatasets(); await analyze();
  if (errors.length) status(errors.join("；"), "error");
  $("files").value = "";
}
async function demo() {
  if (busy) return;
  toggleBusy(true); status("正在载入合成示例…", "busy");
  try {
    const data = await request("/api/demo", {});
    datasets = []; addDataset(data);
    $("title").value = "Synthetic TE / TM comparison";
    $("yLabel").value = "Response (a.u.)";
    $("normalization").value = "none"; $("baseline").value = "none";
    $("smoothing").value = "1"; $("raw").checked = false; smoothLabel();
    renderDatasets(); toggleBusy(false); await analyze();
    status("已载入 TE/TM 合成示例。可调整处理设置；这不是论文测量数据。");
  } catch (error) { status(error.message, "error"); toggleBusy(false); }
}
function selectControl(values, current, onChange) {
  const select = element("select");
  for (const name of values) { const option = element("option", name); option.value = name; select.append(option); }
  select.value = current;
  select.addEventListener("change", () => onChange(select.value));
  return select;
}
function renderDatasets() {
  $("datasets").replaceChildren();
  if (!datasets.length) $("datasets").append(element("p", "尚未导入数据。", "empty-note"));
  for (const data of datasets) {
    const card = element("div", undefined, "dataset"), heading = element("div", undefined, "dataset-head");
    const name = element("div"); name.append(element("strong", data.name), element("div", `${data.rows.toLocaleString()} 行 · ${data.columns.length} 列`, "count"));
    const remove = element("button", "×", "remove"); remove.setAttribute("aria-label", `移除 ${data.name}`);
    remove.onclick = () => { datasets = datasets.filter(d => d !== data); renderDatasets(); analyze(); };
    heading.append(name, remove); card.append(heading);
    if (data.sheets.length && data.file) {
      const sheetLabel = element("label", "Excel 工作表");
      sheetLabel.append(selectControl(data.sheets, data.source.sheet, async sheet => {
        if (busy) return;
        toggleBusy(true);
        try {
          const replacement = await request("/api/import", {name: data.file.name, data: await fileBase64(data.file), settings: {...parsing(), sheet}});
          const index = datasets.indexOf(data);
          replacement.x = replacement.numeric_columns[0] || replacement.columns[0];
          replacement.ys = replacement.numeric_columns.slice(1, 2); replacement.file = data.file;
          datasets[index] = replacement; renderDatasets(); toggleBusy(false); await analyze();
        } catch (error) { status(error.message, "error"); toggleBusy(false); }
      })); card.append(sheetLabel);
    }
    const xLabel = element("label", "X 数据列");
    xLabel.append(selectControl(data.columns, data.x, value => {
      data.x = value; data.ys = data.ys.filter(y => y !== value); renderDatasets(); analyze();
    })); card.append(xLabel);
    card.append(element("label", "Y 数据列（可多选）"));
    const choices = element("div", undefined, "y-options");
    for (const column of data.columns.filter(c => c !== data.x)) {
      const label = element("label", undefined, "check"), box = element("input");
      box.type = "checkbox"; box.checked = data.ys.includes(column);
      box.onchange = () => { data.ys = box.checked ? [...data.ys, column] : data.ys.filter(y => y !== column); analyze(); };
      label.append(box, document.createTextNode(column)); choices.append(label);
    }
    card.append(choices); $("datasets").append(card);
  }
  renderPreview(); $("apply").disabled = busy || !datasets.length;
}
function payload() {
  return {curves: datasets.flatMap(data => data.ys.map(y => ({id: data.id, x: data.x, y, label: `${data.name.replace(/\.[^.]+$/, "")} / ${y}`}))),
    processing: {normalization: $("normalization").value, baseline: $("baseline").value, smoothing: Number($("smoothing").value)},
    figure: {title: $("title").value, x_label: $("xLabel").value, y_label: $("yLabel").value, show_raw: $("raw").checked}};
}
async function analyze() {
  const ticket = ++revision, data = payload();
  $("export").disabled = true;
  if (!data.curves.length) { curves = []; draw(); renderSummary(); status("请选择 X 列和至少一条 Y 曲线。"); return; }
  status("正在更新曲线…", "busy");
  try {
    const result = await request("/api/analyze", data);
    if (ticket !== revision) return;
    curves = result.curves; draw(); renderSummary(); $("export").disabled = busy;
    status(`已处理 ${curves.length} 条曲线，保留原始采集顺序。`);
  } catch (error) { if (ticket === revision) { curves = []; draw(); renderSummary(); status(error.message, "error"); } }
}
function smoothLabel() { const n = Number($("smoothing").value); $("smoothValue").textContent = n === 1 ? "1 · 不平滑" : `${n} 点`; }
function table(headers, rows) {
  const tbl = element("table"), head = element("thead"), tr = element("tr");
  for (const label of headers) tr.append(element("th", label)); head.append(tr); tbl.append(head);
  const body = element("tbody");
  for (const values of rows) { const row = element("tr"); for (const value of values) row.append(element("td", value ?? "—")); body.append(row); }
  tbl.append(body); return tbl;
}
function renderPreview() {
  $("preview").replaceChildren();
  for (const data of datasets) { $("preview").append(element("p", `${data.name} · 前 8 行`, "hint"), table(data.columns, data.preview)); }
}
function renderSummary() {
  $("summary").replaceChildren(); $("warnings").replaceChildren();
  if (!curves.length) { $("summary").append(element("p", "处理结果将在这里显示。", "empty-note")); return; }
  $("summary").append(table(["曲线", "有效点", "排除行", "Y 范围", "采样最大值 X"], curves.map(c => [c.label, c.stats.points, c.stats.dropped_rows, `${fmt(c.stats.y_min)} – ${fmt(c.stats.y_max)}`, fmt(c.stats.sample_max_x)])));
  const warnings = [...new Set(curves.flatMap(c => c.warnings))];
  if ($("normalization").value !== "none") warnings.push("每条曲线单独归一化，保留形状比较；原始 TE/TM 强度比例需用未归一化曲线判断。");
  for (const message of warnings) $("warnings").append(element("p", message, "notice"));
}
function draw() {
  const canvas = $("chart"), box = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, box.width * ratio); canvas.height = Math.max(1, box.height * ratio);
  const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio);
  const w = box.width, h = box.height;
  $("plotEmpty").style.display = curves.length ? "none" : "flex";
  $("plotTitle").textContent = $("title").value || "曲线预览";
  $("pointCount").textContent = curves.length ? `${curves.length} 条曲线 · ${curves.reduce((a,c) => a+c.stats.points,0).toLocaleString()} 点` : "等待数据";
  $("legend").replaceChildren(); plot = null;
  if (!curves.length) return;
  let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
  for (const curve of curves) {
    for (const x of curve.x) { xMin = Math.min(xMin, x); xMax = Math.max(xMax, x); }
    for (const ys of [curve.y, ...($("raw").checked ? [curve.raw_y] : [])]) {
      for (const y of ys) { yMin = Math.min(yMin, y); yMax = Math.max(yMax, y); }
    }
  }
  if (xMin === xMax) { xMin -= 0.5; xMax += 0.5; }
  const padding = (yMax-yMin || 1) * .09; yMin -= padding; yMax += padding;
  const left = 78, right = 20, top = 14, bottom = 52;
  const width = w-left-right, height = h-top-bottom;
  const sx = x => left + (x-xMin)/(xMax-xMin)*width, sy = y => top+height-(y-yMin)/(yMax-yMin)*height;
  ctx.font = "11px Segoe UI, Microsoft YaHei";
  for (let i=0;i<=5;i++) {
    const tx = xMin+(xMax-xMin)*i/5, ty = yMin+(yMax-yMin)*i/5;
    ctx.strokeStyle = "#e9eef1"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(left,sy(ty)); ctx.lineTo(w-right,sy(ty)); ctx.stroke();
    const tick = Number(ty).toLocaleString("en-US", {maximumSignificantDigits: 4});
    ctx.fillStyle = "#758694"; ctx.textAlign = "right"; ctx.fillText(tick,left-9,sy(ty)+4);
    ctx.textAlign = "center"; ctx.fillText(fmt(tx),sx(tx),h-bottom+22);
  }
  ctx.strokeStyle = "#abb9c2"; ctx.beginPath(); ctx.moveTo(left,top); ctx.lineTo(left,h-bottom); ctx.lineTo(w-right,h-bottom); ctx.stroke();
  ctx.fillStyle = "#455b6b"; ctx.textAlign = "center"; ctx.fillText($("xLabel").value,left+width/2,h-5);
  ctx.save(); ctx.translate(13,top+height/2); ctx.rotate(-Math.PI/2); ctx.fillText($("yLabel").value,0,0); ctx.restore();
  const line = (curve, values, raw, color) => {
    ctx.save(); ctx.beginPath(); ctx.rect(left,top,width,height); ctx.clip();
    ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = raw ? 1.2 : 2.2; ctx.globalAlpha = raw ? .28 : 1; ctx.setLineDash(raw ? [4,4] : []);
    for (let i=0;i<curve.x.length;i++) { const x=sx(curve.x[i]),y=sy(values[i]); if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y); }
    ctx.stroke(); ctx.restore();
  };
  curves.forEach((c,i) => {
    const color = colors[i%colors.length];
    if ($("raw").checked) line(c,c.raw_y,true,color);
    line(c,c.y,false,color);
    const item=element("span",undefined,"legend-item"), swatch=element("span",undefined,"swatch"); swatch.style.setProperty("--color",color); item.append(swatch,document.createTextNode(c.label)); $("legend").append(item);
  });
  plot = {left,width,xMin,xMax};
}
$("chart").addEventListener("mousemove", event => {
  if (!plot) return;
  const dx=event.offsetX; if (dx<plot.left || dx>plot.left+plot.width) return;
  const x=plot.xMin+(dx-plot.left)/plot.width*(plot.xMax-plot.xMin);
  const samples=curves.map(c => { let i=0; for (let j=1;j<c.x.length;j++) if (Math.abs(c.x[j]-x)<Math.abs(c.x[i]-x)) i=j; return `${c.y_column}: X=${fmt(c.x[i])}, Y=${fmt(c.y[i])}`; });
  $("hover").textContent=samples.join("　｜　");
});
async function download() {
  if (busy || !curves.length) return;
  toggleBusy(true); status("正在生成 300 dpi PNG、SVG 和处理记录…", "busy");
  try {
    const result=await request("/api/prepare-export",payload()), link=element("a");
    link.href=result.download_url; link.download="opticslabkit-results.zip";
    document.body.append(link); link.click(); link.remove();
    status("结果包已生成。manifest.json 记录源文件哈希、读取设置和处理参数。");
  } catch(error) { status(error.message,"error"); }
  finally { toggleBusy(false); }
}
$("files").addEventListener("change", e => importFiles(e.target.files));
for (const event of ["dragenter","dragover"]) $("drop").addEventListener(event,e => {e.preventDefault();$("drop").classList.add("over");});
$("drop").addEventListener("dragleave",() => $("drop").classList.remove("over"));
$("drop").addEventListener("drop",e => {e.preventDefault();$("drop").classList.remove("over");importFiles(e.dataTransfer.files);});
$("demo").onclick=demo; $("demoEmpty").onclick=demo; $("apply").onclick=analyze; $("export").onclick=download;
for (const id of ["baseline","smoothing","normalization"]) $(id).addEventListener("input",() => {
  smoothLabel();
  if (id==="normalization") {
    $("raw").checked=false;
    $("yLabel").value=$("normalization").value==="none" ? "Response" : "Normalized response";
    $("scaleNote").textContent=$("normalization").value==="none" ? "" : "已关闭原始曲线叠加，避免不同尺度混在同一坐标轴。";
  }
  $("export").disabled=true; clearTimeout(timer); timer=setTimeout(analyze,180);
});
for (const id of ["title","xLabel","yLabel","raw"]) $(id).addEventListener("input",draw);
new ResizeObserver(draw).observe($("chart"));
draw();
