// Dependency-free behavior checks; actual browser rendering is checked separately.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync('backend/static/manual.html', 'utf8');
const calls = [], storage = new Map();
const {File} = require('node:buffer');
const crypto = require('crypto').webcrypto;
const documents = new Map([
  ['kb', [{id: 'saved-manual', document_key: 'manual-key', filename: 'manual.pdf', version: 'v1', status: 'ready', is_current: true}]],
  ['resume', [{id: 'resume-doc', document_key: 'resume-key', filename: '简历.pdf', version: 'v1', status: 'ready', is_current: true}]],
]);
const selectionKey = 'pdf-inspector.lastKnowledgeBase';
const library = [
  {id: 'kb', name: 'Demo', embedding_provider: 'hash', embedding_model: 'hash-v1'},
  {id: 'resume', name: '我的简历', embedding_provider: 'hash', embedding_model: 'hash-v1'},
];
function element(tag) {
  return {tag, value: '', textContent: '', disabled: false, hidden: true, children: [], files: [], attributes: {},
    append(child) {this.children.push(child); if (tag === 'select' && !this.value) this.value = child.value;},
    replaceChildren() {this.children = []; if (tag === 'select') this.value = '';}, scrollIntoView() {}, focus() {this.focused = true;},
    setAttribute(name, value) {this.attributes[name] = value;}};
}
let failAsk = false, legacyCitation = false, failLoad = false, requireKey = false, taskFile = null, failIngest = false, conflictingIngest = false, offline = false;
let failDelete = '';
async function fileHash(file) {
  return Buffer.from(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())).toString('hex');
}
async function fetch(path, options = {}) {
  calls.push([path, options]); let body;
  assert.equal(options.cache, 'no-store');
  if (offline) throw Error('NetworkError when attempting to fetch resource.');
  if (requireKey && !options.headers.get('Authorization')) return {ok: false, status: 401, text: async () => '{"detail":"unauthorized"}'};
  if (/^\/v1\/knowledge-bases\/[^/]+$/.test(path)) {
    const id = path.split('/')[3], item = library.find(item => item.id === id);
    if (!item) return {ok: false, status: 404, text: async () => 'knowledge_base_not_found'};
    if (options.method === 'DELETE') {
      if (failDelete === 'permission') return {ok: false, status: 403, text: async () => '{"detail":"forbidden"}'};
      if (failDelete === 'busy') return {ok: false, status: 409, text: async () => '{"detail":"cannot delete a knowledge base while indexing is active"}'};
      library.splice(library.indexOf(item), 1); documents.delete(id);
      return {ok: true, status: 204};
    }
    return {ok: true, json: async () => ({...item, document_count: (documents.get(id) || []).length})};
  }
  if (path === '/v1/knowledge-bases' && options.method === 'POST') {
    const {name} = JSON.parse(options.body);
    if (library.some(item => item.name === name)) return {ok: false, status: 409, text: async () => '{"detail":"knowledge_base_already_exists"}'};
    body = {id: 'created-' + library.length, name, embedding_provider: 'hash', embedding_model: 'hash-v1'};
    library.unshift(body);
  }
  else if (path.startsWith('/v1/knowledge-bases?')) {
    if (failLoad) return {ok: false, status: 503, text: async () => 'unavailable'};
    const offset = Number(new URL(path, 'http://localhost').searchParams.get('offset'));
    body = {items: library.slice(offset, offset + 200)};
  }
  else if (/\/documents\?/.test(path)) body = {items: documents.get(path.split('/')[3]) || []};
  else if (path === '/v1/tasks') {taskFile = options.body.get('file'); body = {id: 'task'};}
  else if (path === '/v1/tasks/task') body = {status: 'ready'};
  else if (path.endsWith('/documents') && options.method === 'POST') {
    if (failIngest) {failIngest = false; return {ok: false, status: 503, text: async () => 'retry later'};}
    if (conflictingIngest) {conflictingIngest = false; return {ok: true, json: async () => ({id: 'another-saved-document', idempotent: true})};}
    const kb = path.split('/')[3], payload = JSON.parse(options.body);
    assert.equal(payload.version, undefined, 'ordinary updates must replace the existing document without adding history rows');
    const items = documents.get(kb) || [];
    let item = items.find(item => item.document_key === payload.document_key);
    if (!item) {item = {id: kb === 'kb' ? 'doc' : 'new-' + items.length, document_key: payload.document_key}; items.push(item);}
    Object.assign(item, {filename: taskFile.name, content_hash: await fileHash(taskFile), status: 'ready', task_id: 'task', is_current: true});
    documents.set(kb, items); body = {...item};
  }
  else if (/\/documents\/[^/]+$/.test(path)) body = {status: 'ready', task_id: 'task'};
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
function createPage(blockStorage = false) {
  let allowDelete = false;
  const confirmations = [];
  const elements = new Map();
  for (const match of html.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const item = element(match[1]);
    item.value = match[0].match(/\bvalue="([^"]*)"/)?.[1] || '';
    item.disabled = /\bdisabled\b/.test(match[0]);
    elements.set(match[2], item);
  }
  const localStorage = {
    getItem(key) {if (blockStorage) throw Error('blocked'); return storage.get(key);},
    setItem(key, value) {if (blockStorage) throw Error('blocked'); storage.set(key, value);},
    removeItem(key) {if (blockStorage) throw Error('blocked'); storage.delete(key);},
  };
  const context = vm.createContext({document: {getElementById: id => elements.get(id), createElement: element}, window: {addEventListener() {}, confirm(message) {confirmations.push(message); return allowDelete;}}, localStorage, fetch, Headers, FormData, Blob, URL, setTimeout, Date, crypto});
  const ready = vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  return {e: id => elements.get(id), ready, confirmations, allowDelete(value) {allowDelete = value;}};
}
(async () => {
  const page = createPage(), e = page.e;
  assert.equal(e('name').value, ''); assert.equal(e('create').disabled, true);
  await page.ready;
  assert.equal(e('kb').value, 'kb'); assert.equal(e('documents').children[0].textContent, 'manual.pdf · v1 · 可查询');
  await e('create').onclick(); assert.match(e('createStatus').textContent, /请先填写/);
  assert(!calls.some(([, options]) => options.method === 'POST'));
  e('name').value = '   '; e('name').oninput(); assert.equal(e('create').disabled, true);
  e('name').value = 'Demo'; e('name').oninput(); assert.equal(e('create').disabled, false);
  await e('create').onclick(); assert.match(e('createStatus').textContent, /已有同名知识库/); assert.equal(e('name').value, 'Demo');
  e('name').value = '  新资料  '; await e('create').onclick();
  assert.match(e('createStatus').textContent, /已创建“新资料”/);
  assert.equal(e('name').value, ''); assert.equal(e('create').disabled, true);
  assert.equal(e('kb').value, library[0].id); assert.equal(storage.get(selectionKey), library[0].id);
  assert.match(e('documentsStatus').textContent, /还没有资料/);
  e('kb').value = 'resume'; await e('kb').onchange();
  const postsBeforeReload = calls.filter(([, options]) => options.method === 'POST').length;
  const reopened = createPage(); await reopened.ready;
  assert.equal(reopened.e('kb').value, 'resume');
  assert.match(reopened.e('documents').children[0].textContent, /简历.pdf.*可查询/);
  assert.equal(calls.filter(([, options]) => options.method === 'POST').length, postsBeforeReload);
  // Updating a renamed PDF must reuse the original identity and leave only one document.
  const r = reopened.e, resumeFile = new File(['%PDF revised resume'], '简历新版.pdf', {type: 'application/pdf'});
  r('documents').children[0].children[1].onclick();
  assert.equal(r('uploadTarget').value, 'resume-doc');
  r('file').files = [resumeFile]; r('file').onchange();
  assert.equal(r('upload').textContent, '更新并保存');
  await r('upload').onclick(); assert.match(r('progress').textContent, /资料已更新并保存/);
  assert.equal(documents.get('resume').length, 1); assert.equal(documents.get('resume')[0].document_key, 'resume-key');
  assert.equal(documents.get('resume')[0].filename, '简历新版.pdf');
  assert.equal(r('documentScope').value, 'resume-doc');
  const beforeDuplicate = calls.length;
  await r('upload').onclick(); assert.match(r('progress').textContent, /无需重复导入/);
  assert(!calls.slice(beforeDuplicate).some(([, options]) => options.method === 'POST'));
  const updatedReload = createPage(); await updatedReload.ready;
  assert.match(updatedReload.e('documents').children[0].textContent, /简历新版.pdf/);
  updatedReload.e('documents').children[0].children[0].onclick();
  updatedReload.e('question').value = '简历内容'; await updatedReload.e('ask').onclick();
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body).document_ids, ['resume-doc']);
  // An ingest error can be retried without uploading/processing the PDF again.
  r('file').files = [new File(['%PDF second revision'], '简历第二版.pdf')]; r('file').onchange();
  failIngest = true; await r('upload').onclick();
  const tasksBeforeRetry = calls.filter(([path]) => path === '/v1/tasks').length;
  await r('upload').onclick();
  assert.match(r('progress').textContent, /资料已更新并保存/);
  assert.equal(calls.filter(([path]) => path === '/v1/tasks').length, tasksBeforeRetry);
  assert.equal(documents.get('resume').length, 1);
  r('file').files = [new File(['%PDF matches another historical document'], '其他旧文件.pdf')]; r('file').onchange();
  conflictingIngest = true; await r('upload').onclick();
  assert.match(r('progress').textContent, /本次没有替换当前资料/);
  assert.equal(documents.get('resume')[0].filename, '简历第二版.pdf');
  storage.set(selectionKey, 'deleted'); const stale = createPage(); await stale.ready;
  assert.equal(stale.e('kb').value, library[0].id);
  const blocked = createPage(true); await blocked.ready; assert.equal(blocked.e('error').textContent, '');
  failLoad = true; e('name').value = '创建后刷新失败'; await e('create').onclick();
  assert.match(e('createStatus').textContent, /已创建/); assert.match(e('libraryStatus').textContent, /创建已成功/);
  assert.equal(e('name').value, ''); failLoad = false;
  requireKey = true; const protectedPage = createPage(); await protectedPage.ready;
  assert.match(protectedPage.e('libraryStatus').textContent, /API 密钥/);
  protectedPage.e('key').value = 'local-test-secret'; await protectedPage.e('connect').onclick();
  assert.equal(protectedPage.e('error').textContent, ''); requireKey = false;
  e('kb').value = 'kb';
  e('key').value = 'local-test-secret';
  const authenticatedStart = calls.length;
  await e('connect').onclick(); assert.equal(e('kb').value, 'kb');
  e('file').files = [new File(['%PDF manual'], 'manual.pdf')]; e('file').onchange();
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
  legacyCitation = true; await e('ask').onclick(); await e('citations').children[0].children[0].onclick();
  assert(calls.some(([path, options]) => path.endsWith('/documents/doc') && !options.method));
  failAsk = true; await e('ask').onclick(); assert.equal(e('answer').textContent, ''); assert.match(e('status').textContent, /失败/);
  const failedKey = calls.at(-1)[1].headers.get('Idempotency-Key');
  failAsk = false; await e('ask').onclick();
  assert.equal(calls.at(-1)[1].headers.get('Idempotency-Key'), failedKey);
  failAsk = true; await e('ask').onclick();
  await e('helpful').onclick(); assert.match(e('error').textContent, /请先完成提问/);
  assert(calls.slice(authenticatedStart).every(([, options]) => options.headers.get('Authorization') === 'Bearer local-test-secret'));
  assert(calls.filter(([path, options]) => path.endsWith('/ask') || (path === '/v1/tasks' && options.method)).every(([, options]) => options.headers.get('Idempotency-Key')));
  // Deletion requires a confirmation for the selected name/count and preserves other bases.
  const deletionPage = createPage(); await deletionPage.ready;
  const d = deletionPage.e; d('kb').value = 'resume'; await d('kb').onchange();
  const deletesBeforeCancel = calls.filter(([, options]) => options.method === 'DELETE').length;
  await d('deleteKb').onclick();
  assert.match(deletionPage.confirmations.at(-1), /我的简历.*\n包含 1 份资料/);
  assert.equal(calls.filter(([, options]) => options.method === 'DELETE').length, deletesBeforeCancel);
  assert.match(d('deleteStatus').textContent, /已取消/);
  deletionPage.allowDelete(true); failDelete = 'permission'; await d('deleteKb').onclick();
  assert.match(d('deleteStatus').textContent, /管理员/); assert.equal(d('kb').value, 'resume');
  failDelete = 'busy'; await d('deleteKb').onclick(); assert.match(d('deleteStatus').textContent, /等待完成/);
  failDelete = ''; d('question').value = 'old question'; d('answer').textContent = 'old answer';
  await d('deleteKb').onclick(); assert.match(d('deleteStatus').textContent, /已删除知识库“我的简历”/);
  assert(!library.some(item => item.id === 'resume')); assert(library.some(item => item.id === 'kb'));
  assert.notEqual(d('kb').value, 'resume'); assert.equal(storage.get(selectionKey), d('kb').value);
  assert.equal(d('answer').textContent, ''); assert.equal(d('question').value, '');
  const remaining = d('kb').value; failLoad = true; await d('deleteKb').onclick(); failLoad = false;
  assert.match(d('deleteStatus').textContent, /已删除.*列表刷新失败/);
  assert(!library.some(item => item.id === remaining)); assert.equal(d('deleteKb').disabled, true);
  // Explicitly deleting the last base must not silently recreate it, even on reopening.
  library.splice(0); library.push({id: 'last-base', name: '不用的知识库'});
  const lastPage = createPage(); await lastPage.ready; lastPage.allowDelete(true);
  const postsBeforeDeleteLast = calls.filter(([, options]) => options.method === 'POST').length;
  await lastPage.e('deleteKb').onclick(); assert.equal(library.length, 0);
  assert.equal(lastPage.e('deleteKb').disabled, true); assert.equal(lastPage.e('kb').value, '');
  const afterLastDelete = createPage(); await afterLastDelete.ready;
  await afterLastDelete.e('connect').onclick();
  assert.equal(library.length, 0); assert.equal(calls.filter(([, options]) => options.method === 'POST').length, postsBeforeDeleteLast);
  afterLastDelete.e('name').value = '重新建立'; await afterLastDelete.e('create').onclick();
  assert.equal(library.length, 1); assert.equal(afterLastDelete.e('deleteKb').disabled, false);
  // A first visit creates a default once; reopening reuses it.
  library.splice(0); const empty = createPage(); await empty.ready;
  assert.equal(library.length, 1); assert.equal(library[0].name, '我的资料');
  assert.equal(empty.e('kb').value, library[0].id); assert.equal(empty.e('name').value, '');
  const defaultPosts = calls.filter(([path, options]) => path === '/v1/knowledge-bases' && options.method === 'POST').length;
  const defaultReload = createPage(); await defaultReload.ready;
  assert.equal(calls.filter(([path, options]) => path === '/v1/knowledge-bases' && options.method === 'POST').length, defaultPosts);
  // Concurrent first visits handle the unique-name conflict and select the same default.
  library.splice(0); const first = createPage(), second = createPage(); await Promise.all([first.ready, second.ready]);
  assert.equal(library.length, 1); assert.equal(first.e('kb').value, second.e('kb').value);
  assert.equal(second.e('error').textContent, '');
  offline = true; const disconnected = createPage(); await disconnected.ready;
  assert.match(disconnected.e('libraryStatus').textContent, /请启动 PDF资料库.exe/);
  assert.match(disconnected.e('kb').children[0].textContent, /未连接/);
  disconnected.e('name').value = '简历'; await disconnected.e('create').onclick();
  assert.match(disconnected.e('createStatus').textContent, /连接不到本机资料库服务/);
  offline = false; await disconnected.e('connect').onclick();
  assert.equal(disconnected.e('error').textContent, '');
  library.splice(0);
  for (let index = 0; index < 201; index++) library.push({id: 'page-' + index, name: 'Library ' + index});
  storage.set(selectionKey, 'page-200'); const paged = createPage(); await paged.ready;
  assert.equal(paged.e('kb').value, 'page-200'); assert.equal(paged.e('kb').children.length, 201);
  console.log('PASS: delete confirmation/cancel/permission/busy/switch base/clear stale answer/last-base deletion/default creation/restore/update/query/auth/cache/evidence/source/feedback');
})().catch(error => {console.error(error); process.exitCode = 1;});
