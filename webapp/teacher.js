'use strict';

/* Панель преподавателя: статус, задания, ученики. Каждый запрос подписан initData Telegram. */
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
    status: 'Статус',
    tasks: 'Задания',
    students: 'Ученики'
  };
  var BOT_STATES = {
    running: 'работает',
    starting: 'запускается',
    stopped: 'остановлен',
    error: 'ошибка',
    unknown: 'неизвестно'
  };

  var ui = {
    view: 'status',
    status: null,
    tasks: null,
    students: null,
    studentPage: 0,
    taskForm: false,
    confirm: null,
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
    var attrs = ' data-action="' + action + '"';
    ['view', 'id', 'page'].forEach(function (key) {
      if (o[key] !== undefined && o[key] !== null) {
        attrs += ' data-' + key + '="' + esc(o[key]) + '"';
      }
    });
    return '<button class="btn ' + (o.kind || '') + '"' + attrs + (o.disabled ? ' disabled' : '') + '>' +
      esc(label) + '</button>';
  }

  function tabs() {
    return '<div class="row">' +
      btn('Статус', 'go', { view: 'status' }) +
      btn('Задания', 'go', { view: 'tasks' }) +
      btn('Ученики', 'go', { view: 'students' }) +
      '</div>';
  }

  function statusHtml() {
    var s = ui.status;
    if (!s) {
      return '<p class="muted">Нет данных.</p>';
    }
    var bot = s.bot;
    var state = BOT_STATES[bot.state] || bot.state;
    var username = bot.username ? ' (@' + esc(bot.username) + ')' : '';
    var errorLine = bot.error ? '<p class="muted">' + esc(bot.error) + '</p>' : '';
    var task = s.active_task ? '№' + s.active_task.id + ' «' + esc(s.active_task.title) + '»' : 'нет';
    var goal = s.active_goal ? '№' + s.active_goal.id + ' «' + esc(s.active_goal.text) + '»' : 'не задана';
    return '<section class="card">' +
      '<h2>Состояние</h2>' +
      '<p>Основной бот: <b>' + esc(state) + '</b>' + username + '</p>' +
      errorLine +
      '<p>Ключ Polza.ai: <b>' + (s.polza_key ? esc(s.polza_key) : 'не задан') + '</b></p>' +
      '<p>Активное задание: ' + task + '</p>' +
      '<p>Ответов нейросети в диалоге: <b>' + esc(s.reply_limit) + '</b></p>' +
      '<p>Режим проверки цели: <b>' + esc(s.goal_mode) + '</b></p>' +
      '<p>Активная цель: ' + goal + '</p>' +
      '</section>' +
      '<div class="row">' + btn('Обновить', 'refresh') + '</div>' +
      '<p class="muted">Ключ показан маской. Изменение настроек, моделей и параметров ИИ будет добавлено в следующих частях.</p>';
  }

  function taskFormHtml() {
    return '<section class="card">' +
      '<h2>Новое задание</h2>' +
      '<input id="taskTitle" class="input" maxlength="100" placeholder="Название">' +
      '<textarea id="taskContent" class="input" rows="6" maxlength="2000" placeholder="Условие задания"></textarea>' +
      '<div class="row">' +
      btn('Создать и сделать активным', 'task-save', { kind: 'primary' }) +
      btn('Отмена', 'task-cancel') +
      '</div>' +
      '</section>';
  }

  function tasksHtml() {
    var t = ui.tasks;
    if (!t) {
      return '<p class="muted">Нет данных.</p>';
    }
    var list = t.items.length
      ? t.items.map(function (task) {
        var mark = task.id === t.active_id ? '✓ ' : '';
        return btn(mark + '№' + task.id + ' ' + task.title, 'task-set', { id: task.id });
      }).join('')
      : '<p class="muted">Заданий пока нет.</p>';
    var form = ui.taskForm ? taskFormHtml() : '';
    return form +
      '<div class="row">' +
      btn('Новое задание', 'task-new', { kind: 'primary' }) +
      btn('Снять активное', 'task-off', { kind: 'danger' }) +
      '</div>' +
      '<p class="muted">Нажмите задание, чтобы сделать его активным. Ученики видят только активное.</p>' +
      '<div class="menu">' + list + '</div>';
  }

  function confirmHtml() {
    var c = ui.confirm;
    var toggle = c.has_topic
      ? '<p>Удалить топик в группе: <b>' + (c.topic ? 'да' : 'нет') + '</b></p>' +
        '<div class="row">' +
        btn(c.topic ? 'Не удалять топик' : 'Удалить топик в группе', 'student-toggle') +
        '</div>'
      : '<p class="muted">Топика в группе нет.</p>';
    return '<section class="card">' +
      '<h2>Удалить ученика</h2>' +
      '<p>Удалить ученика ' + esc(c.name) + '? История и оценки будут удалены, открытый диалог отменён.</p>' +
      '<p class="muted">Сообщения в личном чате ученика с ботом не удаляются. ' +
      'После удаления ему нужно отправить /start, чтобы пройти регистрацию заново.</p>' +
      toggle +
      '<div class="row">' +
      btn('Да, удалить', 'student-delete', { kind: 'danger' }) +
      btn('Отмена', 'student-cancel') +
      '</div>' +
      '</section>';
  }

  function studentsHtml() {
    if (ui.confirm) {
      return confirmHtml();
    }
    var st = ui.students;
    if (!st) {
      return '<p class="muted">Нет данных.</p>';
    }
    var head = st.total
      ? '<p class="muted">Зарегистрировано: ' + st.total + '. Страница ' + (st.page + 1) + ' из ' + st.pages + '.</p>'
      : '<p class="muted">Зарегистрированных учеников пока нет.</p>';
    var cards = st.items.map(function (s) {
      var handle = s.username ? ' · @' + esc(s.username) : '';
      var topic = s.has_topic ? 'топик есть' : 'без топика';
      return '<section class="card">' +
        '<b>' + esc(s.name) + '</b>' +
        '<p class="muted">' + handle.replace(/^ · /, '') + (handle ? ' · ' : '') + topic + '</p>' +
        '<div class="row">' + btn('Удалить', 'student-ask', { id: s.id, kind: 'danger' }) + '</div>' +
        '</section>';
    }).join('');
    var nav = '';
    if (st.page > 0) {
      nav += btn('‹ Назад', 'students-page', { page: st.page - 1 });
    }
    if (st.page < st.pages - 1) {
      nav += btn('Дальше ›', 'students-page', { page: st.page + 1 });
    }
    return head + cards + (nav ? '<div class="row">' + nav + '</div>' : '');
  }

  function render() {
    titleEl.textContent = TITLES[ui.view] || 'Панель преподавателя';
    var views = { status: statusHtml, tasks: tasksHtml, students: studentsHtml };
    root.innerHTML = tabs() + (views[ui.view] || statusHtml)();
  }

  async function fetchStudents(page) {
    var data = await api('/api/teacher/students?page=' + page);
    ui.students = data;
    ui.studentPage = data.page;
  }

  async function go(view) {
    ui.view = view;
    ui.taskForm = false;
    ui.confirm = null;
    if (view === 'status') {
      ui.status = await api('/api/teacher/status');
    } else if (view === 'tasks') {
      ui.tasks = await api('/api/teacher/tasks');
    } else if (view === 'students') {
      await fetchStudents(ui.studentPage);
    }
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
    ui.taskForm = false;
    ui.tasks = await api('/api/teacher/tasks');
    toast('Задание создано и стало активным');
    render();
  }

  async function setActive(taskId) {
    await api('/api/teacher/tasks/active', { method: 'POST', body: { task_id: taskId } });
    ui.tasks = await api('/api/teacher/tasks');
    toast(taskId === null ? 'Активное задание снято' : 'Задание сделано активным');
    render();
  }

  function askDelete(studentId) {
    var found = null;
    if (ui.students) {
      ui.students.items.forEach(function (s) {
        if (s.id === studentId) {
          found = s;
        }
      });
    }
    if (!found) {
      toast('Ученик не найден в списке, обновите экран');
      return;
    }
    ui.confirm = { id: found.id, name: found.name, has_topic: found.has_topic, topic: false };
    render();
  }

  async function deleteStudent() {
    var c = ui.confirm;
    if (!c) {
      return;
    }
    var result = await api('/api/teacher/students/' + c.id + '?topic=' + (c.topic ? '1' : '0'), {
      method: 'DELETE'
    });
    ui.confirm = null;
    await fetchStudents(ui.studentPage);
    toast('Ученик ' + result.name + ' удалён. ' + result.topic_note);
    render();
  }

  async function handle(action, ds) {
    switch (action) {
      case 'go':
        return go(ds.view);
      case 'refresh':
        return go(ui.view);
      case 'task-new':
        ui.taskForm = true;
        return render();
      case 'task-cancel':
        ui.taskForm = false;
        return render();
      case 'task-save':
        return saveTask();
      case 'task-set':
        return setActive(Number(ds.id));
      case 'task-off':
        return setActive(null);
      case 'students-page':
        ui.confirm = null;
        await fetchStudents(Number(ds.page) || 0);
        return render();
      case 'student-ask':
        return askDelete(Number(ds.id));
      case 'student-toggle':
        if (ui.confirm) {
          ui.confirm.topic = !ui.confirm.topic;
        }
        return render();
      case 'student-cancel':
        ui.confirm = null;
        return render();
      case 'student-delete':
        return deleteStudent();
      default:
        return undefined;
    }
  }

  async function init() {
    root.addEventListener('click', function (event) {
      var el = event.target.closest('[data-action]');
      if (!el || el.disabled) {
        return;
      }
      run(function () { return handle(el.dataset.action, el.dataset); });
    });
    try {
      await go('status');
    } catch (err) {
      root.innerHTML = '<section class="card"><p>' + esc(err.message) + '</p></section>';
    }
  }

  init();
})();
