// Dependency-free behavior checks; actual browser rendering is checked separately.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync('backend/static/manual.html', 'utf8');
const elements = new Map(), calls = [];
function element(tag) {
  return {tag, value: '', textContent: '', disabled: false, hidden: true, children: [], files: [], attributes: {},
    append(child) {this.children.push(child); if (tag === 'select' && !this.value) this.value = child.value;},
    replaceChildren() {this.children = [];}, scrollIntoView() {},
    setAttribute(name, value) {this.attributes[name] = value;}};
}
for (const match of html.matchAll(/<(\w+)[^>]*id="([^"]+)"/g)) elements.set(match[2], element(match[1]));
let failAsk = false, legacyCitation = false;
async function fetch(path, options = {}) {
  calls.push([path, options]); let body;
  if (path === '/v1/knowledge-bases') body = {items: [{id: 'kb', name: 'Demo', embedding_provider: 'hash', embedding_model: 'hash-v1'}]};
  else if (path === '/v1/tasks') body = {id: 'task'};
  else if (path === '/v1/tasks/task') body = {status: 'ready'};
  else if (path === '/v1/knowledge-bases/kb/documents') body = {id: 'doc'};
  else if (path === '/v1/knowledge-bases/kb/documents/doc') body = {status: 'ready', task_id: 'task'};
  else if (path.endsWith('/ask')) {
    if (failAsk) return {ok: false, status: 502, text: async () => 'invalid evidence'};
    body = {answer_id: 'answer', answer: 'Fact', refused: false, status: 'completed',
      claims: [{text: 'Fact', evidence: [{chunk_id: 'chunk', quote: '<img onerror=alert(1)> original text'}]}],
      citations: [{chunk_id: 'chunk', document_id: 'doc', task_id: legacyCitation ? undefined : 'task', filename: 'manual.pdf', pages: [2, 4]}]};
  } else if (path.endsWith('/feedback')) body = {id: 'feedback'};
  else if (path.endsWith('/source')) body = {};
  else if (path.endsWith('.png')) body = {};
  else throw Error('Unexpected request ' + path);
  return {ok: true, json: async () => body, blob: async () => new Blob(['%PDF']), text: async () => ''};
}
const context = vm.createContext({document: {getElementById: id => elements.get(id), createElement: element}, window: {addEventListener() {}}, fetch, Headers, FormData, Blob, URL, setTimeout, Date});
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
(async () => {
  const e = id => elements.get(id);
  e('key').value = 'local-test-secret';
  await e('connect').onclick(); assert.equal(e('kb').value, 'kb');
  e('file').files = [new Blob(['%PDF'])]; e('documentKey').value = 'manual'; e('version').value = 'v1';
  await e('upload').onclick(); assert.match(e('progress').textContent, /入库完成/);
  e('question').value = 'parameter'; e('mode').value = 'hybrid'; e('rrf').value = '30';
  await e('ask').onclick(); assert.equal(e('answer').textContent, 'Fact');
  const quote = e('evidence').children[0].children.find(child => child.tag === 'blockquote');
  assert.equal(quote.textContent, '<img onerror=alert(1)> original text'); assert.equal(quote.children.length, 0);
  const row = e('citations').children[0], review = row.children.find(child => child.tag === 'label').children[0];
  assert.equal(review.value, 'unreviewed');
  await row.children[1].onclick(); assert.match(e('sourceLabel').textContent, /第 4 页/); assert.equal(e('pdfPage').hidden, false);
  await e('helpful').onclick();
  let feedback = JSON.parse(calls.at(-1)[1].body); assert.deepEqual(feedback.valid_citation_ids, []);
  review.value = 'valid'; e('correction').value = 'Correct answer'; e('comment').value = 'Checked page';
  await e('helpful').onclick(); feedback = JSON.parse(calls.at(-1)[1].body);
  assert.deepEqual(feedback.valid_citation_ids, ['chunk']); assert.equal(feedback.correction, 'Correct answer');
  review.value = 'invalid'; await e('unhelpful').onclick(); feedback = JSON.parse(calls.at(-1)[1].body);
  assert.deepEqual(feedback.invalid_citation_ids, ['chunk']); assert.deepEqual(feedback.valid_citation_ids, []);
  assert(!calls.some(([path]) => path.includes('limit=200')));
  legacyCitation = true; await e('ask').onclick(); await e('citations').children[0].children[0].onclick();
  assert(calls.some(([path, options]) => path.endsWith('/documents/doc') && !options.method));
  failAsk = true; await e('ask').onclick(); assert.equal(e('answer').textContent, ''); assert.match(e('status').textContent, /失败/);
  await e('helpful').onclick(); assert.match(e('error').textContent, /请先完成提问/);
  assert(calls.every(([, options]) => options.headers.get('Authorization') === 'Bearer local-test-secret'));
  console.log('PASS: upload/index/query/quote text/page navigation/manual citation review/correction/legacy source/error cleanup/authentication');
})().catch(error => {console.error(error); process.exitCode = 1;});
