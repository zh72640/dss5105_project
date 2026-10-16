/* Session drafts are saved by the server; only IDs and pending retries are local. */
(() => {
  const key = 'sweaterco.session.v1';
  let current = null, pending = null, busy = false;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(key) || '{}'); pending = saved.pending || null; } catch { saved = {}; }
  function persist() {
    saved = {id: current?.session_id || saved.id, pending};
    localStorage.setItem(key, JSON.stringify(saved));
  }
  function controls() {
    $('session-fields').disabled = busy || !!pending || !current || current.state === 'CLOSED';
    $('session-confirm').disabled = current?.state !== 'ACTIVE';
    ['session-new', 'session-resume', 'session-resume-id'].forEach(id => $(id).disabled = busy || !!pending);
    $('session-retry').hidden = !pending;
    $('session-retry').disabled = busy;
  }
  function show(session) {
    current = session;
    $('session-resume-id').value = session.session_id;
    $('session-state').textContent = `${session.session_id} · ${session.state} · 版本 ${session.version}`;
    const d = session.draft;
    table($('session-draft'), ['当前订单', '目标', '最多工坊', '排除', '指定工坊', '硬交期'],
      [[d.order_id, d.objective || session.objective, d.num_workshop_allowed || 1, d.exclusion.join(', ') || '无', d.preferred_workshop || '无', d.deadline_required ? '是' : '否']]);
    $('session-messages').replaceChildren(...(session.messages || []).map(m => {
      const p = document.createElement('p');
      p.textContent = `${m.sequence}. ${m.role === 'user' ? '你' : '系统'}：${m.content}`;
      return p;
    }));
    const latest = session.last_response;
    if (latest) {
      const r = latest.result;
      $('session-feedback').textContent = r.message;
      table($('session-preview'), [latest.committed ? '已分配工坊' : '预览工坊', '件数', '费用', '预计天数'],
        (r.allocation || []).map(a => [a.workshop_name, a.pieces, fixed(a.estimated_cost), fixed(a.estimated_days)]));
    } else $('session-feedback').textContent = '会话已创建，请输入需求。';
    if (session.blockers.length) $('session-feedback').textContent += ' 待处理：' + session.blockers.join(', ');
    persist(); controls();
  }
  async function refresh(id) {
    const response = await fetch('/api/sessions/' + encodeURIComponent(id));
    const data = await response.json();
    if (!response.ok) throw Error(data.error || '会话读取失败');
    show(data);
  }
  async function deliver() {
    busy = true; controls();
    try {
      const response = await fetch(pending.url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(pending.body)});
      const data = await response.json();
      if (response.status >= 500) throw Error(data.result?.message || data.error || '保存暂时失败');
      pending = null; persist();
      if (data.session) {
        show(data.session);
        $('session-feedback').textContent = data.result?.message || '会话已创建，请输入需求。';
        if (data.replayed) $('session-feedback').textContent += '（已恢复上次响应）';
        const r = data.result;
        if (r) {
          table($('session-preview'), [data.committed ? '已分配工坊' : '预览工坊', '件数', '费用', '预计天数'],
            (r.allocation || []).map(a => [a.workshop_name, a.pieces, fixed(a.estimated_cost), fixed(a.estimated_days)]));
          $('audit').textContent = JSON.stringify(data, null, 2);
          $('session-message').value = '';
        } else $('session-preview').replaceChildren();
        await refresh(data.session.session_id);
        await history();
      } else {
        $('session-feedback').textContent = data.result?.message || data.error || '操作未完成';
        if (current) await refresh(current.session_id);
      }
    } catch (error) {
      $('session-feedback').textContent = error.message + (pending ? '；点击“重试上次操作”，会复用原请求。' : '；请恢复会话读取最新状态。');
    } finally { busy = false; controls(); }
  }
  $('session-new').addEventListener('click', () => {
    const id = crypto.randomUUID();
    pending = {url: '/api/sessions', body: {session_id: id, objective: $('objective').value}};
    persist(); deliver();
  });
  $('session-resume').addEventListener('click', async () => {
    busy = true; controls();
    try { await refresh($('session-resume-id').value.trim()); }
    catch (error) { $('session-feedback').textContent = error.message; }
    finally { busy = false; controls(); }
  });
  function send(action) {
    if (!current || busy || pending) return;
    const message = ['confirm', 'close'].includes(action) ? '' : $('session-message').value.trim();
    if (['message', 'replace'].includes(action) && !message) { $('session-feedback').textContent = '请先输入需求或回复。'; return; }
    pending = {url: '/api/sessions/' + encodeURIComponent(current.session_id) + '/turns',
      body: {request_id: crypto.randomUUID(), expected_version: current.version, action, message}};
    persist(); deliver();
  }
  $('session-form').addEventListener('submit', event => { event.preventDefault(); send('message'); });
  ['replace', 'confirm', 'close'].forEach(action => $('session-' + action).addEventListener('click', () => send(action)));
  $('session-retry').addEventListener('click', deliver);
  if (saved.id) refresh(saved.id).catch(error => { $('session-feedback').textContent = error.message + '；可新建会话。'; });
  if (pending) $('session-feedback').textContent = '上次操作尚未确认结果，请点击“重试上次操作”。';
  controls();
})();
