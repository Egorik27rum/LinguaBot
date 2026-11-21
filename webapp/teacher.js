'use strict';

/* Панель преподавателя LinguaBot. Все разделы: статус, настройки, боты, модели,
   задания, ученики, параметры ИИ, цели и диалог, внешние ссылки, главное меню.
   Запросы подписаны initData Telegram. Действия через data-action и делегирование. */
(function () {
  var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) {
    tg.ready();
    tg.expand();
  }
  var initData = tg ? tg.initData : '';
  var root = document.getElementById('app');
  var titleEl = document.getElementById('title');
  var toastEl = document.getElementById('toast');
  var toastTimer = null;

  var TOPUP_URL = 'https://polza.ai';
  var TITLES = {
    menu: 'Панель преподавателя',
    status: 'Статус',
    settings: 'Настройки',
    bots: 'Боты',
    models: 'Модели',
    'models-role': 'Модели',
    'models-all': 'Модели и цены',
    tasks: 'Задания',
    students: 'Ученики',
    ai: 'Параметры ИИ',
    'ai-role': 'Роль ассистента',
    dialog: 'Цели и диалог',
    'dialog-modes': 'Режимы проверки',
    goals: 'Цели'
  };
  var BOT_STATES = {
    running: 'работает',
    starting: 'запускается',
    stopped: 'остановлен',
    error: 'ошибка',
    unknown: 'неизвестно',
    pending: 'ждёт перезапуска run.bat',
    disabled: 'выключен'
  };
  var SORTS = { rec: 'Рекомендуемые', desc: 'Цена ↓', asc: 'Цена ↑' };

  var ui = {
    view: 'menu',
    stack: [],
    data: {},
    busy: false,
    confirm: null
  };

  function esc(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function toast(text) {
    toastEl.textContent = text;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.hidden = true; }, 3500);
  }

  async function api(path, options) {
    var opts = options || {};
    var headers = { Authorization: 'tma ' + initData };
    var init = { method: opts.method || 'GET', headers: headers };
    if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.body);
    }
    var response = await fetch(path, init);
    var data = {};
    try {
      data = await response.json();
    } catch (err) {
      data = {};
    }
    if (!response.ok) {
      throw new Error(data.error || 'Сервер не ответил. Попробуйте позже.');
    }
    return data;
  }

  // Одна операция за раз: двойное нажатие не отправит два запроса
  async function run(task) {
    if (ui.busy) {
      toast('Подождите, запрос выполняется');
      return;
    }
    ui.busy = true;
    try {
      await task();
    } catch (err) {
      toast(err.message || 'Произошла ошибка');
    } finally {
      ui.busy = false;
    }
  }

  function btn(label, action, opts) {
    var o = opts || {};
    var attrs = ' data-action="' + action + '"';
    ['view', 'id', 'page', 'role', 'value', 'key'].forEach(function (name) {
      if (o[name] !== undefined && o[name] !== null) {
        attrs += ' data-' + name + '="' + esc(o[name]) + '"';
      }
    });
    return '<button class="btn ' + (o.kind || '') + '"' + attrs + (o.disabled ? ' disabled' : '') + '>' +
      esc(label) + '</button>';
  }

  function backRow() {
    return '<div class="row">' + btn('Назад', 'back') + '</div>';
  }

  function labelOf(list, id) {
    var found = list.filter(function (item) { return item.id === id; })[0];
    return found ? found.name : id;
  }

  function go(view) {
    if (ui.view !== view) {
      ui.stack.push(ui.view);
    }
    ui.view = view;
    return loadView(view);
  }

  async function back() {
    ui.confirm = null;
    var previous = ui.stack.pop() || 'menu';
    ui.view = previous;
    return loadView(previous);
  }

  async function loadView(view) {
    if (view === 'menu') {
      return render();
    }
    if (view === 'status') {
      ui.data.status = await api('/api/teacher/status');
    } else if (view === 'settings') {
      ui.data.key = await api('/api/teacher/settings/key');
      ui.data.context = await api('/api/teacher/settings/context');
    } else if (view === 'bots') {
      ui.data.bots = await api('/api/teacher/bots');
    } else if (view === 'models-role') {
      await loadModels(ui.data.role, ui.data.category || 'text', ui.data.sort || 'rec', ui.data.page || 0);
    } else if (view === 'models-all') {
      ui.data.all = await api('/api/teacher/models/all');
    } else if (view === 'tasks') {
      ui.data.tasks = await api('/api/teacher/tasks');
    } else if (view === 'students') {
      ui.data.students = await api('/api/teacher/students?page=' + (ui.data.studentPage || 0));
    } else if (view === 'ai' || view === 'ai-role') {
      ui.data.ai = await api('/api/teacher/ai');
    } else if (view === 'dialog') {
      ui.data.dialog = await api('/api/teacher/dialog');
    } else if (view === 'goals') {
      ui.data.goals = await api('/api/teacher/goals');
      ui.data.dialog = await api('/api/teacher/dialog');
    }
    return render();
  }

  async function loadModels(role, category, sort, page) {
    var query = '?role=' + encodeURIComponent(role) +
      '&category=' + encodeURIComponent(category) +
      '&sort=' + encodeURIComponent(sort) +
      '&page=' + Number(page || 0);
    ui.data.models = await api('/api/teacher/models' + query);
    ui.data.role = role;
    ui.data.category = category;
    ui.data.sort = sort;
    ui.data.page = ui.data.models.page;
  }

  // ---------- Экраны ----------

  function menuHtml() {
    return '<section class="card"><p class="muted">Управление LinguaBot</p></section>' +
      '<div class="menu">' +
      btn('Статус', 'go', { view: 'status' }) +
      btn('Настройки', 'go', { view: 'settings' }) +
      btn('Боты', 'go', { view: 'bots' }) +
      btn('Модели', 'models-open') +
      btn('Задания', 'go', { view: 'tasks' }) +
      btn('Ученики', 'go', { view: 'students' }) +
      btn('Параметры ИИ', 'go', { view: 'ai' }) +
      btn('Цели и диалог', 'go', { view: 'dialog' }) +
      btn('Пополнить баланс', 'topup') +
      '</div>';
  }

  function statusHtml() {
    var s = ui.data.status;
    var bot = s.bot;
    var state = BOT_STATES[bot.state] || bot.state;
    var username = bot.username ? ' (@' + esc(bot.username) + ')' : '';
    var error = bot.error ? '<p class="muted">' + esc(bot.error) + '</p>' : '';
    var task = s.active_task ? '№' + esc(s.active_task.id) + ' «' + esc(s.active_task.title) + '»' : 'нет';
    var goal = s.active_goal ? '№' + esc(s.active_goal.id) + ' «' + esc(s.active_goal.text) + '»' : 'не задана';
    return '<section class="card">' +
      '<p>Основной бот: <b>' + esc(state) + '</b>' + username + '</p>' + error +
      '<p>Ключ Polza.ai: <b>' + (s.polza_key ? esc(s.polza_key) : 'не задан') + '</b></p>' +
      '<p>Активное задание: ' + task + '</p>' +
      '<p>Ответов нейросети: <b>' + esc(s.reply_limit) + '</b></p>' +
      '<p>Режим проверки цели: <b>' + esc(s.goal_mode) + '</b></p>' +
      '<p>Активная цель: ' + goal + '</p>' +
      '</section>' +
      '<div class="row">' + btn('Обновить', 'refresh') + '</div>' + backRow();
  }

  function settingsHtml() {
    var key = ui.data.key;
    var ctx = ui.data.context;
    var keyBlock = ui.confirm && ui.confirm.kind === 'key'
      ? '<section class="card"><h3>Смена ключа Polza.ai</h3>' +
        '<p class="muted">Сейчас: ' + (key.polza_key ? esc(key.polza_key) : 'не задан') + '</p>' +
        '<input id="newKey" class="input" autocomplete="off" placeholder="Новый ключ">' +
        '<p class="muted">Ключ проверяется в Polza.ai. Неверный ключ не сохраняется.</p>' +
        '<div class="row">' + btn('Сохранить ключ', 'key-save', { kind: 'primary' }) +
        btn('Отмена', 'cancel-confirm') + '</div></section>'
      : '<section class="card"><h3>Ключ Polza.ai</h3>' +
        '<p>Текущий: <b>' + (key.polza_key ? esc(key.polza_key) : 'не задан') + '</b></p>' +
        '<div class="row">' + btn('Сменить ключ', 'key-ask', { kind: 'danger' }) + '</div></section>';
    var ctxBlock = '<section class="card"><h3>Контекст для оценки</h3>' +
      '<textarea id="ctxText" class="input" rows="6" maxlength="' + ctx.limit + '">' + esc(ctx.context) + '</textarea>' +
      '<p class="muted">Символов: до ' + ctx.limit + '.</p>' +
      '<div class="row">' + btn('Сохранить контекст', 'ctx-save', { kind: 'primary' }) + '</div></section>';
    return keyBlock + ctxBlock + backRow();
  }

  function botsHtml() {
    var b = ui.data.bots;
    var warn = b.config_error ? '<p class="info">Внимание: ' + esc(b.config_error) + '</p>' : '';
    var list = b.items.map(function (item) {
      var label = item.username ? '@' + item.username : item.name;
      var state = BOT_STATES[item.state] || item.state;
      var err = item.error ? '<p class="muted">' + esc(item.error) + '</p>' : '';
      return '<section class="card"><b>' + esc(label) + '</b> — ' + esc(state) + err + '</section>';
    }).join('');

    var addBlock = '';
    if (ui.confirm && ui.confirm.kind === 'bot-add') {
      addBlock = '<section class="card"><h3>Добавить бота</h3>' +
        '<p class="muted">Токен от @BotFather. Он уходит на сервер и не показывается снова.</p>' +
        '<input id="botToken" class="input" autocomplete="off" placeholder="123456789:AAE-...">' +
        '<div class="row">' + btn('Добавить', 'bot-add', { kind: 'primary' }) +
        btn('Отмена', 'cancel-confirm') + '</div></section>';
    }

    var checkBlock = '';
    if (ui.confirm && ui.confirm.kind === 'bot-check') {
      var helpers = b.items.filter(function (i) { return i.role === 'helper' && i.enabled; });
      var buttons = helpers.length
        ? helpers.map(function (item) {
          return btn(item.username ? '@' + item.username : item.name, 'bot-check', { key: item.name });
        }).join('')
        : '<p class="muted">Доп. ботов нет, проверять нечего.</p>';
      checkBlock = '<section class="card"><h3>Проверка привязки</h3>' + buttons + '</section>' +
        '<div class="row">' + btn('Отмена', 'cancel-confirm') + '</div>';
    }

    var controls = !addBlock && !checkBlock
      ? '<div class="row">' + btn('Добавить бота', 'bot-add-open', { kind: 'primary' }) +
        btn('Проверить привязку', 'bot-check-open') + '</div>'
      : '';
    return warn + list + addBlock + checkBlock + controls + backRow();
  }

  function modelsHtml() {
    return '<div class="menu">' +
      btn('Анализ текста', 'models-role-open', { role: 'text' }) +
      btn('Анализ голоса', 'models-role-open', { role: 'speech' }) +
      btn('Все модели и цены', 'go', { view: 'models-all' }) +
      btn('Обновить список', 'models-refresh') +
      '</div>' + backRow();
  }

  function modelsRoleHtml() {
    var m = ui.data.models;
    if (!m) {
      return '<p class="muted">Нет данных.</p>';
    }
    var cats = m.role === 'speech' ? ['speech', 'multimodal'] : ['text', 'multimodal'];
    var catNames = { text: 'Текст (LLM)', speech: 'Расшифровка (STT)', multimodal: 'Голос + текст' };
    var catButtons = '<div class="row">' + cats.map(function (c) {
      return btn((c === m.category ? '✓ ' : '') + catNames[c], 'models-cat', { role: m.role, key: c });
    }).join('') + '</div>';
    var sortButtons = '<div class="row">' + Object.keys(SORTS).map(function (s) {
      return btn((s === m.sort ? '✓ ' : '') + SORTS[s], 'models-sort', { role: m.role, key: s });
    }).join('') + '</div>';
    var items = m.items.length ? m.items.map(function (item) {
      var current = item.id === m.current ? '✓ ' : '';
      return btn(current + item.name + ' · ' + item.prices, 'models-pick', { id: item.id });
    }).join('') : '<p class="muted">В этой категории моделей нет.</p>';
    var pager = '';
    if (m.page > 0) pager += btn('‹', 'models-page', { page: m.page - 1 });
    if (m.page < m.pages - 1) pager += btn('›', 'models-page', { page: m.page + 1 });
    return '<p class="info">' + esc(m.role_title) + '. Текущая: ' +
      esc(m.current || 'не выбрана (модель по умолчанию)') + '</p>' +
      catButtons + sortButtons +
      '<p class="muted">Страница ' + (m.page + 1) + ' из ' + m.pages + '. Цена: вход / выход за 1M токенов.</p>' +
      '<div class="menu">' + items + '</div>' +
      (pager ? '<div class="row">' + pager + '</div>' : '') +
      '<div class="row">' + btn('Сбросить модель', 'models-reset', { role: m.role, kind: 'danger' }) + '</div>' +
      backRow();
  }

  function modelsAllHtml() {
    var a = ui.data.all;
    var groups = a.groups.map(function (g) {
      var rows = g.items.map(function (item) {
        return '<div class="pre">• ' + esc(item.id) + ' — ' + esc(item.prices) + '</div>';
      }).join('');
      return '<h3>' + esc(g.title) + ' (' + g.count + ')</h3>' + rows;
    }).join('');
    return '<section class="card">' + (groups || '<p class="muted">Моделей нет.</p>') + '</section>' + backRow();
  }

  function tasksHtml() {
    var t = ui.data.tasks;
    var form = ui.confirm && ui.confirm.kind === 'task-new'
      ? '<section class="card"><h3>Новое задание</h3>' +
        '<input id="taskTitle" class="input" maxlength="100" placeholder="Название">' +
        '<textarea id="taskContent" class="input" rows="6" maxlength="2000" placeholder="Условие задания"></textarea>' +
        '<div class="row">' + btn('Создать и сделать активным', 'task-save', { kind: 'primary' }) +
        btn('Отмена', 'cancel-confirm') + '</div></section>'
      : '';
    var offConfirm = ui.confirm && ui.confirm.kind === 'task-off'
      ? '<section class="card"><p>Снять активное задание? Ученики перестанут его видеть.</p>' +
        '<div class="row">' + btn('Да, снять', 'task-off-do', { kind: 'danger' }) +
        btn('Отмена', 'cancel-confirm') + '</div></section>'
      : '';
    var list = t.items.length
      ? t.items.map(function (task) {
        return btn((task.id === t.active_id ? '✓ ' : '') + '№' + task.id + ' ' + task.title, 'task-set', { id: task.id });
      }).join('')
      : '<p class="muted">Заданий пока нет.</p>';
    return form + offConfirm +
      '<div class="row">' +
      btn('Новое задание', 'task-new', { kind: 'primary' }) +
      btn('Снять активное', 'task-off', { kind: 'danger' }) +
      '</div>' +
      '<p class="muted">Нажмите задание, чтобы сделать его активным.</p>' +
      '<div class="menu">' + list + '</div>' + backRow();
  }

  function studentsHtml() {
    var c = ui.confirm;
    if (c && c.kind === 'student-delete') {
      var toggleLabel = c.topic ? 'Не удалять топик в группе' : 'Удалить топик в группе';
      var topicBlock = c.hasTopic
        ? '<p>Удалить топик в группе: <b>' + (c.topic ? 'да' : 'нет') + '</b></p>' +
          '<div class="row">' + btn(toggleLabel, 'student-toggle') + '</div>'
        : '<p class="muted">Топика в группе нет.</p>';
      return '<section class="card"><h3>Удалить ученика</h3>' +
        '<p>Удалить ученика ' + esc(c.name) + '? История и оценки будут удалены, открытый диалог отменён.</p>' +
        '<p class="muted">Сообщения в личном чате ученика с ботом не удаляются. После удаления ему нужно отправить /start.</p>' +
        topicBlock +
        '<div class="row">' + btn('Да, удалить', 'student-delete-do', { kind: 'danger' }) +
        btn('Отмена', 'cancel-confirm') + '</div></section>';
    }
    var st = ui.data.students;
    var head = st.total
      ? '<p class="muted">Зарегистрировано: ' + st.total + '. Страница ' + (st.page + 1) + ' из ' + st.pages + '.</p>'
      : '<p class="muted">Зарегистрированных учеников пока нет.</p>';
    var cards = st.items.map(function (s) {
      var handle = s.username ? ' · @' + esc(s.username) : '';
      var topic = s.has_topic ? 'топик есть' : 'без топика';
      return '<section class="card"><b>' + esc(s.name) + '</b>' +
        '<p class="muted">' + topic + handle + '</p>' +
        '<div class="row">' + btn('Удалить', 'student-ask', { id: s.id, kind: 'danger' }) + '</div></section>';
    }).join('');
    var nav = '';
    if (st.page > 0) nav += btn('‹ Назад', 'students-page', { page: st.page - 1 });
    if (st.page < st.pages - 1) nav += btn('Дальше ›', 'students-page', { page: st.page + 1 });
    return head + cards + (nav ? '<div class="row">' + nav + '</div>' : '') + backRow();
  }

  function aiHtml() {
    var a = ui.data.ai;
    var rows = [
      btn('Роль: ' + a.role.name, 'go', { view: 'ai-role' }),
      btn('Температура: ' + a.temperature, 'ai-cycle', { key: 'temperature' }),
      btn('Длина ответа: ' + a.max_tokens, 'ai-cycle', { key: 'max_tokens' }),
      btn('История: ' + (a.history_limit === 0 ? 'выключена' : a.history_limit + ' реплик'), 'ai-cycle', { key: 'history_limit' }),
      btn('Исправления: ' + labelOf(a.options.correction, a.correction), 'ai-cycle', { key: 'correction' }),
      btn('Язык: ' + labelOf(a.options.reply_language, a.reply_language), 'ai-cycle', { key: 'reply_language' }),
      btn('Сбросить к умолчанию', 'ai-reset', { kind: 'danger' })
    ];
    return '<div class="menu">' + rows.join('') + '</div>' +
      '<p class="muted">Температура: 0 — точнее, 1.3 — разнообразнее. Изменения применяются сразу.</p>' +
      backRow();
  }

  function aiRoleHtml() {
    var a = ui.data.ai;
    var roles = a.options.roles.map(function (r) {
      return btn((a.role.id === r.id ? '✓ ' : '') + r.name, 'ai-role-pick', { id: r.id });
    }).join('');
    var custom = ui.confirm && ui.confirm.kind === 'ai-custom'
      ? '<section class="card"><h3>Своя роль</h3>' +
        '<textarea id="customRole" class="input" rows="4" maxlength="' + a.options.custom_role_max + '"></textarea>' +
        '<div class="row">' + btn('Сохранить', 'ai-custom-save', { kind: 'primary' }) +
        btn('Отмена', 'cancel-confirm') + '</div></section>'
      : '<div class="row">' + btn((a.role.id === 'custom' ? '✓ ' : '') + 'Своя роль', 'ai-custom-open') + '</div>';
    return '<section class="card"><p>Сейчас: <b>' + esc(a.role.name) + '</b></p><div class="pre">' + esc(a.role.text) + '</div></section>' +
      '<div class="menu">' + roles + '</div>' + custom + backRow();
  }

  function dialogHtml() {
    var d = ui.data.dialog;
    var limitRow = '<div class="row">' + d.reply_limit_options.map(function (n) {
      return btn((n === d.reply_limit ? '✓ ' : '') + n, 'dlg-limit', { value: n });
    }).join('') + '</div>';
    var modeNames = [['soft', 'Мягкий'], ['normal', 'Обычный'], ['strict', 'Строгий']];
    var modeRow = '<div class="row">' + modeNames.map(function (m) {
      return btn((m[0] === d.goal_mode ? '✓ ' : '') + m[1], 'dlg-mode', { key: m[0] });
    }).join('') + '</div>';
    return '<section class="card"><h3>Ответов нейросети в диалоге</h3>' + limitRow + '</section>' +
      '<section class="card"><h3>Режим проверки цели</h3>' + modeRow +
      '<div class="row">' + btn('Что значат режимы', 'dlg-modes') + '</div></section>' +
      '<div class="menu">' + btn('Цели', 'go', { view: 'goals' }) + '</div>' + backRow();
  }

  function dialogModesHtml() {
    var modes = ui.data.modes || [];
    var text = modes.map(function (m) {
      return m.title + ': ' + m.criteria + '\nПотолок итога, если цель не достигнута: ' + m.cap + '.';
    }).join('\n\n');
    return '<section class="card"><div class="pre">' + esc(text) + '</div></section>' + backRow();
  }

  function goalsHtml() {
    var g = ui.data.goals;
    var d = ui.data.dialog;
    var active = d.active_goal
      ? 'Активная цель: №' + d.active_goal.id + ' «' + d.active_goal.text + '»'
      : 'Активной цели нет.';
    var confirm = ui.confirm && ui.confirm.kind === 'goal-new'
      ? '<section class="card"><h3>Новая цель</h3>' +
        '<textarea id="goalText" class="input" rows="3" maxlength="500" placeholder="Например: заказать кофе и уточнить состав"></textarea>' +
        '<div class="row">' + btn('Создать и сделать активной', 'goal-save', { kind: 'primary' }) +
        btn('Отмена', 'cancel-confirm') + '</div></section>'
      : '';
    var list = g.items.length
      ? g.items.map(function (goal) {
        return btn((goal.id === g.active_id ? '✓ ' : '') + '№' + goal.id + ' ' + goal.text, 'goal-pick', { id: goal.id });
      }).join('')
      : '<p class="muted">Целей пока нет. Создайте первую.</p>';
    return '<p class="info">' + esc(active) + '</p>' + confirm +
      '<div class="row">' + btn('Новая цель', 'goal-new', { kind: 'primary' }) +
      btn('Снять активную', 'goal-off') + '</div>' +
      '<div class="menu">' + list + '</div>' + backRow();
  }

  var VIEWS = {
    menu: menuHtml,
    status: statusHtml,
    settings: settingsHtml,
    bots: botsHtml,
    models: modelsHtml,
    'models-role': modelsRoleHtml,
    'models-all': modelsAllHtml,
    tasks: tasksHtml,
    students: studentsHtml,
    ai: aiHtml,
    'ai-role': aiRoleHtml,
    dialog: dialogHtml,
    'dialog-modes': dialogModesHtml,
    goals: goalsHtml
  };

  function render() {
    if (tg && tg.BackButton) {
      if (ui.view === 'menu') {
        tg.BackButton.hide();
      } else {
        tg.BackButton.show();
      }
    }
    titleEl.textContent = TITLES[ui.view] || 'Панель преподавателя';
    var view = VIEWS[ui.view] || menuHtml;
    root.innerHTML = view();
  }

  // ---------- Действия ----------

  async function saveKey() {
    var box = document.getElementById('newKey');
    var value = box ? box.value.trim() : '';
    var result = await api('/api/teacher/settings/key', {
      method: 'POST',
      body: { api_key: value, confirm: true }
    });
    ui.confirm = null;
    ui.data.key = await api('/api/teacher/settings/key');
    toast('Ключ сохранён: ' + result.polza_key);
    render();
  }

  async function saveContext() {
    var box = document.getElementById('ctxText');
    ui.data.context = await api('/api/teacher/settings/context', {
      method: 'POST',
      body: { context: box ? box.value : '' }
    });
    toast('Контекст сохранён');
    render();
  }

  async function addBot() {
    var box = document.getElementById('botToken');
    var token = box ? box.value.trim() : '';
    var result = await api('/api/teacher/bots', { method: 'POST', body: { token: token } });
    ui.confirm = null;
    ui.data.bots = await api('/api/teacher/bots');
    toast('Бот ' + result.name + ' добавлен. Перезапустите run.bat');
    render();
  }

  async function checkBot(name) {
    var result = await api('/api/teacher/bots/check', { method: 'POST', body: { name: name } });
    ui.confirm = null;
    var label = result.username ? '@' + result.username : name;
    toast(label + ': ' + result.details);
    render();
  }

  async function selectModel(id) {
    var role = ui.data.role;
    await api('/api/teacher/models/select', { method: 'POST', body: { role: role, model_id: id } });
    toast('Модель выбрана');
    await loadModels(role, ui.data.category, ui.data.sort, ui.data.page);
    render();
  }

  async function resetModel(role) {
    await api('/api/teacher/models/reset', { method: 'POST', body: { role: role } });
    toast('Модель сброшена на значение по умолчанию');
    await loadModels(role, ui.data.category, ui.data.sort, 0);
    render();
  }

  async function refreshModels() {
    var result = await api('/api/teacher/models/refresh', { method: 'POST' });
    toast('Список обновлён: ' + result.count);
    render();
  }

  var CYCLES = {
    temperature: { path: 'temperature', field: 'temperature', list: [0.0, 0.3, 0.7, 1.0, 1.3] },
    max_tokens: { path: 'max-tokens', field: 'max_tokens', list: [300, 500, 800, 1200, 2000] },
    history_limit: { path: 'history', field: 'history_limit', list: [0, 5, 10, 20, 40] },
    correction: { path: 'correction', field: 'correction', list: ['soft', 'normal', 'strict'] },
    reply_language: { path: 'language', field: 'reply_language', list: ['auto', 'ru', 'en'] }
  };

  async function cycleParam(key) {
    var spec = CYCLES[key];
    if (!spec) return;
    var current = ui.data.ai[spec.field];
    var idx = spec.list.indexOf(current);
    var body = {};
    body[spec.field] = spec.list[(idx + 1) % spec.list.length];
    ui.data.ai = await api('/api/teacher/ai/' + spec.path, { method: 'POST', body: body });
    toast('Сохранено');
    render();
  }

  async function saveCustomRole() {
    var box = document.getElementById('customRole');
    ui.data.ai = await api('/api/teacher/ai/role', {
      method: 'POST',
      body: { role_id: 'custom', text: box ? box.value : '' }
    });
    ui.confirm = null;
    toast('Своя роль сохранена');
    render();
  }

  async function resetAi() {
    ui.data.ai = await api('/api/teacher/ai/reset', { method: 'POST' });
    toast('Параметры сброшены');
    render();
  }

  async function saveTask() {
    var titleBox = document.getElementById('taskTitle');
    var contentBox = document.getElementById('taskContent');
    await api('/api/teacher/tasks', {
      method: 'POST',
      body: {
        title: titleBox ? titleBox.value : '',
        content: contentBox ? contentBox.value : ''
      }
    });
    ui.confirm = null;
    ui.data.tasks = await api('/api/teacher/tasks');
    toast('Задание создано и стало активным');
    render();
  }

  async function setTask(taskId) {
    await api('/api/teacher/tasks/active', { method: 'POST', body: { task_id: taskId } });
    ui.confirm = null;
    ui.data.tasks = await api('/api/teacher/tasks');
    toast(taskId === null ? 'Активное задание снято' : 'Задание сделано активным');
    render();
  }

  function askDelete(studentId) {
    var found = null;
    ui.data.students.items.forEach(function (s) {
      if (s.id === studentId) found = s;
    });
    if (!found) {
      toast('Ученик не найден в списке, обновите экран');
      return;
    }
    ui.confirm = { kind: 'student-delete', id: found.id, name: found.name, hasTopic: found.has_topic, topic: false };
    render();
  }

  async function deleteStudent() {
    var c = ui.confirm;
    if (!c) return;
    var result = await api('/api/teacher/students/' + c.id + '?topic=' + (c.topic ? '1' : '0'), {
      method: 'DELETE'
    });
    ui.confirm = null;
    ui.data.students = await api('/api/teacher/students?page=' + (ui.data.studentPage || 0));
    toast('Ученик ' + result.name + ' удалён. ' + result.topic_note);
    render();
  }

  async function setLimit(value) {
    ui.data.dialog = await api('/api/teacher/dialog/limit', { method: 'POST', body: { reply_limit: value } });
    toast('Сохранено');
    render();
  }

  async function setMode(mode) {
    ui.data.dialog = await api('/api/teacher/dialog/mode', { method: 'POST', body: { goal_mode: mode } });
    toast('Сохранено');
    render();
  }

  async function openModes() {
    var result = await api('/api/teacher/dialog/mode');
    ui.data.modes = result.modes;
    ui.stack.push(ui.view);
    ui.view = 'dialog-modes';
    render();
  }

  async function saveGoal() {
    var box = document.getElementById('goalText');
    var result = await api('/api/teacher/goals', { method: 'POST', body: { text: box ? box.value : '' } });
    ui.confirm = null;
    ui.data.goals = await api('/api/teacher/goals');
    ui.data.dialog = await api('/api/teacher/dialog');
    toast('Цель №' + result.id + ' создана и стала активной');
    render();
  }

  async function pickGoal(goalId) {
    await api('/api/teacher/goals/active', { method: 'POST', body: { goal_id: goalId } });
    ui.data.goals = await api('/api/teacher/goals');
    ui.data.dialog = await api('/api/teacher/dialog');
    toast(goalId === null ? 'Активная цель снята' : 'Активная цель выбрана');
    render();
  }

  function openTopUp() {
    if (tg && typeof tg.openLink === 'function') {
      tg.openLink(TOPUP_URL);
      return;
    }
    window.open(TOPUP_URL, '_blank', 'noopener');
  }

  async function handle(action, ds) {
    switch (action) {
      case 'go': return go(ds.view);
      case 'back': return back();
      case 'refresh': return loadView(ui.view);
      case 'topup': return openTopUp();
      case 'cancel-confirm': ui.confirm = null; return render();

      case 'models-open': return go('models');
      case 'models-role-open':
        ui.data.role = ds.role;
        ui.data.category = ds.role === 'speech' ? 'speech' : 'text';
        ui.data.sort = 'rec';
        ui.data.page = 0;
        return go('models-role');
      case 'models-refresh': return refreshModels();
      case 'models-cat': return loadModels(ds.role, ds.key, ui.data.sort || 'rec', 0).then(render);
      case 'models-sort': return loadModels(ds.role, ui.data.category, ds.key, 0).then(render);
      case 'models-page': return loadModels(ui.data.role, ui.data.category, ui.data.sort, Number(ds.page)).then(render);
      case 'models-pick': return selectModel(ds.id);
      case 'models-reset': return resetModel(ds.role);

      case 'key-ask': ui.confirm = { kind: 'key' }; return render();
      case 'key-save': return saveKey();
      case 'ctx-save': return saveContext();

      case 'bot-add-open': ui.confirm = { kind: 'bot-add' }; return render();
      case 'bot-add': return addBot();
      case 'bot-check-open': ui.confirm = { kind: 'bot-check' }; return render();
      case 'bot-check': return checkBot(ds.key);

      case 'task-new': ui.confirm = { kind: 'task-new' }; return render();
      case 'task-save': return saveTask();
      case 'task-set': return setTask(Number(ds.id));
      case 'task-off': ui.confirm = { kind: 'task-off' }; return render();
      case 'task-off-do': return setTask(null);

      case 'students-page':
        ui.data.studentPage = Number(ds.page) || 0;
        ui.confirm = null;
        return loadView('students');
      case 'student-ask': return askDelete(Number(ds.id));
      case 'student-toggle':
        if (ui.confirm) ui.confirm.topic = !ui.confirm.topic;
        return render();
      case 'student-delete-do': return deleteStudent();

      case 'ai-cycle': return cycleParam(ds.key);
      case 'ai-role-pick': return aiRolePick(ds.id);
      case 'ai-custom-open': ui.confirm = { kind: 'ai-custom' }; return render();
      case 'ai-custom-save': return saveCustomRole();
      case 'ai-reset': return resetAi();

      case 'dlg-limit': return setLimit(Number(ds.value));
      case 'dlg-mode': return setMode(ds.key);
      case 'dlg-modes': return openModes();

      case 'goal-new': ui.confirm = { kind: 'goal-new' }; return render();
      case 'goal-save': return saveGoal();
      case 'goal-pick': return pickGoal(Number(ds.id));
      case 'goal-off': return pickGoal(null);

      default: return undefined;
    }
  }

  async function aiRolePick(roleId) {
    ui.data.ai = await api('/api/teacher/ai/role', { method: 'POST', body: { role_id: roleId } });
    render();
  }

  async function init() {
    if (tg && tg.BackButton) {
      tg.BackButton.onClick(function () { run(back); });
    }
    root.addEventListener('click', function (event) {
      var el = event.target.closest('[data-action]');
      if (!el || el.disabled) return;
      run(function () { return handle(el.dataset.action, el.dataset); });
    });
    try {
      ui.data.status = await api('/api/teacher/status');
      render();
    } catch (err) {
      root.innerHTML = '<section class="card"><p>' + esc(err.message) + '</p></section>';
    }
  }

  init();
})();
