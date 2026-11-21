'use strict';

/* Mini App LinguaBot: экраны ученика. Каждый запрос подписан initData Telegram. */
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

  var TITLES = {
    home: 'LinguaBot',
    task: 'Текущее задание',
    role: 'Роль ассистента',
    help: 'Инструкция',
    chat: 'Диалог',
    history: 'История диалогов',
    dialog: 'История диалога',
    report: 'Итог диалога'
  };

  var INSTRUCTION = [
    'Инструкция',
    '',
    '1. Вопросы: пишите вопросы по английскому в чат. Нейросеть ответит и поможет разобраться с ошибками.',
    '2. Задание: откройте «Текущее задание», чтобы увидеть условие и требования.',
    '3. Ответ: нажмите «Ответить на задание». Нейросеть отвечает и задаёт уточняющие вопросы.',
    '4. Завершение: диалог закончится, когда исчерпан лимит ответов нейросети. ' +
      'Досрочно — кнопка «Завершить диалог». Затем выставляется оценка по шкале 1–5.',
    '5. Роль: «Роль ассистента» покажет, в каком режиме сейчас работает нейросеть.',
    '6. Переписка: ваши сообщения и ответы дублируются в личный топик, который видит преподаватель.',
    '',
    'Голосовые сообщения распознаются в боте, в приложении пока доступен текст.'
  ].join('\n');

  var ui = {
    state: null,
    view: 'home',
    chat: null,
    history: null,
    dialog: null,
    report: '',
    historyPage: 0,
    busy: false
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
    var data = ' data-action="' + action + '"';
    if (o.view !== undefined) data += ' data-view="' + o.view + '"';
    if (o.id !== undefined) data += ' data-id="' + o.id + '"';
    if (o.page !== undefined) data += ' data-page="' + o.page + '"';
    return '<button class="btn ' + (o.kind || '') + '"' + data + (o.disabled ? ' disabled' : '') + '>' +
      esc(label) + '</button>';
  }

  function backBtn() {
    return '<div class="row">' + btn('Назад', 'back') + '</div>';
  }

  function bubble(message) {
    return '<div class="bubble ' + (message.role === 'user' ? 'me' : 'bot') + '">' +
      esc(message.content) + '</div>';
  }

  async function loadState() {
    ui.state = await api('/api/student/state');
  }

  async function go(view) {
    ui.view = view;
    if (view === 'chat') {
      ui.chat = await api('/api/student/chat');
    }
    render();
  }

  async function openHistory(page) {
    ui.historyPage = page || 0;
    ui.history = await api('/api/student/dialogs?page=' + ui.historyPage);
    ui.view = 'history';
    render();
  }

  async function openDialog(id) {
    ui.dialog = await api('/api/student/dialogs/' + encodeURIComponent(id));
    ui.view = 'dialog';
    render();
  }

  async function back() {
    if (ui.view === 'dialog') {
      return openHistory(ui.historyPage);
    }
    return go('home');
  }

  function registerHtml() {
    return '<section class="card">' +
      '<h2>Регистрация</h2>' +
      '<p>Напишите имя и фамилию. Для вас создастся личный топик, который видит преподаватель.</p>' +
      '<input id="fullName" class="input" maxlength="64" placeholder="Имя и фамилия" autocomplete="name">' +
      '<div class="row">' + btn('Зарегистрироваться', 'register', { kind: 'primary' }) + '</div>' +
      '</section>';
  }

  function homeHtml() {
    var s = ui.state;
    var d = s.dialog;
    var actions = '';
    if (!s.ready) {
      actions += '<p class="info">Преподаватель ещё не подключил ключ Polza.ai. ' +
        'Диалог и чат временно недоступны.</p>';
    }
    if (d && d.status === 'active') {
      actions += btn('Продолжить диалог', 'go', { view: 'chat', kind: 'primary' });
      actions += btn('Завершить диалог', 'finish', { kind: 'danger' });
    } else if (d && d.status === 'ended') {
      actions += btn('Получить оценку', 'finish', { kind: 'primary' });
    } else {
      actions += btn('Ответить на задание', 'start', {
        kind: 'primary',
        disabled: !s.task || !s.ready
      });
    }
    actions += btn('Чат с нейросетью', 'go', { view: 'chat' });
    actions += btn('Текущее задание', 'go', { view: 'task' });
    actions += btn('История диалогов', 'history', { page: 0 });
    actions += btn('Роль ассистента', 'go', { view: 'role' });
    actions += btn('Инструкция', 'go', { view: 'help' });

    var taskLine = s.task
      ? 'Активное задание: <b>' + esc(s.task.title) + '</b>'
      : 'Активного задания пока нет.';
    return '<section class="card">' +
      '<p class="muted">Здравствуйте, ' + esc(s.full_name) + '!</p>' +
      '<p>' + taskLine + '</p>' +
      '</section>' +
      '<div class="menu">' + actions + '</div>';
  }

  function taskHtml() {
    var s = ui.state;
    var requirements = s.context
      ? '<h3>Требования преподавателя</h3><div class="pre">' + esc(s.context) + '</div>'
      : '<p class="muted">Преподаватель пока не задал требования.</p>';
    var task = s.task
      ? '<h3>' + esc(s.task.title) + '</h3><div class="pre">' + esc(s.task.content) + '</div>'
      : '<p class="muted">Активного задания пока нет.</p>';
    return '<section class="card">' + requirements + task + '</section>' + backBtn();
  }

  function roleHtml() {
    var role = ui.state.role;
    return '<section class="card">' +
      '<p>Сейчас ассистент работает в роли «' + esc(role.name) + '».</p>' +
      '<div class="pre">' + esc(role.text) + '</div>' +
      '</section>' + backBtn();
  }

  function helpHtml() {
    return '<section class="card"><div class="pre">' + esc(INSTRUCTION) + '</div></section>' + backBtn();
  }

  function chatHtml() {
    var s = ui.state;
    var d = s.dialog;
    var messages = (ui.chat && ui.chat.messages) || [];
    var head;
    if (d && d.status === 'active') {
      head = '<p class="info">Диалог по заданию. Ответов нейросети: ' +
        d.replies_used + ' из ' + d.reply_limit + '.</p>';
    } else if (d && d.status === 'ended') {
      head = '<p class="info">Диалог завершён и ждёт оценки. Нажмите «Завершить диалог».</p>';
    } else {
      head = '<p class="info">Свободный чат. Вопросы по английскому, история сохраняется.</p>';
    }
    var canSend = s.ready && !(d && d.status === 'ended');
    var list = messages.map(bubble).join('') || '<p class="muted">Сообщений пока нет.</p>';
    var disabled = canSend ? '' : ' disabled';
    var finish = d && d.status !== 'graded' ? btn('Завершить диалог', 'finish', { kind: 'danger' }) : '';

    return head +
      '<div class="messages" id="messages">' + list + '</div>' +
      '<div class="composer">' +
      '<textarea id="msg" class="input" rows="2" maxlength="2000" placeholder="Напишите сообщение"' +
      disabled + '></textarea>' +
      '<button class="btn primary" data-action="send"' + disabled + '>Отправить</button>' +
      '</div>' +
      '<div class="row">' + btn('Меню', 'go', { view: 'home' }) + finish + '</div>';
  }

  function historyHtml() {
    var h = ui.history;
    var items = h.items.length
      ? h.items.map(function (item) {
        return btn(item.label, 'dialog', { id: item.id });
      }).join('')
      : '<p class="muted">Завершённых диалогов пока нет.</p>';
    var nav = '';
    if (h.page > 0) {
      nav += btn('‹ Назад', 'history', { page: h.page - 1 });
    }
    if (h.page < h.pages - 1) {
      nav += btn('Дальше ›', 'history', { page: h.page + 1 });
    }
    return '<p class="muted">Страница ' + (h.page + 1) + ' из ' + h.pages + '.</p>' +
      '<div class="menu">' + items + '</div>' +
      '<div class="row">' + nav + '</div>' +
      backBtn();
  }

  function dialogHtml() {
    var d = ui.dialog;
    var messages = d.messages.map(bubble).join('') || '<p class="muted">Реплик нет.</p>';
    return '<h3>' + esc(d.label) + '</h3>' +
      '<div class="messages">' + messages + '</div>' +
      '<h3>Итог</h3>' +
      '<div class="card pre">' + esc(d.report) + '</div>' +
      backBtn();
  }

  function reportHtml() {
    return '<section class="card"><div class="pre">' + esc(ui.report) + '</div></section>' +
      '<div class="row">' + btn('В меню', 'go', { view: 'home', kind: 'primary' }) + '</div>';
  }

  function render() {
    if (tg && tg.BackButton) {
      if (ui.view === 'home') {
        tg.BackButton.hide();
      } else {
        tg.BackButton.show();
      }
    }
    titleEl.textContent = TITLES[ui.view] || 'LinguaBot';
    var s = ui.state;
    if (!s) {
      return;
    }
    if (!s.registered) {
      root.innerHTML = registerHtml();
      return;
    }
    var views = {
      home: homeHtml,
      task: taskHtml,
      role: roleHtml,
      help: helpHtml,
      chat: chatHtml,
      history: historyHtml,
      dialog: dialogHtml,
      report: reportHtml
    };
    root.innerHTML = (views[ui.view] || homeHtml)();
    if (ui.view === 'chat') {
      var box = document.getElementById('messages');
      if (box) {
        box.scrollTop = box.scrollHeight;
      }
    }
  }

  async function doRegister() {
    var input = document.getElementById('fullName');
    ui.state = await api('/api/student/register', {
      method: 'POST',
      body: { full_name: input ? input.value : '' }
    });
    toast('Регистрация завершена');
    ui.view = 'home';
    render();
  }

  async function doStart() {
    var result = await api('/api/student/dialog', { method: 'POST' });
    ui.state = result.state;
    toast(result.notice || 'Диалог начат');
    await go('chat');
  }

  async function doFinish() {
    var result = await api('/api/student/dialog/finish', { method: 'POST' });
    ui.state = await api('/api/student/state');
    if (result.report) {
      ui.report = result.report;
      ui.view = 'report';
      render();
      return;
    }
    toast(result.notice || 'Диалог завершён');
    ui.view = 'home';
    render();
  }

  async function doSend() {
    var box = document.getElementById('msg');
    var text = box ? box.value.trim() : '';
    if (!text) {
      toast('Напишите сообщение');
      return;
    }
    var result = await api('/api/student/message', { method: 'POST', body: { text: text } });
    if (box) {
      box.value = '';
    }
    ui.state = await api('/api/student/state');
    if (result.finished && result.report) {
      ui.report = result.report;
      ui.view = 'report';
      render();
      return;
    }
    ui.chat = await api('/api/student/chat');
    if (result.notice) {
      toast(result.notice);
    }
    ui.view = 'chat';
    render();
  }

  async function handle(action, ds) {
    switch (action) {
      case 'register': return doRegister();
      case 'go': return go(ds.view);
      case 'back': return back();
      case 'start': return doStart();
      case 'finish': return doFinish();
      case 'send': return doSend();
      case 'history': return openHistory(Number(ds.page) || 0);
      case 'dialog': return openDialog(ds.id);
      default: return undefined;
    }
  }

  async function init() {
    if (tg && tg.BackButton) {
      tg.BackButton.onClick(function () { run(back); });
    }
    root.addEventListener('click', function (event) {
      var el = event.target.closest('[data-action]');
      if (!el || el.disabled) {
        return;
      }
      run(function () { return handle(el.dataset.action, el.dataset); });
    });
    try {
      await loadState();
      render();
    } catch (err) {
      root.innerHTML = '<section class="card"><p>' + esc(err.message) + '</p></section>';
    }
  }

  init();
})();
