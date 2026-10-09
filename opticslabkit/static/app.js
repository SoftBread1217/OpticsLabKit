"use strict";
const $ = id => document.getElementById(id);
const colors = ["#176b82", "#d78736", "#735ab8", "#3d8b63", "#c3536b", "#556878"];
const CLIENT_VERSION = "0.3.0";
let datasets = [], curves = [], analysis = {pairs: [], statistics: [], warnings: []};
let busy = false, dirty = true, compatible = true, revision = 0, timer, controlSignature = "";
const curveOptions = new Map();
let extraViews = [];
const fmt = n => Number(n).toLocaleString("en-US", {maximumSignificantDigits: 6});
const element = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
};
function status(message, kind = "") { $("status").textContent = message; $("status").className = kind; }
function buttons() {
  for (const id of ["files", "demo", "demoEmpty", "repeatDemo", "scanDemo", "loadSession"]) $(id).disabled = busy || !compatible;
  $("apply").disabled = busy || !compatible || !datasets.length;
  for (const id of ["export", "saveSession"]) $(id).disabled = busy || !compatible || dirty || !curves.length;
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
const keyFor = (id, y, view = "base") => JSON.stringify([id, y, view]);
const optionsFor = spec => curveOptions.get(keyFor(spec.id, spec.y, spec.view));
function selectedCurves() {
  let index = 0;
  const primary = datasets.flatMap(data => data.ys.map(y => {
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
    return {id: data.id, x: data.x, y, view: "base", ...options};
  }));
  extraViews = extraViews.filter(view => datasets.some(data => data.id === view.id && data.ys.includes(view.y)));
  return [...primary, ...extraViews.map(view => {
    const data = datasets.find(d => d.id === view.id);
    const {branches, ...options} = optionsFor(view);
    return {...view, x: data.x, ...options};
  })];
}
function invalidate() { revision++; clearTimeout(timer); dirty = true; $("downloadReady").hidden = true; buttons(); }
function clearOptionsFor(id) {
  for (const key of curveOptions.keys()) if (JSON.parse(key)[0] === id) curveOptions.delete(key);
  extraViews = extraViews.filter(view => view.id !== id);
}
async function removeDataset(data) {
  if (busy || !compatible) return;
  invalidate(); toggleBusy(true);
  try {
    await request("/api/forget", {ids: [data.id]});
    datasets = datasets.filter(d => d.id !== data.id); clearOptionsFor(data.id);
    renderDatasets(); toggleBusy(false); await analyze();
  } catch (error) { status(error.message, "error"); }
  finally { toggleBusy(false); }
}
async function reread(data, settings, path = "/api/reparse") {
  if (busy || !compatible) return;
  invalidate(); toggleBusy(true);
  try {
    const replacement = await request(path, {id: data.id, ...(path === "/api/sheet" ? settings : {settings})});
    replacement.x = replacement.columns.includes(data.x) ? data.x : replacement.numeric_columns[0];
    replacement.ys = data.ys.filter(y => replacement.columns.includes(y) && y !== replacement.x);
    if (!replacement.ys.length) replacement.ys = replacement.numeric_columns.filter(y => y !== replacement.x).slice(0, 1);
    datasets[datasets.indexOf(data)] = replacement; clearOptionsFor(data.id);
    renderDatasets(); toggleBusy(false); await analyze();
    if (!dirty) status("已按新设置重读。分组、图例、样式、分支与独立处理已重置，请检查预览；原文件未修改。");
  } catch (error) { renderDatasets(); status(`读取设置未应用，旧数据仍保留：${error.message}`, "error"); }
  finally { toggleBusy(false); }
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
  if (busy || !compatible || !files.length) return;
  invalidate(); toggleBusy(true);
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
  if (busy || !compatible) return;
  invalidate(); toggleBusy(true); status("正在载入合成示例…", "busy");
  try {
    const result = await request(kind === "pair" ? "/api/demo" : `/api/demo-${kind}`, {replace_ids: datasets.map(d => d.id)});
    datasets = []; curveOptions.clear(); extraViews = [];
    for (const data of result.datasets || [result]) addDataset(data);
    $("title").value = kind === "repeats" ? "Synthetic repeats: mean and SD" : kind === "scan" ? "Synthetic forward / return scan" : "Synthetic TE / TM comparison";
    $("yLabel").value = "Response (a.u.)";
    $("normalization").value = "none"; $("baseline").value = "none"; $("smoothing").value = "1";
    $("raw").checked = false; $("repeats").checked = $("unitsConfirmed").checked = kind === "repeats";
    for (const id of ["xMin", "xMax", "yMin", "yMax"]) $(id).value = "";
    $("xScale").value = $("yScale").value = "linear"; smoothLabel();
    for (const [index, spec] of selectedCurves().entries()) {
      const options = optionsFor(spec);
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
    remove.disabled = busy; remove.onclick = () => removeDataset(data);
    heading.append(name, remove); card.append(heading);
    if (data.sheets.length) {
      const sheetLabel = element("label", "Excel 工作表");
      sheetLabel.append(selectControl(data.sheets, data.source.sheet, sheet => reread(data, {sheet}, "/api/sheet"))); card.append(sheetLabel);
    }
    const xLabel = element("label", "X 数据列");
    xLabel.append(selectControl(data.columns, data.x, value => {
      data.x = value; data.ys = data.ys.filter(y => y !== value);
      for (const [key, options] of curveOptions) if (JSON.parse(key)[0] === data.id) {options.branch = "all"; options.branches = [];}
      renderDatasets(); queueAnalyze();
    })); card.append(xLabel, element("label", "Y 数据列（可多选）"));
    const choices = element("div", undefined, "y-options");
    for (const column of data.columns.filter(c => c !== data.x)) {
      const label = element("label", undefined, "check"), box = element("input");
      box.type = "checkbox"; box.checked = data.ys.includes(column);
      box.onchange = () => { data.ys = box.checked ? [...data.ys, column] : data.ys.filter(y => y !== column); queueAnalyze(); };
      label.append(box, document.createTextNode(column)); choices.append(label);
    }
    const reparse = element("button", "按上方读取设置重新读取", "secondary compact");
    reparse.disabled = busy; reparse.onclick = () => reread(data, parsing());
    card.append(choices, element("p", `读取记录：跳过 ${data.source.skip_rows} 行 · ${data.source.header_detected ? "有表头" : "无表头"} · ${data.source.encoding || "Excel"}`, "hint"), reparse);
    $("datasets").append(card);
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
  invalidate(); timer = setTimeout(analyze, 300);
}
async function analyze() {
  clearTimeout(timer);
  const ticket = ++revision; dirty = true; buttons();
  try {
    const data = payload();
    renderCurveControls();
    if (!data.curves.length) { clearResults(); status("请选择 X 列和至少一条 Y 曲线。"); return; }
    if (data.curves.some(spec => !optionsFor(spec).branches.length)) {
      const catalog = await request("/api/branches", {curves: data.curves});
      if (ticket !== revision) return;
      catalog.branches.forEach((branches, i) => {optionsFor(data.curves[i]).branches = branches;});
      renderCurveControls();
    }
    status("正在按导出图样更新预览…", "busy");
    const result = await request("/api/analyze", data);
    if (ticket !== revision) return;
    curves = result.curves; analysis = result.analysis;
    result.curves.forEach((curve, i) => { optionsFor(data.curves[i]).branches = curve.branches; });
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
  const specs = selectedCurves(), signature = JSON.stringify(specs.map(s => [s.id, s.y, s.view, optionsFor(s).branches, optionsFor(s).processing !== undefined]));
  if (signature === controlSignature) return;
  controlSignature = signature; $("curveControls").replaceChildren();
  specs.forEach((spec, index) => {
    const options = optionsFor(spec), card = element("details", undefined, "curve-card");
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
    const independent = element("input"); independent.type = "checkbox"; independent.checked = !!options.processing;
    independent.onchange = () => {
      if (independent.checked) options.processing = {normalization: $("normalization").value, baseline: $("baseline").value, smoothing: Number($("smoothing").value)};
      else delete options.processing;
      controlSignature = ""; renderCurveControls(); queueAnalyze();
    };
    const own = element("label", undefined, "check"); independent.setAttribute("aria-label", `独立处理 ${index+1}`); own.append(independent, document.createTextNode("此曲线独立处理（不跟随左侧共享设置）"));
    card.append(fields, own);
    if (options.processing) {
      const ownFields = element("div", undefined, "grid2");
      function ownField(name, key, choices) {
        const label = element("label", name), input = selectControl(choices, String(options.processing[key]), value => {
          options.processing[key] = key === "smoothing" ? Number(value) : value;
          if (key === "normalization" && value !== "none") { $("raw").checked = false; $("scaleNote").textContent = "已关闭原始叠加；请核对独立处理后的曲线尺度与轴单位。"; }
          queueAnalyze();
        });
        input.setAttribute("aria-label", `${name} ${index+1}`); label.append(input); ownFields.append(label);
      }
      ownField("独立归一化", "normalization", [["none", "不归一化"], ["minmax", "Min-Max"], ["maxabs", "最大绝对值"]]);
      ownField("独立基线", "baseline", [["none", "不扣除"], ["minimum", "最小值"], ["edge_linear", "两端点线性"]]);
      const windows = [...new Set([1,3,5,7,9,11,15,21,31,options.processing.smoothing])].sort((a,b) => a-b).map(n => [String(n), `${n} 点`]);
      ownField("独立平滑", "smoothing", windows); card.append(ownFields);
    } else card.append(element("p", "跟随左侧共享处理。独立设置只改变此视图，原始文件不变。", "hint"));
    const actions = element("div", undefined, "curve-actions");
    const copy = element("button", "复制为另一个分支 / 处理对照", "secondary compact"); copy.disabled = specs.length >= 12;
    copy.onclick = () => {
      if (selectedCurves().length >= 12) { status("最多比较 12 个曲线视图。", "error"); return; }
      const view = crypto.randomUUID(), clone = JSON.parse(JSON.stringify(options));
      clone.label = `${options.label.slice(0, 180)} (copy)`; clone.style.line = "--";
      extraViews.push({id: spec.id, y: spec.y, view}); curveOptions.set(keyFor(spec.id, spec.y, view), clone);
      controlSignature = ""; renderCurveControls(); queueAnalyze();
    };
    actions.append(copy);
    if (spec.view !== "base") {
      const remove = element("button", "移除此对照视图", "secondary compact");
      remove.onclick = () => { extraViews = extraViews.filter(v => v.view !== spec.view); curveOptions.delete(keyFor(spec.id, spec.y, spec.view)); controlSignature = ""; renderCurveControls(); queueAnalyze(); };
      actions.append(remove);
    }
    card.append(actions); $("curveControls").append(card);
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
  $("summary").append(table(["曲线", "处理", "有效点", "排除行", "Y 范围", "采样最大值 X"], curves.map(c => [c.label, `${c.processing_scope === "independent" ? "独立" : "共享"} · ${c.settings.normalization} · ${c.settings.smoothing} 点`, c.stats.points, c.stats.dropped_rows, `${fmt(c.stats.y_min)} – ${fmt(c.stats.y_max)}`, fmt(c.stats.sample_max_x)])));
  if (analysis.pairs.length) $("opticalSummary").append(table(["实验组", "TE 条数", "TM 条数", "配对检查"], analysis.pairs.map(p => [p.group, p.te.length, p.tm.length, p.status === "paired" ? "1 对 · 请确认条件匹配" : p.te.length && p.tm.length ? "多条候选 · 需核对" : p.te.length || p.tm.length ? "单一偏振 · 未配对" : "未指定偏振"] )));
  for (const s of analysis.statistics) $("opticalSummary").append(element("p", `${s.group} / ${s.polarization}：n=${s.n}，${s.x.length} 个共同区间采样点；${s.interpolated ? "已线性插值" : "相同网格"}；样本 SD（不是 SEM）。`, "hint"));
  const warnings = [...new Set([...curves.flatMap(c => c.warnings), ...analysis.warnings])];
  if (curves.some(c => c.settings.normalization !== "none")) warnings.push("有曲线进行了归一化，仅保留形状比较；对应 SD 不能据此报告原始幅值误差或 TE/TM 比例。");
  for (const message of warnings) $("warnings").append(element("p", message, "notice"));
}
function clickDownload(url, name) {
  const link = $("downloadReady"); link.href = url; link.download = name;
  link.textContent = name.endsWith(".json") ? "点击下载已生成的会话（含原始数据）" : "点击下载已生成的结果 ZIP";
  link.hidden = false; link.click();
}
async function download(session = false) {
  if (busy || !compatible || dirty || !curves.length) return;
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
  if (!file || busy || !compatible) return;
  invalidate(); toggleBusy(true); status("正在验证和恢复会话…", "busy");
  try {
    if (file.size > 29 * 1024 * 1024) throw new Error("会话最大 29 MB");
    const result = await request("/api/session/load", {...JSON.parse(await file.text()), replace_ids: datasets.map(d => d.id)});
    datasets = result.datasets; curveOptions.clear(); extraViews = [];
    for (const spec of result.state.curves) {
      const {id, x, y, view = "base", ...options} = spec;
      if (view !== "base") extraViews.push({id, y, view});
      curveOptions.set(keyFor(id, y, view), {...options, branches: []});
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
async function checkBackend() {
  toggleBusy(true);
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("无法连接本地服务");
    const health = await response.json();
    compatible = health.version === CLIENT_VERSION;
    if (!compatible) status("页面已升级，但旧服务仍在运行。若旧页面还打开，请先在那里保存会话；再关闭旧启动窗口、重新运行 start.cmd 并刷新。未保存数据会随重启清空。", "error");
  } catch (error) { compatible = false; status(`本地服务检查失败：${error.message}。请重新启动服务并刷新。`, "error"); }
  finally { toggleBusy(false); }
}
buttons();
const backendReady = checkBackend();
