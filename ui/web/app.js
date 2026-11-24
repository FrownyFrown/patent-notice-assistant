'use strict';
history.replaceState(null, '', location.pathname);
const $ = id => document.getElementById(id);
const list = value => Array.isArray(value) ? value : [];
const rows = value => list(value).filter(v => v && typeof v === 'object' && !Array.isArray(v));
const obj = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
const str = value => value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
const tones = {yes: 'good', pass: 'good', accepted: 'good', ok: 'good', no_reason_found: 'good', partial: 'mid', moved: 'mid', warn: 'mid', hold: 'mid', unverified: 'bad', fail: 'bad', refuse_draft: 'bad'};
const mark = (parent, text, code) => el('p', text, parent, 'badge ' + (Object.hasOwn(tones, code) ? tones[code] : ''));
const joined = value => list(value).map(str).join(', ');
const statuses = {todo: '차례 전', ready: '할 차례', working: '작업 중', done: '끝남', warning: '확인 필요', error: '오류', skipped: '건너뜀', stale: '다시 필요'};
const verdicts = {yes: '있음', partial: '일부', no: '없음', unverified: '미확인'};
const checks = {pass: '원문 일치', moved: '단락번호 고침', fail: '원문 불일치', none: '인용문 없음'};
let generation = 0, selected = '', revision = null, reviewKey = '', etag = '', artifactKey = '', caseListKey = '', chatKey = '', state = {};
let sending = false, composing = false;
function el(tag, text, parent, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = str(text);
  if (className) node.className = className;
  if (parent) parent.append(node);
  return node;
}
function paragraph(parent, text) { return el('p', text || '없음', parent, 'pre'); }
function section(id, title) { const node = $(id); node.replaceChildren(); el('h2', title, node); return node; }
function fields(parent, values) {
  const dl = el('dl', null, parent);
  for (const [label, value] of values) { el('dt', label, dl); el('dd', str(value) || '없음', dl); }
}
function evidence(d) {
  const e = obj(d.evidence);
  if (d.basis === 'well_known') return '주지관용 증거 ' + (e.has_evidence ? '있음' : '없음') + (e.detail ? ': ' + str(e.detail) : '');
  if (d.basis === 'design_choice') return '설계사항 근거 1: ' + str(e.condition_1) + '\n설계사항 근거 2: ' + str(e.condition_2);
  return '';
}
function table(parent, caption, headings, data, render) {
  const wrap = el('div', null, parent, 'table-wrap'); wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', caption + ' 가로 스크롤');
  const t = el('table', null, wrap); el('caption', caption, t);
  const head = el('tr', null, el('thead', null, t));
  for (const h of headings) { const th = el('th', h, head); th.scope = 'col'; }
  const body = el('tbody', null, t);
  for (const row of data) {
    const tr = el('tr', null, body);
    headings.forEach((_, index) => { const cell = el(index === 0 ? 'th' : 'td', null, tr); if (index === 0) cell.scope = 'row'; render(cell, row, index); });
  }
  if (!data.length) paragraph(parent, '아직 자료가 없습니다');
  return t;
}
function copyButton(parent, text) {
  const button = el('button', '복사', parent); button.type = 'button';
  button.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(str(text)); button.textContent = '복사됨'; }
    catch { button.textContent = '글을 선택해 복사하세요'; }
  });
}
async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {...options, signal: controller.signal, cache: 'no-store'});
    if (response.status === 304) return {unchanged: true};
    const data = await response.json();
    if (!response.ok) throw new Error(response.status === 401 ? '화면을 닫고 실행 파일로 다시 열어 주세요' : str(data.error) || '요청에 실패했습니다');
    return {data, etag: response.headers.get('ETag')};
  } finally { clearTimeout(timeout); }
}
function post(path, data) { return api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)}); }
function preserve(action) {
  const open = new Set(Array.from(document.querySelectorAll('details[open]')).map(n => n.dataset.key));
  const active = document.activeElement;
  const id = active && active.id;
  const focusSection = active && active.closest('section');
  const focusSelector = 'button, a, input, summary, [tabindex]';
  const focusIndex = focusSection ? Array.from(focusSection.querySelectorAll(focusSelector)).indexOf(active) : -1;
  const scrolls = Array.from(document.querySelectorAll('.table-wrap')).map(n => [n.getAttribute('aria-label'), n.scrollLeft]);
  const x = window.scrollX, y = window.scrollY;
  action();
  document.querySelectorAll('details').forEach(n => { n.open = open.has(n.dataset.key); });
  if (id && $(id) && active !== $(id)) $(id).focus({preventScroll: true});
  else if (focusSection && focusIndex >= 0 && !active.isConnected) {
    const replacement = focusSection.querySelectorAll(focusSelector)[focusIndex];
    if (replacement) replacement.focus({preventScroll: true});
  }
  document.querySelectorAll('.table-wrap').forEach(n => { const old = scrolls.find(r => r[0] === n.getAttribute('aria-label')); if (old) n.scrollLeft = old[1]; });
  window.scrollTo(x, y);
}
function renderState(s) {
  $('draft').textContent = str(s.draft_notice);
  const steps = $('steps'); steps.replaceChildren();
  const names = ['청구항', '구성 분해', '검색', '대조', '빈칸 검색', '판단 초안', '통지서'];
  names.forEach((name, i) => {
    const step = rows(s.steps).find(r => r.id === i + 1) || {};
    const li = el('li', name, steps, Object.hasOwn(statuses, step.status) ? step.status : 'todo');
    if (obj(s.next).step === i + 1) li.setAttribute('aria-current', 'step');
    el('p', statuses[step.status] || '차례 전', li, 'badge');
    if (step.message) paragraph(li, step.message);
  });
  const next = section('next', '지금 할 일'); paragraph(next, obj(s.next).title || '다음 작업이 없습니다');
  if (obj(s.next).say) { paragraph(next, s.next.say); copyButton(next, s.next.say); }
  const input = obj(s.input), zero = rows(s.steps).find(r => r.id === 0) || {};
  fields(section('summary', '사건 요약'), [['발명의 명칭', s.title], ['출원번호', s.application_number], ['출원일', input.application_date],
    ['우선일', input.priority_date], ['기준일', input.basis_date], ['파일 이름', input.file_name],
    ['입력 상태', (statuses[zero.status] || '차례 전') + ' ' + str(zero.message)], ['경고', joined(input.warnings)]]);
  const claims = section('claims', '청구항 원문');
  if (!rows(s.claims).length) paragraph(claims, '아직 청구항이 없습니다');
  rows(s.claims).forEach(c => {
    const a = el('article', null, claims); el('h3', '청구항 ' + str(c.number), a);
    paragraph(a, (c.kind === 'independent' ? '독립항' : c.kind === 'dependent' ? '종속항' : '구분 전') + (c.deleted ? ' / 삭제' : ''));
    if (list(c.depends_on).length) paragraph(a, '인용항: ' + joined(c.depends_on));
    paragraph(a, c.text); if (list(c.warnings).length) paragraph(a, '경고: ' + joined(c.warnings));
  });
  const docs = rows(s.candidates), shown = docs.filter(d => d.status === 'accepted' || rows(s.matrix).some(m => m.doc_id === d.doc_id));
  table(section('matrix', '구성요소 대조표'), '구성요소별 문헌 대조', ['구성요소', ...shown.map(d => str(d.doc_id) + (d.status === 'excluded' ? ' (제외)' : ''))], rows(s.components), (cell, c, index) => {
    if (!index) { paragraph(cell, str(c.id) + '\n' + str(c.text)); return; }
    const doc = shown[index - 1];
    const m = rows(s.matrix).find(r => r.component_id === c.id && r.doc_id === doc.doc_id);
    if (!m) { cell.textContent = '아직 안 봄'; return; }
    mark(cell, verdicts[m.verdict] || '미확인', m.verdict);
    paragraph(cell, list(m.paragraphs).length ? '단락 ' + joined(m.paragraphs) : '단락번호 없음');
    mark(cell, checks[m.check] || '미확인', m.check);
    if (m.check_message) paragraph(cell, m.check_message);
    if (m.note) paragraph(cell, m.note);
    const detail = el('details', null, cell); detail.dataset.key = 'matrix-' + c.id + '-' + doc.doc_id;
    const summary = el('summary', '인용문과 원문 단락', detail); summary.id = detail.dataset.key;
    paragraph(detail, m.quote || '인용문 없음');
    rows(m.passages).forEach(p => { paragraph(detail, (p.num || '단락번호 없음') + (p.translated ? ' / 번역' : ' / 원문')); paragraph(detail, p.text); });
  }).className = 'matrix';
  const gaps = section('gaps', '빈칸');
  rows(s.gaps).forEach(g => paragraph(gaps, str(g.component_id) + ': ' + str(g.text) + '\n' + (verdicts[g.best_verdict] || '미확인') + ' / ' + (g.searched ? '검색함' : '검색 전')));
  if (!rows(s.gaps).length) paragraph(gaps, '표시할 빈칸이 없습니다');
  table(section('candidates', '후보 문헌'), '후보 문헌 목록', ['번호', '제목', '공개일', '출처', '상태', '빠진 사유'], docs, (cell, d, i) => {
    const origins = {web_search: '웹 검색', user_pdf: '담당자 PDF', search_report: '검색 보고서', manual: '직접 입력'};
    const values = [d.doc_id, d.title, d.publication_date, origins[d.origin] || d.origin, {pending: '아직 안 받음', accepted: '채택', excluded: '제외'}[d.status] || '미확인', d.excluded_reason];
    if (i === 4) mark(cell, values[i], d.status === 'excluded' ? 'fail' : d.status); else cell.textContent = str(values[i]);
    if (i === 1 && d.machine_translated) paragraph(cell, '기계번역');
    if (i === 0 && typeof d.url === 'string' && d.url.startsWith('https://patents.google.com/')) {
      el('br', null, cell); const a = el('a', '공보 열기', cell); a.href = d.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    }
  });
  const verification = section('verification', '원문 대조 결과'), v = obj(s.verification), summary = obj(v.summary);
  paragraph(verification, Object.keys(checks).map(k => checks[k] + ' ' + str(summary[k] || 0) + '건').join(' / '));
  table(verification, '원문 대조 항목', ['구성요소', '문헌', '단락', '결과', '내용'], rows(v.items), (cell, r, i) => {
    if (i === 3) { mark(cell, checks[r.result] || '미확인', r.result); return; }
    cell.textContent = str([r.component_id, r.doc_id, joined(r.paragraphs) || '단락번호 없음', checks[r.result] || '미확인', [r.message, r.quote].map(str).filter(Boolean).join('\n')][i]); cell.className = 'pre';
  });
  const conclusions = section('conclusions', '결론');
  rows(s.conclusions).forEach(c => {
    const a = el('article', null, conclusions); el('h3', '청구항 ' + str(c.claim), a);
    mark(a, {refuse_draft: '거절 초안', hold: '보류', no_reason_found: '거절이유 찾지 못함'}[c.verdict] || '판단 전', c.verdict);
    fields(a, [['조문', {'29-1-2': '제29조제1항제2호', '29-2': '제29조제2항'}[c.statute] || c.statute], ['인용발명 번호', joined(c.reference_nos)],
      ['공통 구성', c.common_claim_text], ['인용 구성', c.common_cited_text],
      ['차이점', rows(c.differences).map(d => [d.text, d.reason, d.doc_id, joined(d.paragraphs), evidence(d)].filter(Boolean).join('\n')).join('\n\n')],
      ['동기', c.motivation], ['효과 검토', c.effect_review], ['논리가 깨질 지점', c.weak_point], ['보류 사유', joined(c.hold_reasons)], ['문장', list(c.sentences).map(str).join('\n\n')]].filter(r => r[1]));
  });
  if (!rows(s.conclusions).length) paragraph(conclusions, '판단 전');
  table(section('references', '인용발명 번호표'), '인용발명', ['번호', '문헌', '제목', '공개일', '사용 청구항'], rows(s.references), (cell, r, i) => {
    cell.textContent = str([r.no, r.doc_id, str(r.title) + (r.machine_translated ? ' / 기계번역' : ''), r.publication_date, joined(r.used_in)][i]);
  });
  table(section('checklist', '점검표'), '점검 항목', ['항목', '구분', '결과', '메모'], rows(s.checklist), (cell, r, i) => {
    if (i === 2) { mark(cell, {ok: '확인', warn: '확인 필요', fail: '오류', todo: '확인 전'}[r.result] || '미확인', r.result); return; }
    cell.textContent = str([r.label, r.section, '', r.note][i]);
  });
  const notes = section('notes', '참고 메모');
  rows(s.notes).forEach(n => { const a = el('article', null, notes); paragraph(a, (n.claim ? '청구항 ' + str(n.claim) + '\n' : '') + str(n.text)); if (n.quote) paragraph(a, n.quote); });
  if (!rows(s.notes).length) paragraph(notes, '메모가 없습니다');
  renderArtifacts(s);
}
function renderArtifacts(s) {
  const artifacts = rows(s.artifacts), html = artifacts.find(a => a.kind === 'html'), docx = artifacts.find(a => a.kind === 'docx');
  const stale = artifacts.some(a => a.stale);
  $('notice-status').textContent = stale ? '앞 단계가 바뀌어 다시 만들어야 합니다' : artifacts.length ? '초안, 담당자 확인 필요' : '아직 통지서가 없습니다';
  $('download').hidden = !docx;
  if (docx) $('download').href = '/api/cases/' + encodeURIComponent(selected) + '/notice.docx';
  const key = html ? selected + '/' + str(html.created_at) : '';
  if (key !== artifactKey) {
    artifactKey = key; $('preview').hidden = !html;
    if (html) $('preview').src = '/api/cases/' + encodeURIComponent(selected) + '/notice.html?v=' + encodeURIComponent(str(html.created_at));
    else $('preview').removeAttribute('src');
  }
}
function renderReview(s, review) {
  const root = section('review', '담당자 확인');
  rows(s.review_items).forEach(item => {
    const saved = obj(obj(review.items)[item.key]);
    const label = el('label', null, root), input = el('input', null, label); input.type = 'checkbox'; input.id = 'review-' + str(item.key); input.checked = saved.checked === true;
    el('span', str(item.label) + (saved.checked && saved.revision !== s.revision ? ' / 확인 뒤 바뀜' : ''), label);
    input.addEventListener('change', async () => {
      const chosen = selected, version = generation, value = input.checked; input.disabled = true;
      try {
        await post('/api/cases/' + encodeURIComponent(chosen) + '/review', {key: item.key, checked: value, revision: s.revision});
        if (generation === version) { etag = ''; reviewKey = ''; $('status').textContent = '확인을 저장했습니다'; }
      } catch (error) { if (generation === version) { input.checked = !value; $('status').textContent = error.message; etag = ''; } }
      finally { input.disabled = false; }
    });
  });
}
function selectCase() {
  selected = $('cases').value; generation++; revision = null; etag = ''; reviewKey = '';
  $('case-content').hidden = true; paragraph(section('review', '담당자 확인'), '사건을 고르세요');
  $('status').className = '';
  $('draft').textContent = '초안, 담당자 확인 필요';
  $('status').textContent = selected ? '읽는 중입니다' : 'input 폴더에 파일을 넣거나 파일을 올리세요';
}
$('cases').addEventListener('change', selectCase);
function renderChat(data) {
  const enabled = data.enabled === true;
  $('chat-disabled').hidden = enabled; $('chat-enabled').hidden = !enabled; $('chat-status').textContent = '';
  if (!enabled) return;
  const messages = rows(data.messages), key = JSON.stringify(messages);
  if (key === chatKey) return;
  chatKey = key; const log = $('messages'); const position = log.scrollTop;
  const bottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.replaceChildren();
  messages.forEach(m => { const a = el('article', null, log); el('strong', m.role === 'user' ? '담당자' : '답변', a); paragraph(a, str(m.ts).slice(0, 16).replace('T', ' ')); paragraph(a, m.text); });
  log.scrollTop = bottom ? log.scrollHeight : position;
}
async function poll() {
  try {
    if (document.hidden) return;
    const version = generation;
    let requestGeneration = version;
    try {
      const result = await api('/api/cases');
      if (version === generation) {
        const cases = rows(result.data), key = JSON.stringify(cases);
        if (caseListKey !== key) {
          caseListKey = key; $('cases').replaceChildren(); el('option', '사건을 고르세요', $('cases')).value = '';
          cases.forEach(c => { const option = el('option', str(c.title || c.case_id) + (c.error ? ' / 오류' : ''), $('cases')); option.value = str(c.case_id); });
          $('cases').value = cases.some(c => c.case_id === selected) ? selected : '';
          if (!selected && cases.length) { $('cases').value = str(cases[0].case_id); selectCase(); }
          else if (selected && !cases.some(c => c.case_id === selected)) selectCase();
        }
        if (!selected) $('status').className = '';
        if (!selected) $('status').textContent = '아직 사건이 없습니다. 파일을 올린 뒤 Codex 채팅에서 검토를 시작하세요';
      }
      if (document.hidden) return;
      const chosen = selected, current = generation;
      requestGeneration = current;
      if (chosen) {
        const response = await api('/api/cases/' + encodeURIComponent(chosen), {headers: etag ? {'If-None-Match': etag} : {}});
        if (current === generation && chosen === selected) {
          if (!response.unchanged) {
            const data = obj(response.data); state = obj(data.state); const review = obj(data.review);
            const changed = revision !== state.revision, nextKey = JSON.stringify(review);
            preserve(() => { if (changed) renderState(state); if (changed || reviewKey !== nextKey) renderReview(state, review); });
            revision = state.revision; reviewKey = nextKey; etag = response.etag || '';
          }
          $('case-content').hidden = false; $('status').textContent = ''; $('status').className = '';
        }
      }
    } catch (error) {
      if (requestGeneration === generation) { $('status').className = 'problem'; $('status').textContent = error.name === 'TypeError' || error.name === 'AbortError' ? '서버 연결이 끊겼습니다. 다시 연결하는 중입니다' : error.message; }
    }
    if (document.hidden) return;
    try { renderChat(obj((await api('/api/chat')).data)); }
    catch (error) { $('chat-status').textContent = '채팅을 읽을 수 없습니다. 다시 연결하는 중입니다'; }
  } finally { setTimeout(poll, 2000); }
}
for (const text of ['처음 설정해줘', 'input 폴더의 출원을 검토해줘. 공개된 출원이야', '이어서 해줘']) {
  paragraph($('prompts'), text); copyButton($('prompts'), text);
}
function count() { $('chat-count').textContent = Array.from($('chat-text').value.trim()).length + ' / 4000자'; }
$('chat-text').addEventListener('input', count);
$('chat-text').addEventListener('compositionstart', () => { composing = true; });
$('chat-text').addEventListener('compositionend', () => { composing = false; });
$('chat-text').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !composing && event.keyCode !== 229) { event.preventDefault(); send(); }
});
async function send() {
  if (sending) return;
  const text = $('chat-text').value.trim();
  if (!text || Array.from(text).length > 4000 || text.includes('\u0000')) { $('chat-status').textContent = '글은 1자부터 4000자까지입니다'; return; }
  sending = true; $('send').disabled = true;
  const original = $('chat-text').value;
  try { await post('/api/chat', {text, case: selected}); if ($('chat-text').value === original) $('chat-text').value = ''; count(); $('chat-status').textContent = '보냈습니다'; }
  catch (error) { $('chat-status').textContent = error.message; }
  finally { sending = false; $('send').disabled = false; }
}
$('send').addEventListener('click', send);
$('upload').addEventListener('change', () => {
  const file = $('upload').files[0]; if (!file) return;
  if (!/\.(pdf|txt)$/i.test(file.name) || !file.size || file.size > 50 * 1024 * 1024) { $('upload-result').textContent = '50MB 이하의 PDF 또는 TXT를 고르세요'; return; }
  const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/upload?name=' + encodeURIComponent(file.name));
  xhr.setRequestHeader('Content-Type', 'application/octet-stream'); xhr.timeout = 120000;
  $('upload').disabled = true; $('upload-progress').hidden = false; $('upload-progress').value = 0; $('upload-result').textContent = '올리는 중입니다';
  xhr.upload.addEventListener('progress', e => { if (e.lengthComputable) $('upload-progress').value = e.loaded / e.total * 100; });
  xhr.addEventListener('load', () => {
    try { const data = JSON.parse(xhr.responseText); $('upload-result').textContent = xhr.status === 201 ? str(data.name) + ': Codex 채팅에서 검토를 시작하세요' : xhr.status === 401 ? '화면을 다시 열어 주세요' : str(data.error); }
    catch { $('upload-result').textContent = '응답을 읽을 수 없습니다'; }
  });
  for (const event of ['error', 'timeout', 'abort']) xhr.addEventListener(event, () => { $('upload-result').textContent = '전송이 끝나지 않았습니다. 다시 시도하세요'; });
  xhr.addEventListener('loadend', () => { $('upload').disabled = false; $('upload').value = ''; $('upload-progress').hidden = true; });
  xhr.send(file);
});
poll();
