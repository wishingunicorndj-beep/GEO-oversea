(function () {
  var state = { data: null, onlyViolate: false };

  var VERDICT = {
    pass:    { label: '符合',     tag: 'teal'  },
    violate: { label: '违反',     tag: 'red'   },
    unclear: { label: '无法判定', tag: 'gray'  }
  };

  function el(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function pct(v) { return Math.round(v * 100) + '%'; }

  /* ---------------- 统计卡 ---------------- */
  function renderStats() {
    var d = state.data, s = d.summary;
    var violatedArticles = d.articles.filter(function (a) {
      return a.rows.some(function (r) { return r.verdict === 'violate'; });
    }).length;

    var cards = [
      { label: '本批文章', value: d.article_count, unit: '篇', note: '同一词包批量产出' },
      { label: '判定违反', value: s.violate, unit: '处', note: violatedArticles + ' 篇存在违规', cls: s.violate ? 'is-danger' : 'is-accent' },
      { label: '其中拒稿级', value: s.hard_violate, unit: '处', note: '客户标为拒稿线的规则', cls: s.hard_violate ? 'is-danger' : 'is-accent' },
      { label: '已判定合格率', value: s.pass_rate_of_judged + '%', unit: '', note: '已判定 ' + s.judged + ' / ' + s.total + ' 项', cls: 'is-accent' }
    ];

    el('stats').innerHTML = cards.map(function (c) {
      return '<div class="stat ' + (c.cls || '') + '">'
        + '<label>' + esc(c.label) + '</label>'
        + '<strong>' + esc(c.value) + (c.unit ? '<span style="font-size:14px;font-weight:600;color:#9a9ba1;margin-left:2px">' + c.unit + '</span>' : '') + '</strong>'
        + '<small>' + esc(c.note) + '</small></div>';
    }).join('');
  }

  /* ---------------- 顶部提示 ---------------- */
  function renderAlerts() {
    var d = state.data, s = d.summary;
    var html = '';

    if (s.unclear > 0) {
      var ratio = Math.round(s.unclear / s.total * 100);
      html += '<div class="alert warn">'
        + '<span class="alert-icon">!</span>'
        + '<div><b>' + s.unclear + ' 项（' + ratio + '%）尚未得出判定。</b>'
        + ' 这部分需要模型逐条核验，当前报告只覆盖了代码可确定性检查的规则。'
        + ' 在补齐模型判定前，请勿据此认定整批质量合格。</div></div>';
    }

    if (s.violate > 0) {
      html += '<div class="alert info">'
        + '<span class="alert-icon">i</span>'
        + '<div>已确认 <b>' + s.violate + ' 处违反</b>，证据句均可在原文中逐字检索。'
        + ' 建议按文章返修后再进入人工复核环节。</div></div>';
    }

    el('alerts').innerHTML = html;
  }

  /* ---------------- 重复度 ---------------- */
  function renderMetrics() {
    var d = state.data.dedup;
    var items = [
      { label: '不同标题核心', value: d.title_distinct + ' / ' + d.article_count, note: '标题骨架唯一度' },
      { label: 'H2 主题重合（最高）', value: pct(d.h2_overlap_max), note: '平均 ' + pct(d.h2_overlap_avg), warn: d.h2_overlap_max >= 0.7 },
      { label: '跨篇句子复用率', value: pct(d.sentence_reuse_ratio), note: '逐字重复的句子占比' },
      { label: '正文相似度（最高）', value: pct(d.body_similarity_max), note: '平均 ' + pct(d.body_similarity_avg) }
    ];

    el('metrics').innerHTML = items.map(function (m) {
      return '<div class="metric ' + (m.warn ? 'is-warn' : '') + '">'
        + '<label>' + esc(m.label) + '</label>'
        + '<strong>' + esc(m.value) + '</strong>'
        + '<small>' + esc(m.note) + '</small></div>';
    }).join('');

    var w = d.warnings || [];
    el('dedupWarn').innerHTML = w.length
      ? '<ul class="warn-list">' + w.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>'
      : '';
  }

  /* ---------------- 逐条判定 ---------------- */
  function renderRows() {
    var d = state.data;
    var rows = [];

    d.articles.forEach(function (a) {
      var list = state.onlyViolate
        ? a.rows.filter(function (r) { return r.verdict === 'violate'; })
        : a.rows;
      if (!list.length) return;

      rows.push('<tr class="group-row"><td colspan="4"><b>第 ' + (a.index + 1) + ' 篇</b> · '
        + esc(a.title) + '</td></tr>');

      list.forEach(function (r) {
        var v = VERDICT[r.verdict] || VERDICT.unclear;
        var ev = r.evidence
          ? '<div class="evidence">' + esc(r.evidence) + '</div>'
          : '<span class="evidence empty">—</span>';
        if (r.verdict === 'unclear' && r.reason) {
          ev += '<span class="reason-note">' + esc(r.reason) + '</span>';
        }
        rows.push('<tr>'
          + '<td><span class="rule-id">' + esc(r.rule_id) + '</span>'
          + '<div class="rule-text">' + esc(r.statement) + '</div></td>'
          + '<td class="col-cat"><span class="tag gray">' + esc(r.category_label || '其他') + '</span></td>'
          + '<td class="col-state"><span class="tag ' + v.tag + '">' + v.label + '</span></td>'
          + '<td>' + ev + '</td></tr>');
      });
    });

    el('rows').innerHTML = rows.join('');
    el('tableSub').textContent = state.onlyViolate
      ? '仅显示判定违反的条目'
      : '共 ' + d.articles.length + ' 篇 × 每条规则逐项核验';
  }

  /* ---------------- 跳过项 ---------------- */
  function renderSkipped() {
    var sk = state.data.skipped || [];
    el('skipCount').textContent = sk.length + ' 条';
    el('skipRows').innerHTML = sk.map(function (s) {
      var tag = s.why.indexOf('may') >= 0 || s.why.indexOf('prefer') >= 0 ? 'blue' : 'gray';
      return '<tr>'
        + '<td><span class="rule-id">' + esc(s.id) + '</span></td>'
        + '<td class="rule-text">' + esc(s.statement) + '</td>'
        + '<td class="col-state"><span class="tag ' + tag + '">' + esc(s.why.replace(' 类不进合格率', '')) + '</span></td>'
        + '</tr>';
    }).join('');
  }

  function render() {
    renderStats();
    renderAlerts();
    renderMetrics();
    renderRows();
    renderSkipped();
  }

  function toast(msg) {
    var t = el('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(function () { t.classList.remove('show'); }, 2000);
  }

  /* ---------------- 启动 ---------------- */
  fetch('./data.json')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      state.data = data;
      render();
    })
    .catch(function () {
      el('rows').innerHTML = '<tr><td colspan="4">'
        + '<div style="text-align:center;padding:40px 20px;color:#9a9ba1">'
        + '<div style="font-size:15px;color:#6f7076;margin-bottom:6px">报告数据未加载</div>'
        + '<div style="font-size:12px">请确认 report/data.json 与页面在同一目录下，并通过本地服务访问（file:// 无法读取 JSON）。</div>'
        + '</div></td></tr>';
    });

  el('onlyViolate').addEventListener('change', function (e) {
    state.onlyViolate = e.target.checked;
    if (state.data) renderRows();
  });

  document.querySelectorAll('.head-actions .button, .top-actions .button').forEach(function (b) {
    b.addEventListener('click', function () { toast('该操作需接入后端服务'); });
  });
})();
