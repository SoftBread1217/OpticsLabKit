// Client event/model integration with a mock DOM and the real loopback API.
// This is not a browser layout or native file-picker test. No lab files are loaded.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {randomUUID} = require('node:crypto');

class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attributes = {}; this.value = '';
    this.checked = false; this.disabled = false; this.type = ''; this.textContent = '';
    this.listeners = {}; this.classList = {add() {}, remove() {}};
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelector(tag) { return flatten(this).find(node => node !== this && node.tag === tag); }
  emit(name) { this.listeners[name]?.({target:this}); this[`on${name}`]?.({target:this}); }
  click() { if (!this.disabled) this.emit('click'); }
}
function flatten(node) { return [node, ...node.children.flatMap(flatten)]; }
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'opticslabkit/static/index.html'), 'utf8');
const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element('fixture')]));
const defaults = {normalization:'none', baseline:'none', smoothing:1, title:'Optical response',
  xLabel:'X', yLabel:'Y', widthMm:180, heightMm:110, font:'DejaVu Sans', fontSize:9,
  tickSize:8, lineWidth:1.5, legendSize:8, legendPos:'best', dpi:300,
  xScale:'linear', yScale:'linear', header:'auto', delimiter:'auto', decimal:'.', skip:0};
for (const [id, value] of Object.entries(defaults)) {
  assert(elements.has(id), `Missing real HTML control: ${id}`);
  elements.get(id).value = String(value);
}
for (const id of ['widthMm','heightMm','fontSize','tickSize','lineWidth','legendSize','xMin','xMax','yMin','yMax']) elements.get(id).type = 'number';
for (const id of ['raw','box','minorTicks','grid','repeats','unitsConfirmed']) elements.get(id).type = 'checkbox';
for (const id of ['raw','box','minorTicks']) elements.get(id).checked = true;
const document = {getElementById:id => elements.get(id), createElement:tag => new Element(tag),
  createTextNode:text => {const node = new Element('text'); node.textContent = text; return node;}};
const endpoint = process.argv[2];
const legacyHealth = process.argv[3] === 'legacy-health';
const context = vm.createContext({document, console, crypto:{randomUUID},
  setTimeout, clearTimeout, fetch:(url, options) => legacyHealth && url === '/api/health'
    ? Promise.resolve({ok:true, json:async () => ({ok:true, app:'OpticsLabKit'})})
    : fetch(new URL(url, endpoint), options)});
vm.runInContext(fs.readFileSync(path.join(root, 'opticslabkit/static/app.js'), 'utf8'), context);
const run = code => vm.runInContext(code, context);
const snapshot = expression => JSON.parse(run(`JSON.stringify(${expression})`));
function field(name) {
  const node = flatten(elements.get('curveControls')).find(el => el.attributes['aria-label'] === name);
  assert(node, `Missing curve control: ${name}`); return node;
}
async function update() { await run('analyze()'); assert.equal(run('dirty'), false, elements.get('status').textContent); }

async function main() {
  await run('backendReady');
  if (legacyHealth) {
    assert.equal(run('compatible'), false);
    assert.equal(elements.get('demo').disabled, true);
    assert.equal(elements.get('files').disabled, true);
    assert(elements.get('status').textContent.includes('旧服务仍在运行'));
    await run("demo('scan')");
    assert.equal(run('datasets.length'), 0);
    console.log('Legacy backend blocked with restart guidance OK'); return;
  }
  assert.equal(run('compatible'), true, elements.get('status').textContent);
  await run("demo('scan')");
  assert.equal(run('dirty'), false, elements.get('status').textContent);
  field('扫描分支 1').value = '0'; field('扫描分支 1').emit('change'); await update();
  const copy = flatten(elements.get('curveControls')).find(el => el.tag === 'button' && el.textContent.startsWith('复制'));
  copy.click(); await update();
  field('扫描分支 2').value = '1'; field('扫描分支 2').emit('change'); await update();
  assert.equal(run('curves.length'), 2);
  assert.equal(snapshot('curves[0].x')[0], 0);
  assert.equal(snapshot('curves[1].x')[0], 4);
  assert.notEqual(snapshot('curves[0].view'), snapshot('curves[1].view'));
  field('独立处理 1').checked = true; field('独立处理 1').emit('change');
  field('独立基线 1').value = 'minimum'; field('独立基线 1').emit('change');
  field('独立平滑 1').value = '5'; field('独立平滑 1').emit('change'); await update();
  elements.get('smoothing').value = '3'; elements.get('smoothing').emit('input'); await update();
  assert.equal(run('curves[0].settings.smoothing'), 5);
  assert.equal(run('curves[1].settings.smoothing'), 3);
  assert.equal(run('curves[0].settings.baseline'), 'minimum');
  assert.equal(run('curves[1].settings.baseline'), 'none');
  const before = snapshot('curves.map(c => c.y)');
  await run('download(true)');
  const url = elements.get('downloadReady').href;
  assert(url && !elements.get('downloadReady').hidden, elements.get('status').textContent);
  const session = await (await fetch(new URL(url, endpoint))).text();
  context.sessionFile = {size:Buffer.byteLength(session), text:async () => session};
  await run("demo('pair')");
  await run('openSession(sessionFile)');
  assert.equal(run('dirty'), false, elements.get('status').textContent);
  assert.deepEqual(snapshot('curves.map(c => c.y)'), before);
  assert.equal(run('extraViews.length'), 1);
  assert.equal(elements.get('smoothing').value, 3); // Mock DOM property, browser coerces to string.
  await run('reread(datasets[0], {skip_rows:99999})');
  assert.equal(run('datasets.length'), 1);
  assert(elements.get('status').textContent.includes('旧数据仍保留'));
  await update();
  await run('reread(datasets[0], {header:"no", skip_rows:1})');
  assert.equal(run('extraViews.length'), 0);
  // Shared smoothing is still 3: the full return scan is intentionally rejected,
  // but branch discovery must be usable to recover without resetting all processing.
  assert(field('扫描分支 1').children.some(option => option.value === '0'));
  field('扫描分支 1').value = '0'; field('扫描分支 1').emit('change'); await update();
  assert.equal(run('curves.length'), 1);
  assert.equal(run('curves[0].processing_scope'), 'shared');
  assert.equal(run('datasets[0].columns[0]'), 'Column 1');
  await run('removeDataset(datasets[0])');
  assert.equal(run('datasets.length'), 0);
  assert.equal(run('curves.length'), 0);
  console.log('Client model/events + real API: branches, overrides, session, reparse, removal OK');
}
main().catch(error => {console.error(error); process.exitCode = 1;}).finally(() => run('clearTimeout(timer)'));
