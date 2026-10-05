"use strict";
const $ = id => document.getElementById(id);
const colors = ["#176b82", "#d78736", "#735ab8", "#3d8b63", "#c3536b", "#556878"];
let datasets = [], curves = [], analysis = {pairs: [], statistics: [], warnings: []};
let busy = false, dirty = true, revision = 0, timer, controlSignature = "";
const curveOptions = new Map();
const fmt = n => Number(n).toLocaleString("en-US", {maximumSignificantDigits: 6});
const element = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
};
function status(message, kind = "") { $("status").textContent = message; $("status").className = kind; }
function buttons() {
  for (const id of ["files", "demo", "demoEmpty", "repeatDemo", "scanDemo", "loadSession"]) $(id).disabled = busy;
  $("apply").disabled = busy || !datasets.length;
  for (const id of ["export", "saveSession"]) $(id).disabled = busy || dirty || !curves.length;
}
function toggleBusy(value) { busy = value; buttons(); }
async function request(path, data) {
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
  if (!response.ok) { const err = await response.json(); throw new Error(err.error || "操作失败"); }
  return response.json();
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
const keyFor = (id, y) => JSON.stringify([id, y]);
function selectedCurves() {
  let index = 0;
  return datasets.flatMap(data => data.ys.map(y => {
    const key = keyFor(data.id, y);
    if (!curveOptions.has(key)) {
      let polarization = "unknown";
      for (const text of [y, data.source.sheet || "", data.name]) {
        const tokens = text.match(/(?<![a-zA-Z0-9])(TE|TM)(?![a-zA-Z0-9])/gi) || [];
        const pol = [...new Set(tokens.map(s => s.toUpperCase()))];
        if (pol.length) { polarization = pol.length === 1 ? pol[0] : "unknown"; break; }
      }
      curveOptions.set(key, {label: `${data.name.replace(/\.[^.]+$/, "")} / ${y}`, group: "",
        polarization, branch: "all",
        style: {color: colors[index % colors.length], line: "-", marker: "none"}, branches: []});
    }
    index++;
    const {branches, ...options} = curveOptions.get(key);
    return {id: data.id, x: data.x, y, ...options};
  }));
}
function addDataset(data, file = null) {
  data.x = data.x || data.numeric_columns[0] || data.columns[0];
  data.ys = data.ys || data.numeric_columns.slice(1, file ? 2 : 3);
  datasets.push(data);
  if (datasets.length === 1) {
    $("xLabel").value = data.x;
    $("yLabel").value = data.ys.length === 1 ? data.ys[0] : "Response";
  }
}
async function importFiles(files) {
  if (busy || !files.length) return;
  toggleBusy(true); $("downloadReady").hidden = true;
  const errors = [];
  for (const file of [...files]) {
    try {
      if (file.size > 20 * 1024 * 1024) throw new Error("单个文件最大 20 MB");
      status(`正在读取 ${file.name}…`, "busy");
      addDataset(await request("/api/import", {name: file.name, data: await fileBase64(file), settings: parsing()}), file);
    } catch (error) { errors.push(`${file.name}：${error.message}`); }
  }
  toggleBusy(false); renderDatasets(); await analyze();
  if (errors.length) status(errors.join("；"), "error");
  $("files").value = "";
}
async function demo(kind = "pair") {
  if (busy) return;
  toggleBusy(true); $("downloadReady").hidden = true; status("正在载入合成示例…", "busy");
  try {
    const result = await request(kind === "pair" ? "/api/demo" : `/api/demo-${kind}`, {});
    datasets = []; curveOptions.clear();
    for (const data of result.datasets || [result]) addDataset(data);
    $("title").value = kind === "repeats" ? "Synthetic repeats: mean and SD" : kind === "scan" ? "Synthetic forward / return scan" : "Synthetic TE / TM comparison";
    $("yLabel").value = "Response (a.u.)";
    $("normalization").value = "none"; $("baseline").value = "none"; $("smoothing").value = "1";
    $("raw").checked = false; $("repeats").checked = $("unitsConfirmed").checked = kind === "repeats";
    for (const id of ["xMin", "xMax", "yMin", "yMax"]) $(id).value = "";
    $("xScale").value = $("yScale").value = "linear"; smoothLabel();
    for (const [index, spec] of selectedCurves().entries()) {
      const options = curveOptions.get(keyFor(spec.id, spec.y));
      options.group = kind === "pair" ? "Demo pair" : kind === "repeats" ? "Demo repeats" : "";
      if (kind === "repeats") options.polarization = "TE";
      options.label = kind === "pair" ? spec.y.replace(/ \(.*$/, "") : kind === "repeats" ? `Run ${index+1}` : "Forward / return";
    }
    controlSignature = ""; renderDatasets(); toggleBusy(false); await analyze();
    if (!dirty) status("已载入合成示例（不是论文测量数据）。可调整图样、扫描分支，或下载结果包。");
  } catch (error) { status(error.message, "error"); toggleBusy(false); }
}
function selectControl(values, current, onChange) {
  const select = element("select");
  for (const entry of values) {
    const [value, text] = Array.isArray(entry) ? entry : [entry, entry];
    const option = element("option", text); option.value = value; select.append(option);
  }
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
    remove.onclick = () => { datasets = datasets.filter(d => d !== data); renderDatasets(); queueAnalyze(); };
    heading.append(name, remove); card.append(heading);
    if (data.sheets.length) {
      const sheetLabel = element("label", "Excel 工作表");
      sheetLabel.append(selectControl(data.sheets, data.source.sheet, async sheet => {
        if (busy) return;
        toggleBusy(true);
        try {
          const replacement = await request("/api/sheet", {id: data.id, sheet});
          replacement.x = replacement.numeric_columns[0] || replacement.columns[0];
          replacement.ys = replacement.numeric_columns.slice(1, 2);
          datasets[datasets.indexOf(data)] = replacement; renderDatasets(); toggleBusy(false); await analyze();
        } catch (error) { status(error.message, "error"); renderDatasets(); toggleBusy(false); }
      })); card.append(sheetLabel);
    }
    const xLabel = element("label", "X 数据列");
    xLabel.append(selectControl(data.columns, data.x, value => {
      data.x = value; data.ys = data.ys.filter(y => y !== value);
      for (const y of data.ys) { const options = curveOptions.get(keyFor(data.id, y)); if (options) {options.branch = "all"; options.branches = [];} }
      renderDatasets(); queueAnalyze();
    })); card.append(xLabel, element("label", "Y 数据列（可多选）"));
    const choices = element("div", undefined, "y-options");
    for (const column of data.columns.filter(c => c !== data.x)) {
      const label = element("label", undefined, "check"), box = element("input");
      box.type = "checkbox"; box.checked = data.ys.includes(column);
      box.onchange = () => { data.ys = box.checked ? [...data.ys, column] : data.ys.filter(y => y !== column); queueAnalyze(); };
      label.append(box, document.createTextNode(column)); choices.append(label);
    }
    card.append(choices); $("datasets").append(card);
  }
  renderPreview(); buttons();
}
const figureMap = {title: "title", x_label: "xLabel", y_label: "yLabel", width_mm: "widthMm", height_mm: "heightMm", font: "font", font_size: "fontSize", tick_size: "tickSize", line_width: "lineWidth", legend_size: "legendSize", legend: "legendPos", dpi: "dpi", x_scale: "xScale", y_scale: "yScale", show_raw: "raw", box: "box", grid: "grid", minor_ticks: "minorTicks"};
function limits(axis) {
  const low = $(`${axis}Min`).value, high = $(`${axis}Max`).value;
  if (!low && !high) return null;
  if (!low || !high) throw new Error(`${axis.toUpperCase()} 轴范围需上下限都填写，或两格都留空。`);
  return [Number(low), Number(high)];
}
function payload() {
  const figure = {};
  for (const [key, id] of Object.entries(figureMap)) {
    const input = $(id);
    figure[key] = input.type === "checkbox" ? input.checked : input.type === "number" || id === "dpi" ? Number(input.value) : input.value;
  }
  figure.x_limits = limits("x"); figure.y_limits = limits("y");
  return {curves: selectedCurves(), datasets: datasets.map(d => ({id: d.id, x: d.x, ys: d.ys})),
    processing: {normalization: $("normalization").value, baseline: $("baseline").value, smoothing: Number($("smoothing").value)},
    analysis: {repeats: $("repeats").checked, units_confirmed: $("unitsConfirmed").checked}, figure};
}
function queueAnalyze() {
  dirty = true; revision++; $("downloadReady").hidden = true;
  buttons(); clearTimeout(timer); timer = setTimeout(analyze, 300);
}
async function analyze() {
  clearTimeout(timer);
  const ticket = ++revision; dirty = true; buttons();
  try {
    const data = payload();
    renderCurveControls();
    if (!data.curves.length) { clearResults(); status("请选择 X 列和至少一条 Y 曲线。"); return; }
    status("正在按导出图样更新预览…", "busy");
    const result = await request("/api/analyze", data);
    if (ticket !== revision) return;
    curves = result.curves; analysis = result.analysis;
    result.curves.forEach((curve, i) => { curveOptions.get(keyFor(data.curves[i].id, data.curves[i].y)).branches = curve.branches; });
    $("chart").src = result.preview_url; $("chart").hidden = false; $("plotEmpty").hidden = true;
    $("plotTitle").textContent = data.figure.title || "曲线预览";
    $("pointCount").textContent = `${curves.length} 条 · ${curves.reduce((a,c) => a+c.stats.points,0).toLocaleString()} 点`;
    $("hover").textContent = `${data.figure.width_mm} × ${data.figure.height_mm} mm · ${data.figure.dpi} dpi PNG · SVG / PDF 矢量导出`;
    renderCurveControls(); renderSummary(); dirty = false; buttons();
    status(`已处理 ${curves.length} 条曲线；预览与导出一致。`);
  } catch (error) { if (ticket === revision) { clearResults(); status(error.message, "error"); } }
}
function clearResults() {
  curves = []; analysis = {pairs: [], statistics: [], warnings: []};
  $("chart").hidden = true; $("chart").removeAttribute("src"); $("plotEmpty").hidden = false;
  $("pointCount").textContent = "等待有效结果"; renderSummary(); buttons();
}
function renderCurveControls() {
  const specs = selectedCurves(), signature = JSON.stringify(specs.map(s => [s.id, s.y, curveOptions.get(keyFor(s.id, s.y)).branches]));
  if (signature === controlSignature) return;
  controlSignature = signature; $("curveControls").replaceChildren();
  specs.forEach((spec, index) => {
    const options = curveOptions.get(keyFor(spec.id, spec.y)), card = element("details", undefined, "curve-card");
    card.open = specs.length <= 2;
    card.append(element("summary", `${index+1}. ${spec.label}`));
    const fields = element("div", undefined, "curve-fields");
    function field(text, input) { const label = element("label", text); input.setAttribute("aria-label", `${text} ${index+1}`); label.append(input); fields.append(label); }
    function textField(text, key, max) {
      const input = element("input"); input.value = options[key]; input.maxLength = max;
      input.oninput = () => { options[key] = input.value; if (key === "label") card.querySelector("summary").textContent = `${index+1}. ${input.value}`; queueAnalyze(); };
      field(text, input);
    }
    textField("图例名称", "label", 200); textField("实验条件 / 组名", "group", 100);
    field("偏振", selectControl([["unknown", "未指定"], ["TE", "TE"], ["TM", "TM"]], options.polarization, value => {options.polarization = value; queueAnalyze();}));
    const branches = [["all", "全部采集点"], ...options.branches.map(b => [b.id, `分支 ${Number(b.id)+1} ${b.direction === "up" ? "↑" : b.direction === "down" ? "↓" : "—"} · ${b.stop-b.start} 点`])];
    field("扫描分支", selectControl(branches, options.branch, value => {options.branch = value; queueAnalyze();}));
    const color = element("input"); color.type = "color"; color.value = options.style.color;
    color.oninput = () => {options.style.color = color.value; queueAnalyze();}; field("颜色", color);
    field("线型", selectControl([["-", "实线"], ["--", "虚线"], ["-.", "点划线"], [":", "点线"]], options.style.line, value => {options.style.line = value; queueAnalyze();}));
    field("采样点标记", selectControl([["none", "不显示"], ["o", "圆"], ["s", "方"], ["^", "三角"], ["D", "菱形"]], options.style.marker, value => {options.style.marker = value; queueAnalyze();}));
    card.append(fields); $("curveControls").append(card);
  });
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
  for (const data of datasets) $("preview").append(element("p", `${data.name} · 前 8 行`, "hint"), table(data.columns, data.preview));
}
function renderSummary() {
  $("summary").replaceChildren(); $("warnings").replaceChildren(); $("opticalSummary").replaceChildren();
  if (!curves.length) { $("summary").append(element("p", "处理结果将在这里显示。", "empty-note")); return; }
  $("summary").append(table(["曲线", "有效点", "排除行", "Y 范围", "采样最大值 X"], curves.map(c => [c.label, c.stats.points, c.stats.dropped_rows, `${fmt(c.stats.y_min)} – ${fmt(c.stats.y_max)}`, fmt(c.stats.sample_max_x)])));
  if (analysis.pairs.length) $("opticalSummary").append(table(["实验组", "TE 条数", "TM 条数", "配对检查"], analysis.pairs.map(p => [p.group, p.te.length, p.tm.length, p.status === "paired" ? "1 对 · 请确认条件匹配" : p.te.length && p.tm.length ? "多条候选 · 需核对" : p.te.length || p.tm.length ? "单一偏振 · 未配对" : "未指定偏振"] )));
  for (const s of analysis.statistics) $("opticalSummary").append(element("p", `${s.group} / ${s.polarization}：n=${s.n}，${s.x.length} 个共同区间采样点；${s.interpolated ? "已线性插值" : "相同网格"}；样本 SD（不是 SEM）。`, "hint"));
  const warnings = [...new Set([...curves.flatMap(c => c.warnings), ...analysis.warnings])];
  if ($("normalization").value !== "none") warnings.push("每条曲线独立归一化，仅保留形状比较；重复测量 SD 也在归一化尺度上，不能据此报告绝对幅值误差或 TE/TM 比例。");
  for (const message of warnings) $("warnings").append(element("p", message, "notice"));
}
function clickDownload(url, name) {
  const link = $("downloadReady"); link.href = url; link.download = name;
  link.textContent = name.endsWith(".json") ? "点击下载已生成的会话（含原始数据）" : "点击下载已生成的结果 ZIP";
  link.hidden = false; link.click();
}
async function download(session = false) {
  if (busy || dirty || !curves.length) return;
  toggleBusy(true); $("downloadReady").hidden = true;
  status(session ? "正在保存会话（包含原始数据）…" : "正在生成科研图、Origin 表和重画脚本…", "busy");
  try {
    const result = await request(session ? "/api/session/save" : "/api/prepare-export", payload());
    clickDownload(result.download_url, session ? "comparison.olksession.json" : "opticslabkit-results.zip");
    status(session ? "会话已生成。下次点“打开会话”恢复；分享前检查其中的原始数据。" : "结果包已生成。解压后可用 origin_xy.csv 在 Origin 重画，用 SVG/PDF 精修排版。");
  } catch(error) { status(error.message, "error"); }
  finally { toggleBusy(false); }
}
async function openSession(file) {
  if (!file || busy) return;
  toggleBusy(true); $("downloadReady").hidden = true; status("正在验证和恢复会话…", "busy");
  try {
    if (file.size > 29 * 1024 * 1024) throw new Error("会话最大 29 MB");
    const result = await request("/api/session/load", JSON.parse(await file.text()));
    datasets = result.datasets; curveOptions.clear();
    for (const spec of result.state.curves) {
      const {id, x, y, ...options} = spec;
      curveOptions.set(keyFor(id, y), {...options, branches: []});
    }
    const state = result.state;
    for (const [key, id] of Object.entries(figureMap)) {
      const value = state.figure[key];
      if (value !== undefined) { if ($(id).type === "checkbox") $(id).checked = value; else $(id).value = value; }
    }
    for (const axis of ["x", "y"]) {
      const values = state.figure[`${axis}_limits`] || ["", ""];
      $(`${axis}Min`).value = values[0]; $(`${axis}Max`).value = values[1];
    }
    for (const id of ["normalization", "baseline", "smoothing"]) $(id).value = state.processing[id];
    $("repeats").checked = !!state.analysis.repeats; $("unitsConfirmed").checked = !!state.analysis.units_confirmed;
    $("preset").value = "custom"; controlSignature = ""; smoothLabel(); renderDatasets(); toggleBusy(false); await analyze();
    if (!dirty) status("已恢复原始数据、选列、分组、处理参数和图样。");
  } catch(error) { status(`会话未恢复：${error.message}`, "error"); }
  finally { $("loadSession").value = ""; toggleBusy(false); }
}
$("files").addEventListener("change", e => importFiles(e.target.files));
for (const event of ["dragenter", "dragover"]) $("drop").addEventListener(event, e => {e.preventDefault(); $("drop").classList.add("over");});
$("drop").addEventListener("dragleave", () => $("drop").classList.remove("over"));
$("drop").addEventListener("drop", e => {e.preventDefault(); $("drop").classList.remove("over"); importFiles(e.dataTransfer.files);});
$("demo").onclick = () => demo(); $("demoEmpty").onclick = () => demo();
$("repeatDemo").onclick = () => demo("repeats"); $("scanDemo").onclick = () => demo("scan");
$("apply").onclick = analyze; $("export").onclick = () => download(); $("saveSession").onclick = () => download(true);
$("loadSession").onchange = e => openSession(e.target.files[0]);
for (const id of ["baseline", "smoothing", "normalization"]) $(id).addEventListener("input", () => {
  smoothLabel();
  if (id === "normalization") {
    $("raw").checked = false;
    $("yLabel").value = $("normalization").value === "none" ? "Response" : "Normalized response";
    $("scaleNote").textContent = $("normalization").value === "none" ? "" : "已关闭原始叠加，避免不同尺度混在同一轴上。";
  }
  queueAnalyze();
});
for (const id of [...Object.values(figureMap), "xMin", "xMax", "yMin", "yMax", "repeats", "unitsConfirmed"]) $(id).addEventListener("input", () => {
  if (["widthMm", "heightMm"].includes(id)) $("preset").value = "custom";
  queueAnalyze();
});
$("preset").onchange = () => {
  const single = $("preset").value === "single";
  if ($("preset").value !== "custom") {
    $("widthMm").value = single ? 85 : 180; $("heightMm").value = single ? 65 : 110;
    $("fontSize").value = single ? 8 : 9; $("tickSize").value = single ? 7 : 8; $("legendSize").value = single ? 7 : 8;
    queueAnalyze();
  }
};
$("chart").onerror = () => { dirty = true; buttons(); status("预览未能加载，请点“更新曲线”重试。", "error"); };
buttons();
