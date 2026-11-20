(function () {
  var state = { data: null, cat: '', onlyPending: false, kept: {}, openEditor: null, busy: false, openConflicts: {} };

  var SEV = {
    reject: { label: '拒稿线', tag: 'red' },
    fix:    { label: '必须改', tag: 'amber' },
    advise: { label: '建议',   tag: 'gray' }
  };
  var POL = { must: 'teal', must_not: 'red', may: 'blue', prefer: 'gray' };
  var POL_LABEL = { must: '必须', must_not: '不得', may: '允许', prefer: '建议' };
  var CATS = [
    ['identity', '实体称谓'], ['fact', '事实口径'], ['prohibition', '禁止事项'],
    ['stance', '自我定位'], ['scope', '业务边界'], ['voice', '口吻体裁'],
    ['structure', '文章结构'], ['citation', '数据引用'], ['delivery', '交付流程']
  ];
  var DECISION_LABEL = {
    accept_a: '采用口径 A', accept_b: '采用口径 B',
    custom: '自定义口径', dismissed: '已删除（判定为不成立）'
  };

  function el(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function activeRules() {
    return (state.data.rules || []).filter(function (r) { return r.status !== 'dismissed'; });
  }
  function dismissedRules() {
    return state.data.dismissed_rules || [];
  }
  function conflictRes(c) { return (c && c.resolution) || {}; }

  function renderStats() {
    var d = state.data, s = d.stats || {};
    var active = activeRules().length;
    var pending = d.conflicts_pending != null ? d.conflicts_pending
      : (d.conflicts || []).filter(function (c) { return !conflictRes(c).decision; }).length;
    var cards = [
      { label: '抽取规则', value: (d.rules || []).length + dismissedRules().length, unit: '条', note: '来自 ' + (d.source_files || []).length + ' 份资料' },
      { label: '生效规则', value: active, unit: '条', note: '将写入工作流', cls: 'is-accent' },
      { label: '已移除', value: dismissedRules().length, unit: '条', note: '保留记录，不生效', cls: '' },
      { label: '待裁决冲突', value: pending, unit: '处', note: pending ? '需人工确认' : '已全部处理', cls: pending ? 'is-danger' : 'is-accent' }
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
    if (d.client && d.client.is_draft) {
      html += '<div class="alert warn"><span class="alert-icon">!</span><div>'
        + '<b>这是草稿版本。</b>系统抽取可能漏项或误判归类，请逐条确认后再生成工作流。'
        + ' 处理完所有待裁决冲突并修正规则后，点「确认转正」去掉草稿标记。</div></div>';
    }
    var pending = (d.conflicts || []).filter(function (c) {
      return conflictRes(c).decision !== 'dismissed' && !conflictRes(c).decision;
    }).length;
    if (pending) {
      html += '<div class="alert info"><span class="alert-icon">i</span><div>'
        + '发现 <b>' + pending + ' 处客户资料互相矛盾</b>。系统未做自动裁决，'
        + '请选择采用哪个口径，或填写自定义解释口径。</div></div>';
    }
    el('alerts').innerHTML = html;
  }

  function renderSources() {
    var d = state.data;
    var excluded = d.excluded_files || [];
    el('srcSub').textContent = '共 ' + (d.source_files || []).length + ' 份文件送入模型'
      + (excluded.length ? '，' + excluded.length + ' 份未采用' : '');
    var html = (d.source_files || []).map(function (f) {
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

  // ---------- 冲突裁决 ----------
  // 完整裁决：二选一或删除即算完成；自定义口径必须填了内容才算完成。
  // 只选了 radio 但没填自定义内容时，卡片仍算「待裁决」，避免提前显示已裁决。
  function isResolved(c) {
    var res = conflictRes(c);
    if (!res.decision) return false;
    if (res.decision === 'custom') return !!(res.custom_text || '').trim();
    return true;
  }

  function renderConflicts() {
    var list = state.data.conflicts || [];
    var shown = list.filter(function (c) { return !state.hideDismissedConflicts || conflictRes(c).decision !== 'dismissed'; });
    var card = el('conflicts').closest('.section-card');
    if (!list.length) {
      if (card) card.hidden = true;
      return;
    }
    if (card) card.hidden = false;
    var pending = list.filter(function (c) { return !isResolved(c); }).length;
    el('conflictCount').textContent = pending + ' 处待裁决 / 共 ' + list.length + ' 处';

    el('conflicts').innerHTML = shown.map(function (c, i) {
      var res = conflictRes(c);
      var idx = list.indexOf(c);
      var resolved = isResolved(c);
      // 展开状态：用户正在操作的项保持展开，已完成的默认收起但可手动展开
      var isOpen = state.openConflicts[idx] !== undefined ? state.openConflicts[idx] : !resolved;
      var body = '<p>' + esc(c.detail) + '</p>'
        + '<div class="party-grid">'
        + partyBox('a', c.party_a, c.from_a, res.decision === 'accept_a', idx)
        + partyBox('b', c.party_b, c.from_b, res.decision === 'accept_b', idx)
        + '</div>'
        + '<div class="decide-row">'
        + '<label class="decide-radio"><input type="radio" name="dec-' + i + '" data-conflict="' + idx + '" value="accept_a"' + (res.decision === 'accept_a' ? ' checked' : '') + '> 采用 A</label>'
        + '<label class="decide-radio"><input type="radio" name="dec-' + i + '" data-conflict="' + idx + '" value="accept_b"' + (res.decision === 'accept_b' ? ' checked' : '') + '> 采用 B</label>'
        + '<label class="decide-radio"><input type="radio" name="dec-' + i + '" data-conflict="' + idx + '" value="custom"' + (res.decision === 'custom' ? ' checked' : '') + '> 自定义口径</label>'
        + '<label class="decide-radio"><input type="radio" name="dec-' + i + '" data-conflict="' + idx + '" value="dismissed"' + (res.decision === 'dismissed' ? ' checked' : '') + '> 删除该项</label>'
        + '</div>'
        + '<textarea class="decide-text" data-conflict-text="' + idx + '" rows="2" placeholder="自定义解释口径：选择「自定义口径」时必须填写，写清最终按哪个说法执行">'
        + esc(res.custom_text || '') + '</textarea>'
        + '<div class="decide-note-row">'
        + '<input class="decide-note" data-conflict-note="' + idx + '" value="' + esc(res.note || '') + '" placeholder="裁决理由（可选）">'
        + '</div>'
        + '<div class="apply-row">'
        + '<span class="apply-label">应用到规则</span>'
        + '<select class="select small" data-apply-rule="' + idx + '">' + applyRuleOptions(res.apply || {}) + '</select>'
        + '<select class="select small" data-apply-field="' + idx + '">' + applyFieldOptions(res.apply || {}) + '</select>'
        + '<span class="apply-hint">不改规则则留空。改 statement/condition 影响生文与验收；改 scope_note 只影响验收。</span>'
        + '</div>'
        + (resolved && res.decision === 'custom' && !res.resolved_at
            ? '<p class="decided-badge">已填写自定义口径，点「保存裁决」后生效</p>' : '')
        + (resolved && res.resolved_at
            ? '<p class="decided-badge">已保存：' + esc(DECISION_LABEL[res.decision] || res.decision)
              + ' · ' + esc(res.resolved_at) + '</p>' : '');

      return '<details class="conflict' + (resolved ? ' is-decided' : '') + '" data-cidx="' + idx + '"'
        + (isOpen ? ' open' : '') + '>'
        + '<summary><span class="conflict-idx">' + (idx + 1) + '</span>'
        + '<strong>' + esc(c.topic) + '</strong>'
        + (resolved ? '<span class="tag teal">已裁决</span>'
          : (res.decision ? '<span class="tag amber">待填写</span>' : '<span class="tag amber">待裁决</span>'))
        + '</summary>'
        + '<div class="conflict-body">' + body + '</div></details>';
    }).join('') || '<div class="empty">没有需要显示的冲突项</div>';

    el('conflictFoot').innerHTML = list.some(function (c) { return conflictRes(c).decision === 'dismissed'; })
      ? '<button class="button small" id="toggleDismissedConflicts">'
        + (state.hideDismissedConflicts ? '显示已删除项' : '隐藏已删除项') + '</button>'
        + '<button class="button teal small" id="saveConflictsBtn">保存裁决</button>'
      : '<button class="button teal small" id="saveConflictsBtn">保存裁决</button>';
  }

  function partyBox(key, text, from, chosen, idx) {
    return '<div class="party' + (chosen ? ' is-chosen' : '') + '">'
      + '<label>口径 ' + key.toUpperCase() + (chosen ? ' · 已采用' : '') + '</label>'
      + '<p>' + esc(text) + '</p><small>' + esc(from) + '</small></div>';
  }

  // 就地刷新单个冲突卡片：只重建 body 和 summary 标记，不动 <details> 本身，
  // 这样用户正在填写的输入框和展开状态都不会丢。
  function refreshConflictCard(idx) {
    var details = document.querySelector('.conflict[data-cidx="' + idx + '"]');
    if (!details) return;
    var c = (state.data.conflicts || [])[idx];
    if (!c) return;
    var res = conflictRes(c);
    var resolved = isResolved(c);

    details.classList.toggle('is-decided', resolved);
    details.open = true;

    var summary = details.querySelector('summary');
    if (summary) {
      var tag = summary.querySelector('.tag');
      if (tag) {
        tag.className = 'tag ' + (resolved ? 'teal' : 'amber');
        tag.textContent = resolved ? '已裁决' : (res.decision ? '待填写' : '待裁决');
      }
    }

    // 更新两侧「已采用」标记
    var parties = details.querySelectorAll('.party');
    [['a', 'accept_a'], ['b', 'accept_b']].forEach(function (pair, n) {
      var el2 = parties[n];
      if (!el2) return;
      var chosen = res.decision === pair[1];
      el2.classList.toggle('is-chosen', chosen);
      var lab = el2.querySelector('label');
      if (lab) lab.textContent = '口径 ' + pair[0].toUpperCase() + (chosen ? ' · 已采用' : '');
    });

    // 更新底部状态提示
    var body = details.querySelector('.conflict-body');
    if (!body) return;
    var old = body.querySelector('.decided-badge');
    if (old) old.remove();
    var text = '';
    if (resolved && res.resolved_at) {
      text = '已保存：' + esc(DECISION_LABEL[res.decision] || res.decision) + ' · ' + esc(res.resolved_at);
    } else if (resolved && res.decision === 'custom') {
      text = '已填写自定义口径，点「保存裁决」后生效';
    } else if (res.decision === 'custom') {
      text = '请在上方填写自定义口径内容，否则无法保存';
    }
    if (text) {
      var p = document.createElement('p');
      p.className = 'decided-badge';
      p.innerHTML = text;
      body.appendChild(p);
    }
  }

  function refreshConflictCounts() {
    var list = state.data.conflicts || [];
    var pending = list.filter(function (c) { return !isResolved(c); }).length;
    el('conflictCount').textContent = pending + ' 处待裁决 / 共 ' + list.length + ' 处';
    renderStats();
  }

  function applyRuleOptions(cur) {
    var opts = ['<option value="">不修改规则</option>'];
    activeRules().forEach(function (r) {
      opts.push('<option value="' + esc(r.id) + '"' + (cur.rule_id === r.id ? ' selected' : '') + '>'
        + esc(r.id) + ' · ' + esc(r.statement.slice(0, 30)) + '</option>');
    });
    return opts.join('');
  }

  function applyFieldOptions(cur) {
    var fields = [
      ['statement', '规则本身（影响生文+验收）'],
      ['condition', '适用条件（影响生文+验收）'],
      ['scope_note', '判定边界（只影响验收）']
    ];
    return '<option value="">选择字段</option>' + fields.map(function (f) {
      return '<option value="' + f[0] + '"' + (cur.field === f[0] ? ' selected' : '') + '>' + esc(f[1]) + '</option>';
    }).join('');
  }

  // ---------- 规则列表 ----------
  function renderRules() {
    var list = activeRules().filter(function (r) {
      if (state.cat && r.category !== state.cat) return false;
      if (state.onlyPending && r.origin !== 'manual') return false;
      return true;
    });

    var byCat = {};
    list.forEach(function (r) { (byCat[r.category_label] = byCat[r.category_label] || []).push(r); });

    el('ruleSub').textContent = '显示 ' + list.length + ' / ' + activeRules().length + ' 条；取消勾选即从工作流与验收中移除（记录保留）';

    var html = '';
    if (state.openEditor === 'new') html += ruleForm({}, true);
    Object.keys(byCat).forEach(function (cat) {
      html += '<div class="rule-group"><div class="rule-group-head">'
        + '<span>' + esc(cat) + '</span><em>' + byCat[cat].length + ' 条</em></div>';
      byCat[cat].forEach(function (r) {
        if (state.openEditor === r.id) { html += ruleForm(r, false); return; }
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
          + (r.is_manual ? '<span class="tag blue">人工录入</span>' : '')
          + (r.scope ? '<span class="rule-scope">' + esc((r.scope || []).join('/')) + '</span>' : '')
          + '<span class="rule-actions">'
          + '<button class="link-btn" data-edit="' + esc(r.id) + '">编辑</button>'
          + '<button class="link-btn danger" data-dismiss="' + esc(r.id) + '">移除</button>'
          + '</span>'
          + '</div>'
          + '<p class="rule-statement">' + esc(r.statement) + '</p>'
          + (r.condition ? '<p class="rule-line"><b>适用</b>' + esc(r.condition) + '</p>' : '')
          + (r.scope_note ? '<p class="rule-line"><b>边界</b>' + esc(r.scope_note) + '</p>' : '')
          + (r.alternative ? '<p class="rule-line"><b>改法</b>' + esc(r.alternative) + '</p>' : '')
          + (r.examples || []).map(function (e) {
              return '<div class="rule-ex"><span class="wrong">' + esc(e.wrong) + '</span>'
                + '<span class="right">' + esc(e.right) + '</span></div>';
            }).join('')
          + (r.detect ? '<p class="rule-detect">自动检查：' + esc((r.detect.values || []).join('、')) + '</p>' : '')
          + '<p class="rule-evidence">出处：' + esc(r.evidence) + '</p>'
          + '</div></article>';
      });
      html += '</div>';
    });
    el('rules').innerHTML = html || '<div class="empty">没有符合条件的规则</div>';
  }

  function ruleForm(r, isNew) {
    var id = (r.id || state.data.next_rule_id || '');
    return '<div class="rule-editor">'
      + '<div class="editor-head"><b>' + (isNew ? '新增写作规则' : '编辑规则 ' + esc(r.id)) + '</b>'
      + '<span class="editor-hint">人工录入固定为「模型判定」，不参与代码门禁</span></div>'
      + '<div class="editor-grid">'
      + '<div class="field"><label>规则 ID</label><input class="input" id="efId" value="' + esc(id) + '"'
      + (isNew ? '' : ' readonly') + '></div>'
      + '<div class="field"><label>类别</label><select class="select" id="efCat">'
      + CATS.map(function (c) {
          return '<option value="' + c[0] + '"'
            + ((r.category || 'prohibition') === c[0] ? ' selected' : '') + '>' + esc(c[1]) + '（' + c[0] + '）</option>';
        }).join('') + '</select></div>'
      + '<div class="field"><label>极性</label><select class="select" id="efPol">'
      + Object.keys(POL_LABEL).map(function (p) {
          return '<option value="' + p + '"' + ((r.polarity || 'must_not') === p ? ' selected' : '') + '>' + esc(POL_LABEL[p]) + '</option>';
        }).join('') + '</select></div>'
      + '<div class="field"><label>严重度</label><select class="select" id="efSev">'
      + [['reject', '拒稿线'], ['fix', '必须改'], ['advise', '建议']].map(function (s) {
          return '<option value="' + s[0] + '"' + ((r.severity || 'fix') === s[0] ? ' selected' : '') + '>' + esc(s[1]) + '</option>';
        }).join('') + '</select></div>'
      + '</div>'
      + '<div class="field"><label>作用于</label><div class="check-row">'
      + ['title', 'body', 'tags'].map(function (s) {
          var on = (r.scope || ['title', 'body']).indexOf(s) >= 0;
          return '<label class="switch"><input type="checkbox" data-scope="' + s + '"' + (on ? ' checked' : '') + '>' + s + '</label>';
        }).join('') + '</div></div>'
      + '<div class="field"><label>规则本身 <em>必填</em></label>'
      + '<textarea class="input" id="efStatement" rows="2" placeholder="如：不得使用「高分红」等夸大分红水平的表述">' + esc(r.statement || '') + '</textarea></div>'
      + '<div class="field"><label>判定边界 <em>必填</em> <span class="field-tip">不写边界模型判定会漂移</span></label>'
      + '<textarea class="input" id="efNote" rows="2" placeholder="如：限制夸大性宣传，不禁止依据已核实材料客观介绍分红表现">' + esc(r.scope_note || '') + '</textarea></div>'
      + '<div class="editor-grid">'
      + '<div class="field"><label>适用条件 <span class="field-tip">选填</span></label>'
      + '<input class="input" id="efCondition" value="' + esc(r.condition || '') + '" placeholder="如：谈及分红险时"></div>'
      + '<div class="field"><label>正确改法 <span class="field-tip">选填</span></label>'
      + '<input class="input" id="efAlt" value="' + esc(r.alternative || '') + '" placeholder="如：改用「红利实现率」客观表述"></div>'
      + '</div>'
      + '<div class="field"><label>正误示例 <span class="field-tip">选填，最有效的判定锚点</span></label>'
      + '<input class="input" id="efWrong" placeholder="错误写法" value="' + esc(((r.examples || [])[0] || {}).wrong || '') + '">'
      + '<input class="input" id="efRight" placeholder="正确写法" value="' + esc(((r.examples || [])[0] || {}).right || '') + '" style="margin-top:6px"></div>'
      + '<div class="editor-foot">'
      + '<span class="editor-out">出处将记为「人工录入」</span>'
      + '<button class="button small" data-cancel-edit="1">取消</button>'
      + '<button class="button teal small" data-save-rule="' + (isNew ? 'new' : esc(r.id)) + '">保存规则</button>'
      + '</div></div>';
  }

  function renderDismissed() {
    var list = dismissedRules();
    var card = el('dismissedRules').closest('.section-card');
    if (!list.length) { if (card) card.hidden = true; return; }
    if (card) card.hidden = false;
    el('dismissedCount').textContent = list.length + ' 条';
    el('dismissedRules').innerHTML = list.map(function (r) {
      return '<tr><td><span class="rule-id">' + esc(r.id) + '</span></td>'
        + '<td class="rule-text">' + esc(r.statement) + '</td>'
        + '<td class="muted-cell">' + esc(r.dismissed_at || '') + '</td>'
        + '<td><button class="link-btn" data-restore="' + esc(r.id) + '">恢复</button></td></tr>';
    }).join('');
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
    renderConflicts(); renderRules(); renderDismissed(); renderNotRules();
    renderPromote();
  }

  function renderPromote() {
    var v = (state.data.client || {}).version || '';
    el('verText').textContent = v;
    var isDraft = String(v).indexOf('draft') >= 0;
    el('promoteBtn').hidden = !isDraft;
    el('promoteBtn').textContent = '确认转正';
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
    state.openEditor = null;
  fetch('/api/rules/' + encodeURIComponent(slug)).then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function (data) {
    state.data = data;
    state.kept = {};
    (data.rules || []).forEach(function (r) { state.kept[r.id] = r.status !== 'dismissed'; });
    localStorage.setItem('geo_last_slug', slug);

    el('crumbClient').textContent = data.client.short;
    el('sideStatus').textContent = data.client.short + ' · 规则包 ' + data.client.version;

    el('catFilter').innerHTML = '<option value="">全部类别</option>';
    var cats = [];
    (data.rules || []).forEach(function (r) {
      if (cats.indexOf(r.category_label) < 0) cats.push(r.category_label);
    });
    cats.forEach(function (c) {
      var o = document.createElement('option');
      o.value = (data.rules.filter(function (r) { return r.category_label === c; })[0] || {}).category;
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

  function post(url, payload) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload ? JSON.stringify(payload) : undefined
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); });
  }

  function failMsg(x) {
    var errs = (x.d && x.d.errors) || [];
    return (x.d && x.d.error) || (errs.length ? errs.join('；') : '操作失败');
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

  // 移除 / 恢复 / 编辑 / 取消 / 保存规则：事件委托，列表重渲染后依然有效
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!t.dataset) return;

    if (t.dataset.edit) {
      state.openEditor = t.dataset.edit;
      renderRules();
      return;
    }
    if (t.dataset.cancelEdit) {
      state.openEditor = null;
      renderRules();
      return;
    }
    if (t.dataset.dismiss) {
      var rid = t.dataset.dismiss;
      if (!confirm('移除规则 ' + rid + '？\n\n记录会保留在规则包里（可恢复），但不再写入工作流，也不参与验收判定。')) return;
      post('/api/rules/' + encodeURIComponent(state.slug) + '/rule/' + encodeURIComponent(rid) + '/dismiss')
        .then(function (x) {
          if (!x.ok) throw new Error(failMsg(x));
          toast('已移除 ' + rid);
          return loadRules(state.slug);
        }).catch(function (err) { toast(err.message, 4000); });
      return;
    }
    if (t.dataset.restore) {
      var rid2 = t.dataset.restore;
      post('/api/rules/' + encodeURIComponent(state.slug) + '/rule/' + encodeURIComponent(rid2) + '/restore')
        .then(function (x) {
          if (!x.ok) throw new Error(failMsg(x));
          toast('已恢复 ' + rid2);
          return loadRules(state.slug);
        }).catch(function (err) { toast(err.message, 4000); });
      return;
    }
    if (t.dataset.saveRule) {
      var isNew = t.dataset.saveRule === 'new';
      var scope = [];
      document.querySelectorAll('[data-scope]').forEach(function (c) {
        if (c.checked) scope.push(c.dataset.scope);
      });
      var rule = {
        id: (el('efId').value || '').trim(),
        category: el('efCat').value,
        polarity: el('efPol').value,
        severity: el('efSev').value,
        scope: scope,
        statement: el('efStatement').value.trim(),
        scope_note: el('efNote').value.trim(),
        condition: el('efCondition').value.trim(),
        alternative: el('efAlt').value.trim()
      };
      var wrong = el('efWrong').value.trim(), right = el('efRight').value.trim();
      if (wrong || right) rule.examples = [{ wrong: wrong, right: right }];

      t.disabled = true;
      post('/api/rules/' + encodeURIComponent(state.slug) + '/rule',
           { mode: isNew ? 'create' : 'update', rule: rule })
        .then(function (x) {
          if (!x.ok) throw new Error(failMsg(x));
          toast((isNew ? '已新增 ' : '已保存 ') + x.d.rule.id
            + (isNew ? '' : '；该规则已同步进工作流与验收'));
          state.openEditor = null;
          return loadRules(state.slug);
        }).catch(function (err) {
          toast(err.message, 6000);
          t.disabled = false;
        });
      return;
    }
    if (t.id === 'newRuleBtn') {
      state.openEditor = 'new';
      state.cat = '';
      el('catFilter').value = '';
      renderRules();
      return;
    }
    if (t.id === 'toggleDismissedConflicts') {
      state.hideDismissedConflicts = !state.hideDismissedConflicts;
      renderConflicts();
      return;
    }
    if (t.id === 'saveConflictsBtn') {
      saveConflicts(t);
      return;
    }
    if (t.id === 'promoteBtn') {
      promote();
      return;
    }
  });

  // 冲突项内容改动只记在 state，点「保存裁决」统一提交
  document.addEventListener('input', function (e) {
    var t = e.target;
    if (!t.dataset) return;
    var i;
    if (t.dataset.conflictText != null) {
      i = +t.dataset.conflictText;
      state.data.conflicts[i].resolution = state.data.conflicts[i].resolution || {};
      state.data.conflicts[i].resolution.custom_text = t.value;
      refreshConflictCard(i);
      refreshConflictCounts();
    } else if (t.dataset.conflictNote != null) {
      i = +t.dataset.conflictNote;
      state.data.conflicts[i].resolution = state.data.conflicts[i].resolution || {};
      state.data.conflicts[i].resolution.note = t.value;
    }
  });

  // 记住展开/收起状态，供重渲染时还原
  document.addEventListener('toggle', function (e) {
    var t = e.target;
    if (t && t.classList && t.classList.contains('conflict') && t.dataset.cidx != null) {
      state.openConflicts[+t.dataset.cidx] = t.open;
    }
  }, true);

  document.addEventListener('change', function (e) {
    var t = e.target;
    if (!t.dataset) return;
    var i;
    if (t.dataset.conflict != null && t.type === 'radio') {
      i = +t.dataset.conflict;
      var c = state.data.conflicts[i];
      c.resolution = c.resolution || {};
      c.resolution.decision = t.value;
      // 不整体重渲染：重渲染会重建 <details> 并按「已裁决」收起，
      // 用户刚点「自定义口径」就看不到输入框了。只就地更新这个卡片。
      state.openConflicts[i] = true;
      refreshConflictCard(i);
      refreshConflictCounts();
    } else if (t.dataset.applyRule != null) {
      i = +t.dataset.applyRule;
      var c2 = state.data.conflicts[i];
      c2.resolution = c2.resolution || {};
      c2.apply = c2.apply || {};
      c2.apply.rule_id = t.value;
    } else if (t.dataset.applyField != null) {
      i = +t.dataset.applyField;
      var c3 = state.data.conflicts[i];
      c3.apply = c3.apply || {};
      c3.apply.field = t.value;
    }
  });

  function saveConflicts(btn) {
    var all = state.data.conflicts || [];
    // 选了自定义口径但没填内容的，先拦住，避免保存成一条空裁决
    var unfilled = [];
    all.forEach(function (c, i) {
      var res = c.resolution || {};
      if (res.decision === 'custom' && !(res.custom_text || '').trim()) {
        unfilled.push({ idx: i, topic: c.topic });
      }
    });
    if (unfilled.length) {
      toast('有 ' + unfilled.length + ' 处选了「自定义口径」但没填内容：' + unfilled[0].topic, 6000);
      state.openConflicts[unfilled[0].idx] = true;
      refreshConflictCard(unfilled[0].idx);
      return;
    }

    var payload = all.filter(function (c) {
      return (c.resolution && c.resolution.decision) || (c.apply && c.apply.rule_id && c.apply.field);
    }).map(function (c) {
      return { topic: c.topic, resolution: c.resolution || {}, apply: c.apply || {} };
    });
    if (!payload.length) { toast('还没有做任何裁决'); return; }
    btn.disabled = true;
    post('/api/rules/' + encodeURIComponent(state.slug) + '/conflicts', { conflicts: payload })
      .then(function (x) {
        if (!x.ok) throw new Error(failMsg(x));
        var msg = '裁决已保存';
        if (x.d.applied && x.d.applied.length) {
          msg += '，已写入 ' + x.d.applied.map(function (a) { return a.rule_id + '.' + a.field; }).join('、');
        }
        toast(msg, 4000);
        return loadRules(state.slug);
      }).catch(function (err) {
        toast(err.message, 6000);
        btn.disabled = false;
      });
  }

  function promote() {
    if (!confirm('确认转正？\n\n版本号会去掉 -draft 标记。转正前请确认已处理全部冲突、并核对规则内容。')) return;
    var btn = el('promoteBtn');
    btn.disabled = true;
    post('/api/rules/' + encodeURIComponent(state.slug) + '/promote')
      .then(function (x) {
        if (!x.ok) throw new Error(failMsg(x));
        toast('已转正：' + x.d.version);
        return loadRules(state.slug);
      }).catch(function (err) {
        toast(err.message, 6000);
        btn.disabled = false;
      });
  }

  el('catFilter').addEventListener('change', function (e) {
    state.cat = e.target.value; renderRules();
  });

  el('toggleAll').addEventListener('click', function () {
    state.onlyPending = !state.onlyPending;
    this.textContent = state.onlyPending ? '显示全部' : '只看人工录入';
    renderRules();
  });

  el('buildBtn').addEventListener('click', function () {
    if (state.busy) return;
    var kept = Object.keys(state.kept).filter(function (k) { return state.kept[k]; });
    if (!kept.length) { toast('至少要保留一条规则'); return; }
    state.busy = true;
    this.disabled = true;
    this.textContent = '正在保存…';

    post('/api/rules/' + encodeURIComponent(state.slug) + '/save', { kept: state.kept })
      .then(function (x) {
        if (!x.ok) throw new Error(failMsg(x));
        el('buildBtn').textContent = '正在生成工作流…';
        return post('/api/build/' + encodeURIComponent(state.slug));
      })
      .then(function (x) {
        if (!x.ok) throw new Error(failMsg(x));
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
        return loadRules(state.slug);
      })
      .catch(function (e) {
        toast(e.message, 6000);
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
