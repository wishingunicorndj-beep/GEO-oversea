(function () {
  var files = [];
  var busy = false;
  var state = { lastLog: '' };
  var ALLOWED = ['.docx', '.xlsx', '.txt', '.md', '.csv', '.pdf'];

  function el(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function toast(msg, ms) {
    var t = el('toast'); t.textContent = msg; t.classList.add('show');
    clearTimeout(t._timer);
    t._timer = setTimeout(function () { t.classList.remove('show'); }, ms || 2400);
  }
  function size(n) {
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(0) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }
  function setStep(n) {
    document.querySelectorAll('.step').forEach(function (s) {
      var i = Number(s.dataset.step);
      s.classList.toggle('is-active', i === n);
      s.classList.toggle('is-done', i < n);
    });
  }

  /* ---------------- 服务状态 ---------------- */
  function checkService() {
    fetch('/api/status').then(function (r) { return r.json(); }).then(function (d) {
      el('svcDot').style.background = 'var(--ui-accent)';
      el('svcText').textContent = '服务运行中';
      var ok = d.model_config_ok;
      el('cfgBadge').innerHTML = '<span></span>' + (ok ? '模型已配置' : '模型未配置');
      el('cfgBadge').style.background = ok ? 'var(--ui-accent-soft)' : 'var(--ui-warn-tag-bg)';
      el('cfgBadge').style.color = ok ? 'var(--ui-accent-ink)' : 'var(--ui-warn-strong)';
      if (!ok) {
        el('alerts').innerHTML = '<div class="alert warn"><span class="alert-icon">!</span><div>'
          + '<b>模型配置未找到。</b>抽取依赖模型，请确认 <code>' + esc(d.model_config || 'nano.local.json')
          + '</code> 存在后再提交。</div></div>';
      }
    }).catch(function () {
      el('svcDot').style.background = 'var(--ui-danger)';
      el('svcText').textContent = '服务未启动';
      el('cfgBadge').innerHTML = '<span></span>离线';
      el('alerts').innerHTML = '<div class="alert warn"><span class="alert-icon">!</span><div>'
        + '<b>没有连上本地服务。</b>请先运行 <code>python3 server.py</code>，'
        + '然后通过 http://127.0.0.1:8901/upload.html 打开本页。</div></div>';
    });
  }

  /* ---------------- 文件 ---------------- */
  function addFiles(list) {
    Array.prototype.forEach.call(list, function (f) {
      var ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase();
      if (ALLOWED.indexOf(ext) < 0) { toast('不支持 ' + ext + ' 格式'); return; }
      if (files.some(function (x) { return x.name === f.name && x.size === f.size; })) return;
      files.push(f);
    });
    renderFiles();
  }

  function renderFiles() {
    el('fileCount').textContent = files.length + ' 个文件';
    el('fileList').innerHTML = files.map(function (f, i) {
      return '<li><span class="file-ext">' + esc(f.name.slice(f.name.lastIndexOf('.') + 1).toUpperCase()) + '</span>'
        + '<span class="file-name">' + esc(f.name) + '</span>'
        + '<span class="file-size">' + size(f.size) + '</span>'
        + '<button class="file-remove" data-i="' + i + '" aria-label="移除">×</button></li>';
    }).join('');
    updateSubmit();
  }

  function updateSubmit() {
    var ok = files.length > 0
      && /^[a-z0-9_]{2,40}$/.test(el('slug').value.trim())
      && el('name').value.trim() && el('short').value.trim()
      && !busy;
    // 不用 disabled：禁用的按钮点不动也不给提示，用户不知道为什么没反应。
    // 改为视觉弱化 + 点击时逐项说明缺什么。
    el('submitBtn').setAttribute('aria-disabled', ok ? 'false' : 'true');
    el('submitBtn').classList.toggle('is-incomplete', !ok);
  }

  /* ---------------- 提交 ---------------- */
  function appendLog(text) {
    var box = el('log');
    box.textContent += text + '\n';
    box.scrollTop = box.scrollHeight;
  }

  /* ---------------- 任务轮询 ---------------- */
  var pollTimer = null;

  function pollTask(taskId) {
    return new Promise(function (resolve, reject) {
      var failCount = 0;
      function tick() {
        fetch('/api/task/' + encodeURIComponent(taskId))
          .then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
          })
          .then(function (t) {
            failCount = 0;
            if (t.step) el('progressTitle').textContent = t.step;
            if (typeof t.progress === 'number') {
              el('progressFill').style.width = t.progress + '%';
            }
            if (t.log && t.log !== state.lastLog) {
              state.lastLog = t.log;
              appendLog(t.log);
            }
            if (t.status === 'done') { resolve(t.result || {}); return; }
            if (t.status === 'failed') { reject(new Error(t.error || '任务失败')); return; }
            pollTimer = setTimeout(tick, 2500);
          })
          .catch(function (e) {
            // 偶发网络抖动不要立刻判死，连续失败 4 次才放弃
            failCount++;
            if (failCount >= 4) { reject(e); return; }
            pollTimer = setTimeout(tick, 4000);
          });
      }
      tick();
    });
  }

  // 刷新后自动续上未完成的任务
  function resumeTask() {
    var tid = localStorage.getItem('geo_task');
    if (!tid) return false;
    var slug = localStorage.getItem('geo_task_slug');
    if (slug) el('slug').value = slug;
    setStep(3);
    el('progressCard').hidden = false;
    el('progressTitle').textContent = '恢复上次任务…';
    el('progressSub').textContent = '任务 ' + tid;
    busy = true;
    updateSubmit();
    pollTask(tid).then(function (result) {
      el('progressTitle').textContent = '抽取完成';
      el('progressFill').style.width = '100%';
      localStorage.removeItem('geo_task');
      setTimeout(function () {
        window.location.href = './rules/index.html?slug=' + encodeURIComponent(el('slug').value.trim());
      }, 800);
    }).catch(function (e) {
      appendLog('恢复失败：' + e.message);
      localStorage.removeItem('geo_task');
      busy = false;
      updateSubmit();
    });
    return true;
  }

  function submit() {
    busy = true;
    updateSubmit();
    setStep(3);
    el('progressCard').hidden = false;
    el('progressTitle').textContent = '正在上传资料';
    el('progressSub').textContent = files.length + ' 个文件';
    el('progressFill').style.width = '12%';
    el('log').textContent = '';

    var fd = new FormData();
    fd.append('slug', el('slug').value.trim());
    fd.append('name', el('name').value.trim());
    fd.append('short', el('short').value.trim());
    files.forEach(function (f) { fd.append('files', f, f.name); });

    localStorage.setItem('geo_last_slug', el('slug').value.trim());

    fetch('/api/upload', { method: 'POST', body: fd })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!x.ok) throw new Error(x.d.error || '上传失败');
        appendLog('已上传 ' + x.d.saved.length + ' 个文件');
        (x.d.skipped || []).forEach(function (s) {
          appendLog('跳过 ' + s.file + '：' + s.why);
        });
        el('progressTitle').textContent = '正在抽取写作规则';
        el('progressSub').textContent = '模型读取全部资料，约 3-6 分钟';
        el('progressFill').style.width = '35%';
        appendLog('开始抽取，请稍候…');
        return fetch('/api/extract', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ slug: el('slug').value.trim() })
        }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); });
      })
      .then(function (x) {
        if (!x.ok) throw new Error(x.d.error || '抽取启动失败');
        // 抽像是异步任务：拿到 task_id 后轮询进度
        appendLog('任务已启动，开始轮询进度…');
        localStorage.setItem('geo_task', x.d.task_id);
        localStorage.setItem('geo_task_slug', el('slug').value.trim());
        return pollTask(x.d.task_id);
      })
      .then(function (result) {
        el('progressFill').style.width = '100%';
        el('progressTitle').textContent = '抽取完成';
        el('progressSub').textContent = (result.rule_count || 0) + ' 条规则，即将进入评审';
        appendLog(result.log || '');
        localStorage.removeItem('geo_task');
        toast('规则抽取完成，正在跳转');
        setTimeout(function () {
          window.location.href = './rules/index.html?slug=' + encodeURIComponent(el('slug').value.trim());
        }, 900);
      })
      .catch(function (e) {
        el('progressTitle').textContent = '出错了';
        el('progressSub').textContent = '请检查下方信息';
        appendLog('错误：' + e.message);
        toast(e.message, 4000);
        busy = false;
        updateSubmit();
      });
  }

  /* ---------------- 表单持久化 ---------------- */
  var FORM_KEY = 'geo_upload_form';
  function saveForm() {
    try {
      localStorage.setItem(FORM_KEY, JSON.stringify({
        slug: el('slug').value, short: el('short').value, name: el('name').value
      }));
    } catch (e) {}
  }
  function restoreForm() {
    try {
      var d = JSON.parse(localStorage.getItem(FORM_KEY) || '{}');
      if (d.slug) el('slug').value = d.slug;
      if (d.short) el('short').value = d.short;
      if (d.name) el('name').value = d.name;
      if (d.slug) localStorage.setItem('geo_last_slug', d.slug);
    } catch (e) {}
  }

  /* ---------------- 事件 ---------------- */
  var dz = el('dropzone');
  dz.addEventListener('click', function () { el('fileInput').click(); });
  dz.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el('fileInput').click(); }
  });
  el('fileInput').addEventListener('change', function (e) { addFiles(e.target.files); e.target.value = ''; });

  ['dragenter', 'dragover'].forEach(function (ev) {
    dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add('is-over'); });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove('is-over'); });
  });
  dz.addEventListener('drop', function (e) {
    if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
  });

  document.addEventListener('click', function (e) {
    var b = e.target.closest('.file-remove');
    if (b) { files.splice(Number(b.dataset.i), 1); renderFiles(); }
  });

  ['slug', 'short', 'name'].forEach(function (id) {
    el(id).addEventListener('input', function () {
      setStep(files.length ? 2 : 1);
      saveForm();
      updateSubmit();
    });
  });

  el('submitBtn').addEventListener('click', function () {
    if (files.length === 0) { toast('请先选择客户资料文件'); return; }
    var slug = el('slug').value.trim();
    if (!/^[a-z0-9_]{2,40}$/.test(slug)) { toast('客户标识需用小写字母、数字、下划线，2-40 位'); el('slug').focus(); return; }
    if (!el('short').value.trim()) { toast('请填写客户简称'); el('short').focus(); return; }
    if (!el('name').value.trim()) { toast('请填写客户全称'); el('name').focus(); return; }
    submit();
  });
  el('resetBtn').addEventListener('click', function () {
    files = []; renderFiles(); el('log').textContent = '';
    el('progressCard').hidden = true; setStep(1);
  });

  restoreForm();
  checkService();
  resumeTask();
  updateSubmit();
})();
