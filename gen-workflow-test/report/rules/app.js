(function () {
  var state = { data: null, cat: '', onlyPending: false, kept: {} };

  var SEV = {
    reject: { label: '拒稿线', tag: 'red' },
    fix:    { label: '必须改', tag: 'amber' },
    advise: { label: '建议',   tag: 'gray' }
  };
  var POL = { must: 'teal', must_not: 'red', may: 'blue', prefer: 'gray' };

  function el(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function renderStats() {
    var d = state.data, s = d.stats;
    var keptCount = Object.keys(state.kept).filter(function (k) { return state.kept[k]; }).length;
    var cards = [
      { label: '抽取规则', value: s.total, unit: '条', note: '来自 ' + d.source_files.length + ' 份资料' },
      { label: '保留', value: keptCount, unit: '条', note: '将写入工作流', cls: 'is-accent' },
      { label: '交付流程类', value: s.delivery_excluded, unit: '条', note: '不写入工作流', cls: '' },
      { label: '待裁决冲突', value: d.conflicts.length, unit: '处', note: '需人工确认', cls: d.conflicts.length ? 'is-danger' : 'is-accent' }
    ];
    el('stats').innerHTML = cards.map(function (c) {
      return '<div class="stat ' + (c.cls || '') + '"><label>' + esc(c.label) + '</label>'
        + '<strong>' + esc(c.value) + (c.unit ? '<span style="font-size:14px;font-weight:600;color:#9a9ba1;margin-left:2px">' + c.unit + '</span>' : '')
        + '</strong><small>' + esc(c.note) + '</small></div>';
    }).join('');
  }

  function renderAlerts() {
    var d = state.data;
    var html = '';
    html += '<div class="alert warn"><span class="alert-icon">!</span><div>'
      + '<b>这是草稿版本。</b>系统抽取可能漏项或误判归类，请逐条确认后再生成工作流。'
      + ' 标为「人工流程」的规则无法自动检查，只作提醒。</div></div>';
    if (d.conflicts.length) {
      html += '<div class="alert info"><span class="alert-icon">i</span><div>'
        + '发现 <b>' + d.conflicts.length + ' 处客户资料互相矛盾</b>。系统未做自动裁决，'
        + '请确认后在下述条目中标注处理口径。</div></div>';
    }
    el('alerts').innerHTML = html;
  }

  function renderSources() {
    var d = state.data;
    var excluded = d.excluded_files || [];
    el('srcSub').textContent = '共 ' + d.source_files.length + ' 份文件送入模型'
      + (excluded.length ? '，' + excluded.length + ' 份未采用' : '');
    var html = d.source_files.map(function (f) {
      return '<li><span class="src-name">' + esc(f.name) + '</span>'
        + '<span class="src-chars">' + (f.chars || 0).toLocaleString() + ' 字</span></li>';
    }).join('');
    if (excluded.length) {
      html += excluded.map(function (n) {
        return '<li class="is-excluded"><span class="src-name">' + esc(n) + '</span>'
          + '<span class="src-chars">未采用</span></li>';
      }).join('');
    }
    el('sources').innerHTML = html
      || '<li class="is-empty">没有记录到来源文件（数据库里缺少抽取元信息）</li>';
  }

  function renderConflicts() {
    var list = state.data.conflicts || [];
    var card = el('conflicts').closest('.section-card');
    if (!list.length) {
      if (card) card.hidden = true;
      return;
    }
    if (card) card.hidden = false;
    el('conflictCount').textContent = list.length + ' 处';
    el('conflicts').innerHTML = list.map(function (c, i) {
      return '<details class="conflict">'
        + '<summary><span class="conflict-idx">' + (i + 1) + '</span>'
        + '<strong>' + esc(c.topic) + '</strong></summary>'
        + '<div class="conflict-body">'
        + '<p>' + esc(c.detail) + '</p>'
        + '<div class="party-grid">'
        + '<div class="party"><label>口径 A</label><p>' + esc(c.party_a) + '</p>'
        + '<small>' + esc(c.from_a) + '</small></div>'
        + '<div class="party"><label>口径 B</label><p>' + esc(c.party_b) + '</p>'
        + '<small>' + esc(c.from_b) + '</small></div>'
        + '</div></div></details>';
    }).join('');
  }

  function renderRules() {
    var d = state.data;
    var list = d.rules.filter(function (r) {
      if (state.cat && r.category !== state.cat) return false;
      if (state.onlyPending && state.kept[r.id] !== false) return false;
      return true;
    });

    var byCat = {};
    list.forEach(function (r) { (byCat[r.category_label] = byCat[r.category_label] || []).push(r); });

    el('ruleSub').textContent = '显示 ' + list.length + ' / ' + d.rules.length + ' 条，取消勾选即不写入工作流';

    var html = '';
    Object.keys(byCat).forEach(function (cat) {
      html += '<div class="rule-group"><div class="rule-group-head">'
        + '<span>' + esc(cat) + '</span><em>' + byCat[cat].length + ' 条</em></div>';
      byCat[cat].forEach(function (r) {
        var keep = state.kept[r.id] !== false;
        var sev = SEV[r.severity] || SEV.advise;
        html += '<article class="rule' + (keep ? '' : ' is-off') + '" data-id="' + esc(r.id) + '">'
          + '<div class="rule-left">'
          + '<label class="rule-check"><input type="checkbox" data-keep="' + esc(r.id) + '"' + (keep ? ' checked' : '') + '></label>'
          + '</div>'
          + '<div class="rule-main">'
          + '<div class="rule-meta">'
          + '<span class="rule-id">' + esc(r.id) + '</span>'
          + '<span class="tag ' + (POL[r.polarity] || 'gray') + '">' + esc(r.polarity_label) + '</span>'
          + '<span class="tag ' + sev.tag + '">' + sev.label + '</span>'
          + '<span class="tag gray">' + esc(r.enforcement_label) + '</span>'
          + (r.scope ? '<span class="rule-scope">' + esc((r.scope || []).join('/')) + '</span>' : '')
          + '</div>'
          + '<p class="rule-statement">' + esc(r.statement) + '</p>'
          + (r.condition ? '<p class="rule-line"><b>适用</b>' + esc(r.condition) + '</p>' : '')
          + (r.scope_note ? '<p class="rule-line"><b>边界</b>' + esc(r.scope_note) + '</p>' : '')
          + (r.alternative ? '<p class="rule-line"><b>改法</b>' + esc(r.alternative) + '</p>' : '')
          + (r.examples || []).map(function (e) {
              return '<div class="rule-ex"><span class="wrong">' + esc(e.wrong) + '</span>'
                + '<span class="right">' + esc(e.right) + '</span></div>';
            }).join('')
          + (r.detect ? '<p class="rule-detect">自动检查：' + esc(r.detect.values.join('、')) + '</p>' : '')
          + '<p class="rule-evidence">出处：' + esc(r.evidence) + '</p>'
          + '</div></article>';
      });
      html += '</div>';
    });
    el('rules').innerHTML = html || '<div class="empty">没有符合条件的规则</div>';
  }

  function renderNotRules() {
    var list = state.data.not_rules || [];
    var card = el('notRules').closest('.section-card');
    if (!list.length) {
      if (card) card.hidden = true;
      return;
    }
    if (card) card.hidden = false;
    el('notRuleCount').textContent = list.length + ' 条';
    el('notRules').innerHTML = list.map(function (n) {
      return '<tr><td class="rule-text">' + esc(n.content) + '</td>'
        + '<td class="muted-cell">' + esc(n.why) + '</td></tr>';
    }).join('');
  }

  function render() {
    renderStats(); renderAlerts(); renderSources();
    renderConflicts(); renderRules(); renderNotRules();
  }

  function toast(msg) {
    var t = el('toast'); t.textContent = msg; t.classList.add('show');
    setTimeout(function () { t.classList.remove('show'); }, 2200);
  }

  var params = new URLSearchParams(location.search);

  // 先拉客户列表：有规则包的客户才可选。不能硬编码客户名，
  // 也不能依赖 localStorage（换机器/换环境就是脏数据）。
  fetch('/api/clients').then(function (r) { return r.json(); }).then(function (d) {
    var list = (d.items || []).filter(function (c) { return c.has_rules; });
    if (!list.length) {
      showNoClient();
      return;
    }
    var want = params.get('slug') || localStorage.getItem('geo_last_slug');
    state.slug = list.some(function (c) { return c.slug === want; })
      ? want : list[0].slug;
    state.clients = list;
    renderClientSelect();
    loadRules(state.slug);
  }).catch(function (e) {
    el('rules').innerHTML = '<div class="empty"><strong>连不上服务</strong>'
      + esc(e.message) + '<div style="margin-top:12px">确认服务已启动后刷新页面</div></div>';
  });

  function showNoClient() {
    el('stats').innerHTML = '';
    el('sources').innerHTML = '';
    el('conflicts').innerHTML = '';
    el('notRules').innerHTML = '';
    el('rules').innerHTML = '<div class="empty"><strong>还没有可评审的客户</strong>'
      + '客户资料上传并完成抽取后，规则包才会出现在这里。'
      + '<div style="margin-top:14px"><a class="button primary" href="./upload.html">去导入客户资料</a></div></div>';
    el('clientSelect').innerHTML = '<option>暂无客户</option>';
    el('clientSelect').disabled = true;
  }

  function renderClientSelect() {
    el('clientSelect').innerHTML = state.clients.map(function (c) {
      return '<option value="' + esc(c.slug) + '"'
        + (c.slug === state.slug ? ' selected' : '') + '>'
        + esc(c.slug) + ' · ' + c.rule_count + ' 条规则</option>';
    }).join('');
  }

  function loadRules(slug) {
    state.slug = slug;
  fetch('/api/rules/' + encodeURIComponent(slug)).then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function (data) {
    state.data = data;
    data.rules.forEach(function (r) { state.kept[r.id] = true; });
    localStorage.setItem('geo_last_slug', slug);

    el('crumbClient').textContent = data.client.short;
    el('sideStatus').textContent = data.client.short + ' · 规则包 ' + data.client.version;
    el('verText').textContent = data.client.version;

    var cats = [];
    data.rules.forEach(function (r) {
      if (cats.indexOf(r.category_label) < 0) cats.push(r.category_label);
    });
    cats.forEach(function (c) {
      var o = document.createElement('option');
      o.value = data.rules.filter(function (r) { return r.category_label === c; })[0].category;
      o.textContent = c;
      el('catFilter').appendChild(o);
    });

    render();
  }).catch(function (e) {
    el('rules').innerHTML = '<div class="empty"><strong>读取规则包失败</strong>'
      + '客户「' + esc(slug) + '」读取失败：' + esc(e.message)
      + '<div style="margin-top:14px"><a class="button small" href="./upload.html">去导入客户资料</a></div></div>';
  });
  }

  el('clientSelect').addEventListener('change', function (e) {
    localStorage.setItem('geo_last_slug', e.target.value);
    loadRules(e.target.value);
  });

  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t.dataset && t.dataset.keep) {
      state.kept[t.dataset.keep] = t.checked;
      var art = t.closest('.rule');
      if (art) art.classList.toggle('is-off', !t.checked);
      renderStats();
    }
  });

  el('catFilter').addEventListener('change', function (e) {
    state.cat = e.target.value; renderRules();
  });

  el('toggleAll').addEventListener('click', function () {
    state.onlyPending = !state.onlyPending;
    this.textContent = state.onlyPending ? '显示全部' : '只看待确认';
    renderRules();
  });

  el('buildBtn').addEventListener('click', function () {
    if (state.busy) return;
    var kept = Object.keys(state.kept).filter(function (k) { return state.kept[k]; });
    if (!kept.length) { toast('至少要保留一条规则'); return; }
    state.busy = true;
    this.disabled = true;
    this.textContent = '正在保存…';

    fetch('/api/rules/' + encodeURIComponent(state.slug) + '/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kept: state.kept })
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!x.ok) throw new Error(x.d.error || '保存失败');
        el('buildBtn').textContent = '正在生成工作流…';
        return fetch('/api/build/' + encodeURIComponent(state.slug), { method: 'POST' });
      })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!x.ok) throw new Error(x.d.error || '生成失败');
        el('buildBtn').textContent = '已生成';
        toast('工作流已生成：' + x.d.file);
        var a = document.createElement('a');
        a.className = 'button small';
        a.href = x.d.download;
        a.textContent = '下载 ' + x.d.file;
        a.style.marginLeft = '8px';
        document.querySelector('.head-actions').appendChild(a);
        el('buildBtn').disabled = false;
        el('buildBtn').textContent = '重新生成';
        state.busy = false;
      })
      .catch(function (e) {
        toast(e.message, 4000);
        el('buildBtn').disabled = false;
        el('buildBtn').textContent = '生成定制工作流';
        state.busy = false;
      });
  });

  el('exportBtn').addEventListener('click', function () {
    // 导出业务确认单（HTML 表格），不是原始 YAML
    var a = document.createElement('a');
    a.href = '/api/download/' + encodeURIComponent(state.slug) + '/rules-html';
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  });
})();
