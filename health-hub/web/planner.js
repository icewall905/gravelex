'use strict';

const byId = id => document.getElementById(id);
const setup = byId('setup');
const workout = byId('workout');
const chat = byId('chat');
const model = byId('model');
const ntfy = byId('ntfy');
const month = byId('month');
const params = new URLSearchParams(location.search);
const native = params.get('android') === '1';
let context = params.get('workout');
let state;
let busy = false;

function element(tag, content, className) {
  const node = document.createElement(tag);
  if (content) node.textContent = content;
  if (className) node.className = className;
  return node;
}

function button(label, action) {
  const control = element('button', label, 'btn');
  control.type = 'button';
  control.onclick = action;
  return control;
}

async function api(body) {
  const response = await fetch('/api/planner', body ? {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-PH-Request': '1'},
    body: JSON.stringify({...body, revision: state.revision}),
  } : {cache: 'no-store'});
  if (response.status === 401) {
    location.replace('/login?planner=1' + (native ? '&android=1' : '') + (params.has('settings') ? '&settings=1' : ''));
    throw Error('Please sign in.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 409) {
      state = await api();
      render();
    }
    throw Error(data.error || 'The planner is temporarily unavailable.');
  }
  return data;
}

function today() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: state.timezone, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date());
  return ['year', 'month', 'day'].map(key => parts.find(part => part.type === key).value).join('-');
}

function selectContext(id) {
  context = id;
  const item = state.workouts.find(row => row.id === id);
  const line = byId('workout-context');
  line.hidden = !item;
  line.textContent = item ? `Regarding ${item.title} · ${item.start.replace('T', ' ')}` : '';
  byId('clear-context').hidden = !item;
  byId('reschedule').hidden = !item;
}

function edit(item) {
  workout.reset();
  workout.hidden = false;
  workout.elements.id.value = item?.id || '';
  workout.elements.title.value = item?.title || '';
  workout.elements.start.value = item?.start || `${month.value === today().slice(0, 7) ? today() : month.value + '-01'}T17:00`;
  workout.elements.minutes.value = item?.minutes || 45;
  workout.elements.status.value = item?.status || 'planned';
  workout.elements.details.value = item?.details || '';
  byId('edit-title').textContent = item ? 'Edit workout' : 'Add workout';
  workout.elements.title.focus();
}

function renderCalendar() {
  const root = byId('calendar');
  root.replaceChildren();
  let day;
  for (const item of state.workouts.filter(row => row.start.startsWith(month.value))) {
    const date = item.start.slice(0, 10);
    if (date !== day) {
      root.append(element('h3', new Intl.DateTimeFormat(undefined, {dateStyle:'full', timeZone:'UTC'})
        .format(new Date(date + 'T12:00:00Z')), 'planner-day'));
      day = date;
    }
    const row = element('article', '', 'planner-workout');
    const status = {done:'Done', skipped:'Skipped', rescheduled:'Rescheduled', planned:item.start < today() + 'T00:00' ? 'Unconfirmed' : 'Planned'}[item.status || 'planned'];
    row.append(element('strong', item.title), element('p', `${item.start.slice(11)} · ${item.minutes} min · ${status}`));
    if (item.details) row.append(element('p', item.details));
    const actions = element('div', '', 'planner-row');
    actions.append(button('Edit', () => edit(item)), button('Ask Trainer', () => {
      selectContext(item.id);
      chat.elements.message.focus();
    }), button('Delete', () => {
      if (confirm(`Delete “${item.title}” from the calendar?`)) mutate({action:'delete', id:item.id});
    }));
    if (item.start.slice(0, 10) <= today() && (!item.status || item.status === 'planned')) {
      actions.append(button('Mark done', () => mutate({action:'status', id:item.id, status:'done'})),
        button('Mark skipped', () => mutate({action:'status', id:item.id, status:'skipped'})));
    }
    if (native && !['skipped','rescheduled'].includes(item.status)) {
      const calendar = element('a', 'Add to phone calendar', 'btn');
      const query = new URLSearchParams({title:item.title, details:item.details, start:item.start_ms, end:item.end_ms});
      calendar.href = '/planner-native/calendar?' + query;
      actions.append(calendar);
    }
    row.append(actions);
    root.append(row);
  }
  if (!day) root.append(element('p', 'No workouts scheduled this month.'));
}

async function renderHistory() {
  const selected = month.value;
  const root = byId('recorded');
  root.replaceChildren();
  try {
    const response = await fetch('/api/planner/history?' + new URLSearchParams({month:selected}));
    if (!response.ok) throw Error('Could not load recorded workouts.');
    const {workouts} = await response.json();
    if (month.value !== selected || !workouts.length) return;
    const heading = element('h3', 'Recorded workouts');
    const items = workouts.map(item => {
      const article = element('article', '', 'planner-workout');
      article.append(element('strong', String(item.kind || 'Workout').replaceAll('_', ' ')));
      const facts = [item.start.replace('T', ' '), `${Math.round(item.seconds / 60)} min`, 'Done'];
      if (item.rpe != null) facts.push(`Effort ${item.rpe}/10`);
      if (item.metrics.distance_m != null) facts.push(`${(item.metrics.distance_m / 1000).toFixed(2)} km`);
      if (item.metrics.avg_hr != null) facts.push(`Avg HR ${item.metrics.avg_hr} bpm`);
      article.append(element('p', facts.join(' · ')));
      if (item.metrics.notes) article.append(element('p', item.metrics.notes));
      return article;
    });
    root.replaceChildren(heading, ...items);
  } catch (error) {
    if (month.value === selected) root.replaceChildren(element('p', error.message));
  }
}

function render() {
  renderCalendar();
  renderHistory();
  selectContext(context);
  byId('saved-notes').replaceChildren(...state.notes.map(note => {
    const row = element('div', '', 'planner-row');
    row.append(element('p', note), button('Remove saved note', () => mutate({action:'forget_note', note})));
    return row;
  }));
  const messages = state.messages.map(message => {
    const node = element('article', '', 'planner-message');
    node.append(element('strong', message.role === 'user' ? 'You' : 'Trainer'), element('p', message.text));
    return node;
  });
  byId('messages').replaceChildren(...messages);
  const options = state.options.map(option => {
    const node = element('article', '', 'planner-option');
    node.append(element('h3', option.title), element('p', option.summary));
    const changes = element('ul');
    for (const id of option.remove_ids) {
      const item = state.workouts.find(row => row.id === id);
      const action = item.start.slice(0, 10) < today() ? (option.reschedule ? 'Mark rescheduled' : 'Keep in history') : 'Remove';
      changes.append(element('li', `${action} · ${item.title} · ${item.start.replace('T', ' ')}`));
    }
    for (const item of option.workouts) {
      const row = element('li', `Add ${item.title} · ${item.start.replace('T', ' ')} · ${item.minutes} min`);
      if (item.details) row.append(element('p', item.details));
      changes.append(row);
    }
    node.append(changes, button('Accept plan', () => mutate({action:'accept', id:option.id})));
    return node;
  });
  byId('options').replaceChildren(...options);
  chat.querySelectorAll('button, textarea').forEach(control => { control.disabled = !state.trainer_ready; });
  byId('trainer-status').textContent = state.trainer_ready ? '' : 'Trainer is currently unavailable.';
}

async function mutate(body) {
  if (busy || !state) return;
  busy = true;
  const status = body.action === 'chat' ? byId('trainer-status') : body.action === 'model_settings' ? byId('model-status') : body.action === 'ntfy_settings' ? byId('ntfy-status') : byId('status');
  status.textContent = body.action === 'chat' ? 'Trainer is working…' : 'Saving…';
  try {
    const accepted = body.action === 'accept' ? state.options.find(option => option.id === body.id) : null;
    state = await api(body);
    if (body.action === 'save') {
      month.value = body.start.slice(0, 7);
      workout.hidden = true;
    }
    if (accepted?.workouts.length) month.value = accepted.workouts[0].start.slice(0, 7);
    if (body.action === 'chat') chat.elements.message.value = '';
    if (body.action === 'ntfy_settings') {
      ntfy.elements.topic.value = state.ntfy.topic;
      byId('test-ntfy').disabled = !state.ntfy.enabled;
    }
    render();
    status.textContent = body.action === 'chat' ? 'Trainer replied.' : 'Saved.';
  } catch (error) {
    status.textContent = error.message;
  } finally {
    busy = false;
  }
}

function moveMonth(step) {
  const [year, value] = month.value.split('-').map(Number);
  month.value = new Date(Date.UTC(year, value - 1 + step, 1)).toISOString().slice(0, 7);
  renderCalendar();
  renderHistory();
}

async function showBrowserReminders() {
  if (Notification.permission !== 'granted') return;
  try {
    const response = await fetch('/api/planner/reminders');
    if (!response.ok) return;
    const {account, reminders} = await response.json();
    const day = today();
    const previous = JSON.parse(localStorage.getItem('ph-planner-reminders') || '{}');
    const delivered = new Set(previous.day === day ? previous.keys : []);
    const registration = await navigator.serviceWorker.register('/sw.js');
    await navigator.serviceWorker.ready;
    for (const item of reminders) {
      const key = `${account}:${item.id}:${item.kind}:${item.at}`;
      if (delivered.has(key)) continue;
      const title = item.kind === 'morning' ? 'You have a workout today' : 'How did training go?';
      await registration.showNotification(title, {
        body: 'Open your workout and reply to Trainer.',
        tag: key,
        data: {workout:item.id},
      });
      delivered.add(key);
    }
    localStorage.setItem('ph-planner-reminders', JSON.stringify({day, keys:[...delivered]}));
  } catch {
    // A background tab can be suspended or disconnected. Try again on focus.
  }
}

async function init() {
  try {
    state = await api();
    month.value = today().slice(0, 7);
    for (const field of ['priorities','activities','goals','availability','timezone','morning']) {
      setup.elements[field].value = state[field];
    }
    setup.elements.follow_up.checked = state.follow_up;
    if (state.ntfy?.available) {
      byId('ntfy-panel').hidden = false;
      byId('ntfy-server').textContent = 'Subscribe in ntfy on ' + state.ntfy.server + '. Keep your topic private.';
      ntfy.elements.topic.value = state.ntfy.topic;
      ntfy.elements.enabled.checked = state.ntfy.enabled;
      byId('test-ntfy').disabled = !state.ntfy.enabled;
      ntfy.onsubmit = event => {
        event.preventDefault();
        mutate({action:'ntfy_settings', topic:ntfy.elements.topic.value, enabled:ntfy.elements.enabled.checked});
      };
      byId('test-ntfy').onclick = async () => {
        if (busy) return;
        busy = true;
        const status = byId('ntfy-status');
        status.textContent = 'Sending test…';
        try {
          await api({action:'ntfy_test'});
          status.textContent = 'Test notification sent.';
        } catch (error) {
          status.textContent = error.message;
        } finally {
          busy = false;
        }
      };
    }
    byId('setup-panel').open = !state.priorities && !state.goals && !params.has('settings');
    byId('model-settings').open = params.has('settings');
    if (params.has('settings')) byId('model-settings').scrollIntoView();
    model.elements.base_url.replaceChildren(...state.allowed_model_endpoints.map(url => new Option(url, url)));
    model.elements.base_url.value = state.model_settings.base_url;
    model.elements.model.value = state.model_settings.model;
    model.elements.web_search.checked = state.model_settings.web_search;
    model.elements.web_search.disabled = !state.search_available;
    function modelBody(action) {
      return {...Object.fromEntries(new FormData(model)), action, web_search:model.elements.web_search.checked};
    }
    model.onsubmit = event => {
      event.preventDefault();
      mutate(modelBody('model_settings'));
    };
    byId('test-model').onclick = async () => {
      if (!model.reportValidity() || busy) return;
      busy = true;
      const status = byId('model-status');
      status.textContent = 'Testing model…';
      try {
        await api(modelBody('test_model'));
        status.textContent = 'Trainer model responded successfully.';
      } catch (error) {
        status.textContent = error.message;
      } finally {
        busy = false;
      }
    };
    byId('enable-reminders').hidden = !native;
    const browserReminders = byId('browser-reminders');
    if (!native && 'Notification' in window && 'serviceWorker' in navigator) {
      browserReminders.hidden = false;
      browserReminders.onclick = async () => {
        const permission = await Notification.requestPermission();
        byId('status').textContent = permission === 'granted' ? 'Browser notifications enabled.' : 'Browser notifications are disabled.';
        await showBrowserReminders();
      };
      window.addEventListener('focus', showBrowserReminders);
      window.setInterval(showBrowserReminders, 60_000);
      showBrowserReminders();
    }
    if (native) {
      byId('dashboard-link').href = '/planner-native/back';
      byId('dashboard-link').textContent = '← Health';
      byId('export').href = '/planner-native/export';
      byId('reminder-help').textContent = 'Save a reminder time, then enable phone notifications. Android can delay background delivery.';
      byId('sign-out').hidden = false;
      byId('sign-out').onclick = async () => {
        try {
          const response = await fetch('/auth/logout', {method:'POST', headers:{'X-PH-Request':'1'}});
          if (!response.ok) throw Error('Sign-out is temporarily unavailable.');
          location.replace('/login?planner=1&android=1');
        } catch (error) {
          byId('status').textContent = error.message;
        }
      };
    }
    setup.onsubmit = event => {
      event.preventDefault();
      mutate({action:'setup', ...Object.fromEntries(new FormData(setup)), follow_up:setup.elements.follow_up.checked});
    };
    workout.onsubmit = event => {
      event.preventDefault();
      const fields = Object.fromEntries(new FormData(workout));
      mutate({action:'save', ...fields, minutes:Number(fields.minutes)});
    };
    chat.onsubmit = event => {
      event.preventDefault();
      mutate({action:'chat', message:chat.elements.message.value, workout_id:context});
    };
    byId('reschedule').onclick = () => mutate({
      action:'chat', reschedule:true, workout_id:context,
      message:chat.elements.message.value.trim() || 'Move this workout to another suitable day.',
    });
    byId('suggest').onclick = () => mutate({
      action:'chat', message:'Suggest workout plans based on my saved setup and recent health.',
    });
    byId('clear-context').onclick = () => selectContext(null);
    byId('add').onclick = () => edit();
    byId('cancel-edit').onclick = () => { workout.hidden = true; };
    byId('previous').onclick = () => moveMonth(-1);
    byId('next').onclick = () => moveMonth(1);
    month.onchange = () => {
      if (!month.value) month.value = today().slice(0, 7);
      renderCalendar();
      renderHistory();
    };
    render();
    byId('status').textContent = '';
    if (context) {
      byId('trainer').scrollIntoView();
      chat.elements.message.focus();
    }
  } catch (error) {
    byId('status').textContent = error.message;
  }
}

init();
