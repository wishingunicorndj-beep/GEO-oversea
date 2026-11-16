(function () {
  var state = {
    clients: [], slug: null, batches: [], report: null,
    onlyViolate: false, busy: false
  };

  var VERDICT = {
    pass:    { label: '符合',     tag: 'teal' },
    violate: { label: '违反',     tag: 'red'  },
    unclear: { label: '无法判定', tag: 'gray' }
  };

  function el(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function pct(v) { return Math.round((v || 0) * 100) + '%'; }
  function toast(msg, ms) {
    var t = el('toast'); t.textContent = msg; t.classList.add('show');
    clearTimeout(t._t); t._t = setTimeout(function () { t.classList.remove('show'); }, ms || 2600);
  }
  function api(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
        return d;
      });
    });
  }

  /* ---------------- 路由 ---------------- */
  function route() {
    var p = new URLSearchParams(location.search);
    var slug = p.get('slug'), batch = p.get('batch');
    if (slug && batch) {
      el('listView').hidden = true;
      el('reportView').hidden = false;
      loadReport(slug, batch);
    } else {
      el('reportView').hidden = true;
      el('listView').hidden = false;
      loadClients(slug);
    }
  }

  /* ---------------- 批次列表 ---------------- */
  function loadClients(preferSlug) {
    api('/api/clients').then(function (d) {
      state.clients = (d.items || []).filter(function (c) { return c.has_rules; });
      if (!state.clients.length) {
        el('batchList').innerHTML = '<div class="empty"><strong>还没有可用客户</strong>'
          + '客户需要先生成规则包，才能做验收。<div style="margin-top:12px">'
          + '<a class="button small" href="./upload.html">去导入客户资料</a></div></div>';
        el('batchSub').textContent = '暂无客户';
        return;
      }
      var saved = localStorage.getItem('geo_report_slug');
      state.slug = preferSlug || saved || state.clients[0].slug;
      if (!state.clients.some(function (c) { return c.slug === state.slug; })) {
        state.slug = state.clients[0].slug;
      }
      renderClientSelect();
      loadBatches();
    }).catch(function (e) {
      el('batchList').innerHTML = '<div class="empty"><strong>读取客户失败</strong>' + esc(e.message)
        + '<div style="margin-top:12px">确认已运行 <code>python3 server.py</code></div></div>';
    });
  }

  function renderClientSelect() {
    el('clientSelect').innerHTML = state.clients.map(function (c) {
      return '<option value="' + esc(c.slug) + '"' + (c.slug === state.slug ? ' selected' : '') + '>'
        + esc(c.slug) + ' · ' + c.rule_count + ' 条规则</option>';
    }).join('');
  }

  function currentClient() {
    return state.clients.filter(function (c) { return c.slug === state.slug; })[0] || {};
  }

  function loadBatches() {
    var c = currentClient();
    el('sideStatus').textContent = c.slug + ' · 规则包 ' + (c.rule_version || '—');
    el('sideNote').textContent = c.rule_count + ' 条规则，' + (c.batch_count || 0) + ' 个验收批次。';
    el('crumb').innerHTML = '<span>GEO 交付</span><span class="slash">/</span>'
      + '<b>' + esc(c.slug) + '</b><span class="slash">/</span><span>验收报告</span>';

    api('/api/batches/' + encodeURIComponent(state.slug)).then(function (d) {
      state.batches = d.items || [];
      renderBatchList();
    }).catch(function (e) {
      el('batchList').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
    });
  }

  function renderBatchList() {
    var b = state.batches;
    el('batchCount').textContent = b.length + ' 个批次';
    el('batchSub').textContent = b.length
      ? '共 ' + b.length + ' 批，按时间倒序。点击查看该批次的完整报告。'
      : '该客户还没有验收批次';

    if (!b.length) {
      el('batchList').innerHTML = '<div class="empty"><strong>还没有批次</strong>'
        + '上传一次生文输出即可生成第一份报告。</div>';
      return;
    }

    el('batchList').innerHTML = b.map(function (x, i) {
      var prev = b[i + 1];
      var delta = '';
      if (prev && typeof x.violate === 'number' && typeof prev.violate === 'number') {
        var dd = x.violate - prev.violate;
        if (dd !== 0) {
          delta = '<span class="delta ' + (dd < 0 ? 'is-good' : 'is-bad') + '">'
            + (dd < 0 ? '↓' : '↑') + Math.abs(dd) + ' 处</span>';
        }
      }
      return '<a class="batch-row" href="./index.html?slug=' + encodeURIComponent(state.slug)
        + '&batch=' + encodeURIComponent(x.id) + '">'
        + '<div class="batch-main">'
        + '<div class="batch-title"><b>' + esc(x.label || x.id) + '</b>'
        + '<span class="batch-time">' + esc(x.created_at || '') + '</span></div>'
        + '<div class="batch-meta">'
        + '<span>' + (x.article_count || 0) + ' 篇</span><span class="sep">·</span>'
        + '<span>规则包 ' + esc(x.rules_version || '—') + '（' + (x.rules_count || 0) + ' 条）</span>'
        + '</div></div>'
        + '<div class="batch-nums">'
        + '<div class="num"><label>违反</label><strong class="' + (x.violate ? 'is-bad' : '') + '">'
        + (x.violate || 0) + '</strong>' + delta + '</div>'
        + '<div class="num"><label>拒稿级</label><strong class="' + (x.hard_violate ? 'is-bad' : '') + '">'
        + (x.hard_violate || 0) + '</strong></div>'
        + '<div class="num"><label>合格率</label><strong class="is-good">'
        + (x.pass_rate != null ? x.pass_rate + '%' : '—') + '</strong></div>'
        + '<span class="row-actions">'
        + '<button class="button small batch-export" data-batch="' + esc(x.id) + '" data-fmt="pdf" '
        + 'title="导出 PDF，可直接发给业务">PDF</button>'
        + '<button class="button small batch-export" data-batch="' + esc(x.id) + '" data-fmt="html" '
        + 'title="导出单文件 HTML，双击即可查看">HTML</button>'
        + '</span>'
        + '</div></a>';
    }).join('');
  }

  /* ---------------- 报告详情 ---------------- */
  function loadReport(slug, batch) {
    el('stats').innerHTML = '<div class="stat"><label>加载中…</label></div>';
    api('/api/batch/' + encodeURIComponent(slug) + '/' + encodeURIComponent(batch))
      .then(function (rep) {
        state.report = rep;
        state.slug = slug;
        renderReport();
      })
      .catch(function (e) {
        el('rows').innerHTML = '<tr><td colspan="4"><div class="empty"><strong>读取报告失败</strong>'
          + esc(e.message) + '</div></td></tr>';
      });
  }

  function renderReport() {
    var d = state.report;
    el('rTitle').textContent = d.batch_label || d.batch_id || '验收报告';
    el('rSub').textContent = (d.client_short || d.client || '')
      + ' · ' + (d.article_count || 0) + ' 篇 · 规则包 ' + (d.rules_version || '—')
      + ' · 评估于 ' + (d.evaluated_at || '');
    el('topActions').innerHTML = '<span class="storage-indicator"><span></span>报告已生成</span>';
    el('sideStatus').textContent = (d.client_short || state.slug) + ' · ' + (d.rules_version || '');
    el('sideNote').textContent = '本批次已保存规则包快照，规则包后续变更不影响本报告。';
    el('crumb').innerHTML = '<span>GEO 交付</span><span class="slash">/</span>'
      + '<a class="crumb-link" href="./index.html?slug=' + encodeURIComponent(state.slug) + '">'
      + esc(d.client_short || state.slug) + '</a>'
      + '<span class="slash">/</span><b>验收报告</b>';
    el('rFoot').textContent = '判定「无法判定」表示该规则需模型判定但未执行，或模型给出的证据句无法在原文中逐字定位。'
      + ' 本报告基于规则包快照 ' + (d.rules_version || '—') + '，之后的规则变更不影响本批次结论。';

    renderStats(); renderAlerts(); renderMetrics(); renderRows(); renderSkipped();
  }

  function renderStats() {
    var s = state.report.summary || {};
    var violated = (state.report.articles || []).filter(function (a) {
      return (a.rows || []).some(function (r) { return r.verdict === 'violate'; });
    }).length;
    var cards = [
      { label: '本批文章', value: state.report.article_count || 0, unit: '篇', note: '同一批次产出' },
      { label: '判定违反', value: s.violate || 0, unit: '处', note: violated + ' 篇存在违规', cls: s.violate ? 'is-danger' : 'is-accent' },
      { label: '其中拒稿级', value: s.hard_violate || 0, unit: '处', note: '客户标为拒稿线', cls: s.hard_violate ? 'is-danger' : 'is-accent' },
      { label: '已判定合格率', value: (s.pass_rate_of_judged != null ? s.pass_rate_of_judged : 0) + '%', unit: '', note: '已判定 ' + (s.judged || 0) + ' / ' + (s.total || 0) + ' 项', cls: 'is-accent' }
    ];
    el('stats').innerHTML = cards.map(function (c) {
      return '<div class="stat ' + (c.cls || '') + '"><label>' + esc(c.label) + '</label>'
        + '<strong>' + esc(c.value) + (c.unit ? '<span style="font-size:14px;font-weight:600;color:#9a9ba1;margin-left:2px">' + c.unit + '</span>' : '')
        + '</strong><small>' + esc(c.note) + '</small></div>';
    }).join('');
  }

  function renderAlerts() {
    var s = state.report.summary || {};
    var html = '';
    if (s.unclear > 0) {
      html += '<div class="alert warn"><span class="alert-icon">!</span><div>'
        + '<b>' + s.unclear + ' 项（' + Math.round(s.unclear / (s.total || 1) * 100) + '%）未得出判定。</b>'
        + ' 多为需外部资料佐证的规则，或模型给出的证据句无法在原文定位。</div></div>';
    }
    if (s.violate > 0) {
      html += '<div class="alert info"><span class="alert-icon">i</span><div>'
        + '已确认 <b>' + s.violate + ' 处违反</b>，证据句均可在原文中逐字检索。</div></div>';
    }
    el('alerts').innerHTML = html;
  }

  function renderMetrics() {
    var d = state.report.dedup || {};
    var items = [
      { label: '不同标题核心', value: (d.title_distinct || 0) + ' / ' + (d.article_count || 0), note: '标题骨架唯一度' },
      { label: 'H2 主题重合（最高）', value: pct(d.h2_overlap_max), note: '平均 ' + pct(d.h2_overlap_avg), warn: (d.h2_overlap_max || 0) >= 0.7 },
      { label: '跨篇句子复用率', value: pct(d.sentence_reuse_ratio), note: '逐字重复的句子占比' },
      { label: '正文相似度（最高）', value: pct(d.body_similarity_max), note: '平均 ' + pct(d.body_similarity_avg) }
    ];
    el('metrics').innerHTML = items.map(function (m) {
      return '<div class="metric ' + (m.warn ? 'is-warn' : '') + '"><label>' + esc(m.label) + '</label>'
        + '<strong>' + esc(m.value) + '</strong><small>' + esc(m.note) + '</small></div>';
    }).join('');
    var w = d.warnings || [];
    el('dedupWarn').innerHTML = w.length
      ? '<ul class="warn-list">' + w.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>'
      : '';
  }

  function renderRows() {
    var arts = state.report.articles || [];
    var blocks = [];

    arts.forEach(function (a) {
      var all = a.rows || [];
      var bad = all.filter(function (r) { return r.verdict === 'violate'; });
      var unclear = all.filter(function (r) { return r.verdict === 'unclear'; });
      var list = state.onlyViolate ? bad : all;
      if (!list.length) return;

      // 默认展开：有违规的篇目；全部合规时折叠，避免一次铺开几百行
      var open = bad.length > 0 || state.onlyViolate;

      var rows = list.map(function (r) {
        var v = VERDICT[r.verdict] || VERDICT.unclear;
        var ev = r.evidence
          ? '<div class="evidence">' + esc(r.evidence) + '</div>'
          : '<span class="evidence empty">—</span>';
        if (r.verdict === 'unclear' && r.reason) ev += '<span class="reason-note">' + esc(r.reason) + '</span>';
        return '<tr><td><span class="rule-id">' + esc(r.rule_id) + '</span>'
          + '<div class="rule-text">' + esc(r.statement) + '</div></td>'
          + '<td class="col-cat"><span class="tag gray">' + esc(r.category_label || '其他') + '</span></td>'
          + '<td class="col-state"><span class="tag ' + v.tag + '">' + v.label + '</span></td>'
          + '<td>' + ev + '</td></tr>';
      }).join('');

      var badges = '<span class="tag teal">' + (all.length - bad.length - unclear.length) + ' 符合</span>';
      if (bad.length) badges += '<span class="tag red">' + bad.length + ' 违反</span>';
      if (unclear.length) badges += '<span class="tag gray">' + unclear.length + ' 未判定</span>';

      blocks.push('<details class="article-block' + (bad.length ? ' has-issue' : '') + '"'
        + (open ? ' open' : '') + '>'
        + '<summary>'
        + '<span class="art-idx">第 ' + (a.index + 1) + ' 篇</span>'
        + '<span class="art-title">' + esc(a.title) + '</span>'
        + '<span class="art-badges">' + badges + '</span>'
        + '</summary>'
        + '<div class="table-wrap"><table>'
        + '<thead><tr><th>客户要求</th><th class="col-cat">类别</th><th class="col-state">判定</th><th>证据（原文）</th></tr></thead>'
        + '<tbody>' + rows + '</tbody></table></div>'
        + '</details>');
    });

    el('rows').innerHTML = blocks.join('') || '<div class="empty">没有符合条件的条目</div>';
    el('tableSub').textContent = state.onlyViolate
      ? '仅显示判定违反的条目'
      : '共 ' + arts.length + ' 篇，点击篇名展开逐条判定';
  }

  function renderSkipped() {
    var sk = state.report.skipped || [];
    el('skipCount').textContent = sk.length + ' 条';
    el('skipRows').innerHTML = sk.map(function (s) {
      var tag = (s.why || '').indexOf('may') >= 0 || (s.why || '').indexOf('prefer') >= 0 ? 'blue' : 'gray';
      return '<tr><td><span class="rule-id">' + esc(s.id) + '</span></td>'
        + '<td class="rule-text">' + esc(s.statement) + '</td>'
        + '<td class="col-state"><span class="tag ' + tag + '">'
        + esc((s.why || '').replace(' 类不进合格率', '')) + '</span></td></tr>';
    }).join('');
  }

  /* ---------------- 任务轮询 ---------------- */
  function pollTask(taskId, onTick) {
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
            if (onTick) onTick(t);
            if (t.status === 'done') { resolve(t.result || {}); return; }
            if (t.status === 'failed') { reject(new Error(t.error || '任务失败')); return; }
            setTimeout(tick, 2500);
          })
          .catch(function (e) {
            failCount++;
            if (failCount >= 4) { reject(e); return; }
            setTimeout(tick, 4000);
          });
      }
      tick();
    });
  }

  /* ---------------- 新建批次 ---------------- */
  function openModal() {
    var c = currentClient();
    el('modalClient').textContent = '将为「' + c.slug + '」生成报告，并保存本次使用的规则包快照。';
    el('ruleHint').textContent = '将使用规则包 ' + (c.rule_version || '—')
      + '（' + c.rule_count + ' 条）。报告生成后规则包再改也不影响本批次。';
    el('batchLabel').value = '';
    el('batchText').value = '';
    el('batchFile').value = '';
    setPasteHint('粘贴标题和正文即可，也支持 Dify 的 JSON', 'stale');
    el('modalOk').disabled = false;
    el('modalOk').textContent = '开始评估';
    el('modalProgress').hidden = true;
    el('modalFill').style.width = '0';
    el('batchModal').showModal();
  }

  /* 粘贴框的即时反馈：JSON 和「标题+正文」两种输入都能识别 */
  function setPasteHint(text, kind) {
    var h = el('pasteHint');
    h.textContent = text;
    h.className = 'paste-hint' + (kind ? ' is-' + kind : '');
  }

  /* 与后端 articles_from_plain_text 保持一致的分篇规则 */
  function splitPlain(text) {
    text = String(text).replace(/\r\n?/g, '\n').trim();
    if (!text) return [];
    var chunks = [], buf = [];
    function flush() {
      if (buf.join('\n').trim()) chunks.push(buf.join('\n'));
      buf = [];
    }
    text.split('\n').forEach(function (line) {
      var s = line.trim();
      if (/^[=\-*]{3,}$/.test(s)) { flush(); return; }
      if (/^#{1,2}\s+\S/.test(s)) { flush(); }
      buf.push(line);
    });
    flush();

    var out = [];
    chunks.forEach(function (chunk) {
      var lines = chunk.trim().split('\n');
      while (lines.length && !lines[0].trim()) lines.shift();
      if (!lines.length) return;
      var head = lines[0].trim().replace(/^#{1,6}\s*/, '').replace(/^[*_]+|[*_]+$/g, '').trim();
      var rest = lines.slice(1).join('\n').trim();
      if (rest && head.length > 0 && head.length <= 80 && head.indexOf('\n') < 0
          && head.indexOf('http') !== 0 && head.charAt(0) !== '<') {
        out.push({ title: head, content: rest });
      } else if (chunk.trim()) {
        out.push({ title: '', content: chunk.trim() });
      }
    });
    return out.filter(function (a) { return a.content.trim(); });
  }

  function sizeLabel(n) {
    return n < 1024 ? Math.max(1, Math.round(n / 102.4) / 10) + ' KB'
                    : Math.round(n / 1024) + ' KB';
  }

  function checkPaste() {
    var raw = el('batchText').value.trim();
    if (!raw) {
      setPasteHint('粘贴标题和正文即可，也支持 Dify 的 JSON', 'stale');
      return;
    }

    if (raw.charAt(0) === '{' || raw.charAt(0) === '[') {
      var d;
      try {
        d = JSON.parse(raw);
      } catch (e) {
        setPasteHint('JSON 还不完整：' + e.message, 'bad');
        return;
      }
      var arts = d && (d.generated_articles_list || d.articles);
      if (!Array.isArray(arts) || !arts.length) {
        setPasteHint('JSON 能解析，但找不到 generated_articles_list 数组', 'bad');
        return;
      }
      setPasteHint('已识别 JSON · ' + arts.length + ' 篇 · ' + sizeLabel(raw.length), 'good');
      return;
    }

    var list = splitPlain(raw);
    if (!list.length) {
      setPasteHint('没识别出文章内容', 'bad');
      return;
    }
    var named = list.filter(function (a) { return a.title; }).length;
    var msg = '已识别 ' + list.length + ' 篇 · ' + sizeLabel(raw.length);
    if (named < list.length) msg += '（' + (list.length - named) + ' 篇没识别到标题，将只按正文判定）';
    setPasteHint(msg, named < list.length ? 'warn' : 'good');
  }

  function submitBatch() {
    if (state.busy) return;
    var pasted = el('batchText').value.trim();
    var file = el('batchFile').files && el('batchFile').files[0];
    if (!pasted && !file) { toast('请粘贴生文输出 JSON，或选择一个 JSON 文件'); return; }
    state.busy = true;
    el('modalOk').disabled = true;
    el('modalOk').textContent = '上传中…';

    var fd = new FormData();
    fd.append('slug', state.slug);
    fd.append('label', el('batchLabel').value.trim());
    if (pasted) fd.append('text', pasted);
    else fd.append('file', file, file.name);

    el('modalOk').textContent = '上传中…';
    el('modalProgress').hidden = false;
    el('modalFill').style.width = '5%';
    el('modalStep').textContent = '正在上传文件…';

    api('/api/evaluate', { method: 'POST', body: fd })
      .then(function (d) {
        // 异步任务：轮询进度，进度条与步骤文字实时更新
        return pollTask(d.task_id, function (t) {
          el('modalFill').style.width = (t.progress || 5) + '%';
          el('modalStep').textContent = t.step || '处理中…';
          el('modalOk').textContent = '评估中 ' + (t.progress || 0) + '%';
        });
      })
      .then(function (result) {
        el('batchModal').close();
        toast('报告已生成', 3000);
        window.location.href = './index.html?slug=' + encodeURIComponent(state.slug)
          + '&batch=' + encodeURIComponent(result.batch_id);
      })
      .catch(function (e) {
        toast(e.message, 5000);
        el('modalOk').disabled = false;
        el('modalOk').textContent = '开始评估';
        state.busy = false;
      });
  }

  /* ---------------- 事件 ---------------- */
  el('clientSelect').addEventListener('change', function (e) {
    state.slug = e.target.value;
    localStorage.setItem('geo_report_slug', state.slug);
    loadBatches();
  });

  el('newBatchBtn').addEventListener('click', openModal);

  document.addEventListener('click', function (e) {
    var b = e.target.closest('.batch-export');
    if (!b) return;
    e.preventDefault();
    e.stopPropagation();
    download(b.dataset.batch, b.dataset.fmt === 'html' ? 'html' : 'pdf');
  });
  el('modalCancel').addEventListener('click', function () { el('batchModal').close(); });
  el('modalOk').addEventListener('click', submitBatch);

  el('batchText').addEventListener('input', checkPaste);
  el('batchPick').addEventListener('click', function () { el('batchFile').click(); });
  el('batchFile').addEventListener('change', function (e) {
    var f = e.target.files && e.target.files[0];
    if (!f) return;
    var reader = new FileReader();
    reader.onload = function () {
      el('batchText').value = String(reader.result || '');
      checkPaste();
    };
    reader.onerror = function () { toast('这个文件读不出来，试试直接粘贴内容'); };
    reader.readAsText(f, 'utf-8');
  });

  el('backBtn').addEventListener('click', function () {
    window.location.href = './index.html?slug=' + encodeURIComponent(state.slug);
  });

  function download(bid, fmt) {
    var url = '/api/board/' + encodeURIComponent(state.slug) + '/' + encodeURIComponent(bid)
      + (fmt === 'pdf' ? '?format=pdf' : '');
    toast(fmt === 'pdf' ? '正在生成 PDF…' : '正在生成看板…', 2000);
    var a = document.createElement('a');
    a.href = url;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  el('mdBtn').addEventListener('click', function () {
    if (!state.report) return;
    download(state.report.batch_id, 'pdf');
  });

  el('htmlBtn').addEventListener('click', function () {
    if (!state.report) return;
    download(state.report.batch_id, 'html');
  });

  el('onlyViolate').addEventListener('change', function (e) {
    state.onlyViolate = e.target.checked;
    if (state.report) renderRows();
  });

  el('expandAll').addEventListener('click', function () {
    var blocks = document.querySelectorAll('.article-block');
    if (!blocks.length) return;
    var anyClosed = Array.prototype.some.call(blocks, function (b) { return !b.open; });
    Array.prototype.forEach.call(blocks, function (b) { b.open = anyClosed; });
    this.textContent = anyClosed ? '全部收起' : '全部展开';
  });

  window.addEventListener('popstate', route);
  route();
})();
