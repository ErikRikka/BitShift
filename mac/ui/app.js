'use strict';

const $ = (id) => document.getElementById(id);

let state = null;
let lastSignature = '';

const UI = {
  hint_picker: {
    ru: 'В «Обзоре…» можно взять и папки, и отдельные файлы',
    en: 'The picker takes whole folders and single files',
  },
  opt_recursive: { ru: 'Подпапки', en: 'Subfolders' },
  toolbar_select_all: { ru: 'выбрать все видимые', en: 'select all visible' },
  filter_all: { ru: 'Все', en: 'All' },
  filter_bad: { ru: 'Брак', en: 'Rejected' },
  filter_skip: { ru: 'Пропущено', en: 'Skipped' },
  opt_shutdown: { ru: 'Выключить мак после конвертации', en: 'Shut down the Mac when finished' },
  opt_eject: { ru: 'Извлечь диск(и) после конвертации', en: 'Eject the volume(s) when finished' },
  opt_vmaf: { ru: 'Проверять качество (VMAF) — медленнее', en: 'Check quality (VMAF) — slower' },
  opt_trash: { ru: 'Удалять исходники в Корзину после проверки', en: 'Move originals to Trash after verifying' },
  btn_browse: { ru: 'Обзор…', en: 'Browse…' },
  btn_refresh: { ru: 'Обновить', en: 'Refresh' },
  btn_start: { ru: 'Старт', en: 'Start' },
  btn_pause: { ru: 'Пауза', en: 'Pause' },
  btn_resume: { ru: 'Продолжить', en: 'Resume' },
  btn_stop: { ru: 'Стоп', en: 'Stop' },
  btn_stopping: { ru: 'Останавливаю…', en: 'Stopping…' },
  btn_encoding: { ru: 'Кодирую {percent}%', en: 'Encoding {percent}%' },
  btn_paused: { ru: 'На паузе', en: 'Paused' },
  btn_cancel: { ru: 'Отмена', en: 'Cancel' },
  btn_close: { ru: 'Закрыть', en: 'Close' },
  btn_to_trash: { ru: 'В Корзину', en: 'Move to Trash' },
  btn_cancel_shutdown: { ru: 'Не выключать', en: 'Keep it on' },
  btn_got_it: { ru: 'Понятно', en: 'Got it' },
  shutdown_failed: { ru: 'Выключить мак не вышло: {error}', en: 'Could not shut the Mac down: {error}' },
  shutdown_in: { ru: 'Мак выключится через {clock}', en: 'The Mac shuts down in {clock}' },
  group_mode: { ru: 'Режим', en: 'Mode' },
  group_codec: { ru: 'Кодек', en: 'Codec' },
  group_audio: { ru: 'Звук', en: 'Audio' },
  group_volume: { ru: 'Объём', en: 'Size' },
  group_left: { ru: 'Осталось', en: 'Remaining' },
  vol_source: { ru: 'Объём исходников', en: 'Source size' },
  vol_forecast: { ru: 'После сжатия', en: 'After encoding' },
  vol_saved: { ru: 'Сэкономлено', en: 'Saved' },
  vol_left: { ru: 'Примерно', en: 'About' },
  settings_title: { ru: 'Настройки', en: 'Settings' },
  settings_lang: { ru: 'Язык', en: 'Language' },
  settings_author: { ru: 'Создано: Эрик Рикка', en: 'Created by Erik Rikka' },
  pick_folder: { ru: 'Выберите папку', en: 'Choose a folder' },
  no_folder: { ru: 'Папка не выбрана', en: 'No folder selected' },
  empty_title: { ru: 'Ничего не выбрано', en: 'Nothing selected' },
  empty_text: {
    ru: 'Нажмите «Обзор…» и выберите папки или отдельные файлы.',
    en: 'Press “Browse…” and pick folders or single files.',
  },
  none_title: { ru: 'Подходящих файлов нет', en: 'No matching files' },
  none_text: {
    ru: 'Проверьте режим — у каждого свои расширения — или включите подпапки.',
    en: 'Check the mode — each takes its own extensions — or turn on subfolders.',
  },
  recursive_off: {
    ru: 'Выбраны отдельные файлы — заходить в подпапки не в чем',
    en: 'Single files are selected — there are no subfolders to walk',
  },
  trash_some: { ru: 'Удалить проверенные ({n}) в Корзину…', en: 'Move verified ({n}) to Trash…' },
  trash_none: { ru: 'Удалить проверенные в Корзину…', en: 'Move verified to Trash…' },
  ask_trash_title: { ru: 'Удалить проверенные в Корзину?', en: 'Move verified originals to Trash?' },
  ask_trash_text: {
    ru: '{n} оригиналов уйдут в Корзину. Все они прошли полную проверку: кодек, длительность, число кадров и полный декод. Безвозвратно ничего не удаляется.',
    en: '{n} originals will go to the Trash. All of them passed the full check: codec, duration, frame count and a complete decode. Nothing is deleted permanently.',
  },
  ask_start_title: { ru: 'Удалять исходники в Корзину?', en: 'Move originals to Trash?' },
  ask_start_text: {
    ru: 'Оригиналы {n} файлов уйдут в Корзину — но только те, что полностью пройдут проверку. Файлы с браком останутся на месте. Безвозвратно ничего не удаляется.',
    en: 'Originals of {n} files will go to the Trash — but only those that pass the full check. Rejected files stay where they are. Nothing is deleted permanently.',
  },
};

function ui(key, params) {
  const entry = UI[key];
  if (!entry) return key;
  const lang = (state && state.lang) || 'ru';
  let text = entry[lang] || entry.ru || '';
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.replace(new RegExp(`\\{${name}\\}`, 'g'), value);
    }
  }
  return text;
}

function applyStaticText() {
  document.documentElement.lang = (state && state.lang) || 'ru';
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = ui(el.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-title]').forEach((el) => {
    el.title = ui(el.dataset.i18nTitle);
  });
}

const BADGE_KIND = {
  waiting: 'idle', skipped: 'idle', queued: 'idle', encoded: 'idle', stopped: 'idle',
  copying: 'busy', encoding: 'busy', verifying: 'busy', verified: 'busy', moving: 'busy',
  done: 'ok', trashed: 'ok',
  failed: 'bad',
};

const STAGE = {
  copying: 'copy',
  encoding: 'encode',
  verifying: 'verify',
  moving: 'move',
};

function badgeText(file) {
  const label = file.state_label || file.state;
  if (STAGE[file.state_key] && file.progress > 0) {
    return `${label} ${Math.round(file.progress * 100)}%`;
  }
  return label;
}

function renderChoiceList(host, items, currentKey, onPick) {
  host.textContent = '';
  host.setAttribute('role', 'radiogroup');
  const pickable = items.filter((i) => i.available !== false);

  const move = (from, dir) => {
    const idx = pickable.indexOf(from);
    if (idx === -1) return;
    const next = pickable[(idx + dir + pickable.length) % pickable.length];
    onPick(next.key);
    requestAnimationFrame(() => host.querySelector('[aria-checked="true"]')?.focus());
  };

  for (const item of items) {
    const el = document.createElement('div');
    const isOn = item.key === currentKey;
    const isOff = item.available === false;
    el.className = 'item' + (isOn ? ' item--on' : '') + (isOff ? ' item--off' : '');
    el.title = item.hint || item.note || '';
    el.innerHTML = `<span class="item__name">${escapeHtml(item.name)}</span>`
      + (item.note ? `<span class="item__note">${escapeHtml(item.note)}</span>` : '');
    if (!isOff) {
      el.setAttribute('role', 'radio');
      el.setAttribute('aria-checked', String(isOn));
      el.tabIndex = isOn ? 0 : -1;
      el.addEventListener('click', () => onPick(item.key));
      el.addEventListener('keydown', (e) => {
        if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); onPick(item.key); }
        else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') { e.preventDefault(); move(item, 1); }
        else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') { e.preventDefault(); move(item, -1); }
      });
    }
    host.appendChild(el);
  }
}

let activeFilter = 'all';

function matchesFilter(file, filter) {
  if (filter === 'bad') return file.state_key === 'failed';
  if (filter === 'skip') return file.state_key === 'skipped';
  return true;
}

function renderToolbar(files) {
  const bar = $('toolbar');
  if (!bar) return;
  bar.hidden = !files.length;
  if (!files.length) return;

  const running = state && state.running;
  const counts = { all: files.length, bad: 0, skip: 0 };
  for (const f of files) {
    if (f.state_key === 'failed') counts.bad += 1;
    if (f.state_key === 'skipped') counts.skip += 1;
  }
  $('chip-all').textContent = `${ui('filter_all')} · ${counts.all}`;
  $('chip-bad').textContent = `${ui('filter_bad')} · ${counts.bad}`;
  $('chip-bad').hidden = counts.bad === 0;
  $('chip-skip').textContent = `${ui('filter_skip')} · ${counts.skip}`;
  $('chip-skip').hidden = counts.skip === 0;
  for (const btn of bar.querySelectorAll('.chip')) {
    btn.classList.toggle('chip--on', btn.dataset.filter === activeFilter);
  }
  if (activeFilter !== 'all' && counts[activeFilter] === 0) {
    activeFilter = 'all';
    $('chip-all').classList.add('chip--on');
    $('chip-bad').classList.remove('chip--on');
    $('chip-skip').classList.remove('chip--on');
  }

  const visible = files.filter((f) => matchesFilter(f, activeFilter) && !f.skipped);
  const selectable = visible.filter((f) => f.selected || !running);
  const allOn = selectable.length > 0 && selectable.every((f) => f.selected);
  const selAll = $('sel-all');
  selAll.checked = allOn;
  selAll.disabled = running || selectable.length === 0;
}

function renderFiles(files) {
  const host = $('files');
  host.textContent = '';
  renderToolbar(files);

  if (!files.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    const title = state && state.folder ? ui('none_title') : ui('empty_title');
    const text = state && state.folder ? ui('none_text') : ui('empty_text');
    empty.innerHTML = `<div class="empty__title">${escapeHtml(title)}</div>`
      + `<div class="empty__text">${escapeHtml(text)}</div>`;
    host.appendChild(empty);
    return;
  }

  const running = state && state.running;
  const shown = files.filter((f) => matchesFilter(f, activeFilter));

  for (const file of shown) {
    const row = document.createElement('div');
    row.className = 'row' + (file.selected ? '' : ' row--off');

    const check = document.createElement('label');
    check.className = 'check';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = file.selected;
    box.disabled = running || file.skipped;
    box.addEventListener('change', () => {
      window.pywebview.api.toggle_file(file.path, box.checked).then(applyFromApi);
    });
    check.appendChild(box);
    const boxUi = document.createElement('span');
    boxUi.className = 'check__box';
    check.appendChild(boxUi);
    row.appendChild(check);

    const info = document.createElement('div');
    info.style.minWidth = '0';
    const detailHtml = file.state_key === 'failed'
      ? `<div class="row__err"><span>${escapeHtml(file.detail)}</span></div>`
      : `<div class="row__detail">${escapeHtml(file.detail)}</div>`;
    info.innerHTML = `<div class="row__name">${escapeHtml(file.label)}</div>` + detailHtml;
    row.appendChild(info);

    const size = document.createElement('div');
    size.className = 'row__size';
    size.textContent = file.size_text;
    row.appendChild(size);

    const badge = document.createElement('div');
    const kind = BADGE_KIND[file.state_key] || 'idle';
    const stage = STAGE[file.state_key];
    badge.className = `badge badge--${kind}` + (stage ? ` badge--${stage}` : '');
    badge.title = file.message || '';
    const fill = document.createElement('div');
    fill.className = 'badge__fill';
    if (stage) fill.style.width = `${Math.round(file.progress * 100)}%`;
    badge.appendChild(fill);
    const text = document.createElement('span');
    text.className = 'badge__text';
    text.textContent = badgeText(file);
    badge.appendChild(text);
    row.appendChild(badge);

    host.appendChild(row);
  }
}

function renderLanguages() {
  const host = $('lang-list');
  if (!host || !state || !state.languages) return;
  host.textContent = '';
  for (const item of state.languages) {
    const el = document.createElement('div');
    el.className = 'seg__item' + (item.key === state.lang ? ' seg__item--on' : '');
    el.textContent = item.name;
    el.addEventListener('click', () => {
      window.pywebview.api.set_lang(item.key).then(applyFromApi);
    });
    host.appendChild(el);
  }
}

function render() {
  if (!state) return;

  $('hardware').textContent = state.hardware;

  renderChoiceList($('modes'), state.modes, state.mode, (key) => {
    window.pywebview.api.set_mode(key).then(applyFromApi);
  });
  renderChoiceList($('codecs'), state.codecs, state.codec, (key) => {
    window.pywebview.api.set_codec(key).then(applyFromApi);
  });
  renderChoiceList($('audio-modes'), state.audio_modes || [], state.audio, (key) => {
    window.pywebview.api.set_audio(key).then(applyFromApi);
  });

  applyStaticText();
  $('folder-name').textContent = state.folder_name || ui('pick_folder');
  $('folder-meta').textContent = state.folder_meta;
  $('folder-path').textContent = state.folder_short || ui('no_folder');
  $('folder-path').title = state.folder || '';

  $('volume-source').textContent = state.source_text;
  $('volume-forecast-row').hidden = !state.forecast_text;
  $('volume-forecast').textContent = state.forecast_text || '';
  const savedRow = $('volume-saved-row');
  savedRow.hidden = !state.saved_text;
  $('volume-saved').textContent = state.saved_text;

  $('left').hidden = !state.left_text;
  $('volume-left').textContent = state.left_text || '';

  renderFiles(state.files);

  $('progress-fill').style.width = `${Math.round(state.percent * 100)}%`;
  $('summary').textContent = state.summary;

  $('opt-recursive').checked = state.recursive;
  $('opt-shutdown').checked = state.shutdown_after;
  $('opt-eject').checked = state.eject_after;
  $('opt-vmaf').checked = state.measure_quality;
  $('opt-trash').checked = state.trash;

  $('history-row').hidden = !state.history_text;
  $('history-value').textContent = state.history_text || '';

  $('opt-recursive').disabled = state.running || state.files_only;
  $('opt-recursive').closest('.check').title = state.files_only ? ui('recursive_off') : '';
  $('opt-shutdown').disabled = state.running;
  $('opt-eject').disabled = state.running;
  $('opt-vmaf').disabled = state.running;
  $('opt-trash').disabled = state.running || !state.trash_available;

  renderShutdown();

  $('btn-browse').disabled = state.running;
  $('btn-refresh').disabled = state.running || !state.folder;
  renderStartButton();

  $('btn-pause').disabled = !state.running || state.stopping;
  $('btn-pause').textContent = state.paused ? ui('btn_resume') : ui('btn_pause');
  $('btn-stop').disabled = !state.running || state.stopping;
  $('btn-stop').textContent = state.stopping ? ui('btn_stopping') : ui('btn_stop');

  const trashBtn = $('btn-trash');
  trashBtn.disabled = state.running || state.trashable === 0 || !state.trash_available;
  trashBtn.textContent = state.trashable
    ? ui('trash_some', { n: state.trashable })
    : ui('trash_none');
  $('app-version').textContent = state.version || '';
  renderLanguages();
}

function renderStartButton() {
  const btn = $('btn-start');
  btn.disabled = state.running || !state.can_start;
  const working = state.running && !state.paused && !state.stopping;
  btn.classList.toggle('btn--working', working);

  let label = ui('btn_start');
  if (working) label = ui('btn_encoding', { percent: Math.round(state.percent * 100) });
  else if (state.running && state.paused) label = ui('btn_paused');

  if (!working) {
    btn.textContent = label;
    return;
  }
  let spin = btn.querySelector('.btn__spin');
  if (!spin) {
    btn.textContent = '';
    spin = document.createElement('span');
    spin.className = 'btn__spin';
    const text = document.createElement('span');
    text.className = 'btn__label';
    btn.append(spin, text);
  }
  btn.querySelector('.btn__label').textContent = label;
}

function clockText(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function renderShutdown() {
  const box = $('shutdown');
  const left = state.shutdown_in;

  if (left === null || left === undefined) {

    if (state.shutdown_error) {
      box.hidden = false;
      box.classList.add('shutdown--failed');
      $('shutdown-text').textContent = ui('shutdown_failed', { error: state.shutdown_error });
      $('btn-cancel-shutdown').textContent = ui('btn_got_it');
      return;
    }
    box.hidden = true;
    return;
  }

  box.hidden = false;
  box.classList.remove('shutdown--failed');
  $('shutdown-text').textContent = ui('shutdown_in', { clock: clockText(left) });
  $('btn-cancel-shutdown').textContent = ui('btn_cancel_shutdown');
}

function applyFromApi(payload) {
  if (!payload) return;
  state = payload;
  render();
}

window.applyState = function (payload) {
  const signature = JSON.stringify(payload);
  if (signature === lastSignature) return;
  lastSignature = signature;
  state = payload;
  render();
};

let confirmAction = null;

function askConfirm(title, text, action) {
  $('modal-title').textContent = title;
  $('modal-text').textContent = text;
  confirmAction = action;
  $('modal').hidden = false;
}

$('modal-cancel').addEventListener('click', () => {
  $('modal').hidden = true;
  confirmAction = null;
});

$('modal-ok').addEventListener('click', () => {
  $('modal').hidden = true;
  const action = confirmAction;
  confirmAction = null;
  if (action) action();
});

$('btn-browse').addEventListener('click', () => {
  window.pywebview.api.choose_folder().then(applyFromApi);
});

$('toolbar').addEventListener('click', (e) => {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  activeFilter = chip.dataset.filter;
  renderFiles(state.files);
});

$('sel-all').addEventListener('change', (e) => {
  const visible = state.files.filter((f) => matchesFilter(f, activeFilter) && !f.skipped);
  const paths = visible.map((f) => f.path);
  window.pywebview.api.set_selection(paths, e.target.checked).then(applyFromApi);
});

$('btn-refresh').addEventListener('click', () => {
  window.pywebview.api.rescan().then(applyFromApi);
});

$('btn-start').addEventListener('click', () => {
  if (state.trash) {
    askConfirm(
      ui('ask_start_title'),
      ui('ask_start_text', { n: state.selected_count }),
      () => window.pywebview.api.start().then(applyFromApi),
    );
  } else {
    window.pywebview.api.start().then(applyFromApi);
  }
});

$('btn-pause').addEventListener('click', () => {
  window.pywebview.api.pause_toggle().then(applyFromApi);
});

$('btn-stop').addEventListener('click', () => {
  window.pywebview.api.stop().then(applyFromApi);
});

$('btn-trash').addEventListener('click', () => {
  askConfirm(
    ui('ask_trash_title'),
    ui('ask_trash_text', { n: state.trashable }),
    () => window.pywebview.api.trash_verified().then(applyFromApi),
  );
});

$('opt-recursive').addEventListener('change', (e) => {
  window.pywebview.api.set_recursive(e.target.checked).then(applyFromApi);
});

$('opt-shutdown').addEventListener('change', (e) => {
  window.pywebview.api.set_shutdown_after(e.target.checked).then(applyFromApi);
});

$('opt-eject').addEventListener('change', (e) => {
  window.pywebview.api.set_eject_after(e.target.checked).then(applyFromApi);
});

$('opt-vmaf').addEventListener('change', (e) => {
  window.pywebview.api.set_measure_quality(e.target.checked).then(applyFromApi);
});

$('btn-cancel-shutdown').addEventListener('click', () => {
  window.pywebview.api.cancel_shutdown().then(applyFromApi);
});

$('opt-trash').addEventListener('change', (e) => {
  window.pywebview.api.set_trash(e.target.checked).then(applyFromApi);
});

function setupWindowDrag() {
  const api = () => (window.pywebview && window.pywebview.api) || null;
  const drag = (on) => {
    const a = api();
    if (a && a.set_drag) a.set_drag(on);
  };

  for (const zone of document.querySelectorAll('.side__head, .main__head')) {
    zone.addEventListener('mouseenter', () => drag(true));
    zone.addEventListener('mouseleave', () => drag(false));
  }
  for (const btn of document.querySelectorAll('.main__head .btn, .main__head .check')) {
    btn.addEventListener('mouseenter', () => drag(false));
    btn.addEventListener('mouseleave', () => drag(true));
  }
}

function setupDropZone() {
  let depth = 0;
  document.addEventListener('dragover', (e) => { e.preventDefault(); });
  document.addEventListener('dragenter', (e) => {
    e.preventDefault();
    depth += 1;
    document.body.classList.add('drag-over');
  });
  document.addEventListener('dragleave', () => {
    depth = Math.max(0, depth - 1);
    if (depth === 0) document.body.classList.remove('drag-over');
  });
  document.addEventListener('drop', (e) => {
    e.preventDefault();
    depth = 0;
    document.body.classList.remove('drag-over');
  });
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

window.addEventListener('pywebviewready', () => {
  setupWindowDrag();
  setupDropZone();
  window.pywebview.api.get_state().then(applyFromApi);
});

$('btn-gear').addEventListener('click', () => {
  $('settings').hidden = false;
});

$('settings-close').addEventListener('click', () => {
  $('settings').hidden = true;
});

$('settings').addEventListener('click', (e) => {
  if (e.target === $('settings')) $('settings').hidden = true;
});

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (!$('settings').hidden) $('settings').hidden = true;
  else if (!$('modal').hidden) $('modal').hidden = true;
});
