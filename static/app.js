/* Strat-O-Matic Card Maker - browser side.
 *
 * Everything is built with DOM calls and textContent. The one exception is
 * card markup, which the server renders with every data value
 * HTML-escaped (stratogen/render.py); cardFragment() inserts only that.
 */
'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const FIRST_YEAR = Number(document.body.dataset.firstYear) || 1871;
  let MAX_YEAR = Number(document.body.dataset.maxYear) || 2025;

  const OFFLINE = "Can't reach the card maker. Is its window still open? " +
    'If you closed it, double-click "Start Strat-O-Gen" again, then reload this page.';
  const LEAGUES = {
    AL: 'American League', NL: 'National League', AA: 'American Association',
    UA: 'Union Association', PL: "Players' League", FL: 'Federal League',
    NA: 'National Association', NNL: 'Negro National League',
    NN2: 'Negro National League', ECL: 'Eastern Colored League',
    ANL: 'American Negro League', EWL: 'East-West League',
    NSL: 'Negro Southern League', NAL: 'Negro American League',
    EAS: 'Eastern independent clubs', WES: 'Western independent clubs',
    IND: 'Independent clubs', NAC: 'Negro clubs', INT: 'International League',
  };

  // --- small helpers --------------------------------------------------------

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? '' : String(value));
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : String(child));
    }
    return node;
  }

  // Server-rendered, server-escaped card markup only.
  function cardFragment(html) {
    const t = document.createElement('template');
    t.innerHTML = html;
    return t.content;
  }

  function announce(text) {
    const a = $('announce');
    a.textContent = '';
    window.setTimeout(() => { a.textContent = text; }, 30);
  }

  const inflight = {};
  // fetch() with one request per channel (a newer one aborts the older),
  // friendly errors for a dead server, and JSON checks.
  async function api(channel, url, options) {
    if (inflight[channel]) inflight[channel].abort();
    const ctrl = new AbortController();
    inflight[channel] = ctrl;
    let resp;
    try {
      resp = await fetch(url, Object.assign({}, options, { signal: ctrl.signal }));
    } catch (err) {
      if (err.name === 'AbortError') throw err;
      throw new Error(OFFLINE);
    }
    let data = null;
    if ((resp.headers.get('content-type') || '').includes('json')) {
      try { data = await resp.json(); } catch (_) { data = null; }
    }
    if (inflight[channel] !== ctrl) {
      const stale = new Error('superseded');
      stale.name = 'AbortError';
      throw stale;
    }
    inflight[channel] = null;
    if (!resp.ok) {
      const err = new Error((data && data.error) ||
        `Something went wrong on the card maker's side (error ${resp.status}).`);
      err.data = data || {};
      throw err;
    }
    if (!data) throw new Error("The card maker sent a reply this page doesn't understand. Try reloading.");
    return data;
  }
  const isAbort = (err) => err && err.name === 'AbortError';

  let busySeq = 0;
  function busy(text) {
    const my = ++busySeq;
    const box = $('busy');
    if (text) { box.textContent = text; box.hidden = false; }
    return () => { if (my === busySeq) { box.hidden = true; box.textContent = ''; } };
  }

  function showError(boxId, message, action) {
    const box = $(boxId);
    box.replaceChildren(document.createTextNode(message));
    if (action) {
      box.append(' ', el('button', { type: 'button', class: 'linklike', onclick: action.run, text: action.label }));
    }
    box.hidden = false;
  }
  function hideError(boxId) { const box = $(boxId); box.hidden = true; box.replaceChildren(); }

  function readYear(input, errorBox, required) {
    const raw = input.value.trim();
    if (!raw) {
      if (required) { showError(errorBox, 'Enter a year, like 1927.'); input.focus(); }
      return null;
    }
    const year = /^\d{4}$/.test(raw) ? Number(raw) : NaN;
    if (!(year >= FIRST_YEAR && year <= MAX_YEAR)) {
      showError(errorBox, `Enter a year from ${FIRST_YEAR} to ${MAX_YEAR}.`);
      input.focus();
      return undefined;
    }
    return year;
  }

  // --- start-up: is the data loaded? -----------------------------------------

  async function checkHealth() {
    const status = $('status');
    try {
      const h = await api('health', '/api/health');
      if (h.ready) {
        status.hidden = true;
        status.classList.remove('bad');
        return;
      }
      status.textContent = 'Loading the player database — the first start takes a few seconds…';
      status.classList.remove('bad');
      status.hidden = false;
      window.setTimeout(checkHealth, 700);
    } catch (err) {
      if (isAbort(err)) return;
      status.textContent = err.message;
      status.classList.add('bad');
      status.hidden = false;
      window.setTimeout(checkHealth, 4000);
    }
  }

  // --- mode tabs (One card / Team set) ---------------------------------------

  const modeTabs = [$('tab-card'), $('tab-team')];
  function setMode(mode, focus) {
    for (const tab of modeTabs) {
      const on = tab.id === `tab-${mode}`;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
      $(tab.getAttribute('aria-controls')).hidden = !on;
      if (on && focus) tab.focus();
    }
    $('result').hidden = mode !== 'card';
    $('team-result').hidden = mode !== 'team';
  }
  for (const tab of modeTabs) {
    tab.addEventListener('click', () => setMode(tab.id.slice(4)));
  }
  function tabKeys(tabs, onPick) {
    tabs.forEach((tab, i) => tab.addEventListener('keydown', (e) => {
      let j = null;
      if (e.key === 'ArrowRight') j = (i + 1) % tabs.length;
      else if (e.key === 'ArrowLeft') j = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === 'Home') j = 0;
      else if (e.key === 'End') j = tabs.length - 1;
      if (j === null) return;
      e.preventDefault();
      onPick(tabs[j]);
    }));
  }
  tabKeys(modeTabs, (tab) => setMode(tab.id.slice(4), true));

  // --- one card: state -------------------------------------------------------

  const state = {
    player: null,      // chosen player summary (from suggest/search/random)
    kindChoice: null,  // batter/pitcher picked by hand for THIS player
    data: null,        // last generated card
    side: 'basic',
  };
  const nameInput = $('name');
  const yearInput = $('year');

  function seasonsOf(p) {
    const all = new Set([...(p.batting_years || []), ...(p.pitching_years || [])]);
    return [...all].sort((a, b) => a - b);
  }

  function setPlayer(p) {
    if (!state.player || state.player.player_id !== p.player_id) {
      state.kindChoice = null;   // the batter/pitcher choice never carries over
    }
    state.player = p;
    nameInput.value = p.name;
  }

  function clearCandidates() { const c = $('candidates'); c.hidden = true; c.replaceChildren(); }
  function hideYears() { const y = $('years'); y.hidden = true; y.replaceChildren(); }

  function showYearChips(years, message) {
    const box = $('years');
    box.replaceChildren();
    if (!years || !years.length) { box.hidden = true; return; }
    box.append(el('span', { class: 'note', text: message }));
    for (const y of years) {
      box.append(el('button', {
        type: 'button', class: 'yearchip', text: y,
        onclick: () => { yearInput.value = y; generate(); },
      }));
    }
    box.hidden = false;
  }

  // --- autocomplete (ARIA 1.2 combobox) ----------------------------------------

  const listbox = $('suggestions');
  let suggestions = [];
  let activeIndex = -1;
  let suggestTimer = null;

  function closeSuggestions() {
    listbox.hidden = true;
    listbox.replaceChildren();
    suggestions = [];
    activeIndex = -1;
    nameInput.setAttribute('aria-expanded', 'false');
    nameInput.removeAttribute('aria-activedescendant');
  }

  function setActive(i) {
    activeIndex = i;
    [...listbox.children].forEach((li, j) => li.setAttribute('aria-selected', String(j === i)));
    if (i >= 0 && listbox.children[i]) {
      nameInput.setAttribute('aria-activedescendant', listbox.children[i].id);
      listbox.children[i].scrollIntoView({ block: 'nearest' });
    } else {
      nameInput.removeAttribute('aria-activedescendant');
    }
  }

  function renderSuggestions(players) {
    suggestions = players;
    activeIndex = -1;
    listbox.replaceChildren();
    if (!players.length) { closeSuggestions(); return; }
    players.forEach((p, i) => {
      const meta = [p.span, p.position || p.role].filter(Boolean).join(' · ');
      listbox.append(el('li', {
        id: `suggestion-${i}`, role: 'option', 'aria-selected': 'false',
        onmousedown: (e) => { e.preventDefault(); chooseSuggestion(i); },
      }, el('span', { class: 's-name', text: p.name }), el('span', { class: 's-meta', text: meta })));
    });
    listbox.hidden = false;
    nameInput.setAttribute('aria-expanded', 'true');
  }

  async function fetchSuggestions(q) {
    try {
      const data = await api('suggest', '/api/suggest?q=' + encodeURIComponent(q));
      if (nameInput.value.trim() !== q || document.activeElement !== nameInput) return;
      renderSuggestions(data.players);
    } catch (err) {
      if (!isAbort(err)) closeSuggestions();
    }
  }

  function chooseSuggestion(i) {
    const p = suggestions[i];
    closeSuggestions();
    if (!p) return;
    hideError('card-error');
    clearCandidates();
    pickPlayer(p);
  }

  nameInput.addEventListener('input', () => {
    const q = nameInput.value.trim();
    if (state.player && q !== state.player.name) { state.player = null; state.kindChoice = null; }
    window.clearTimeout(suggestTimer);
    if (q.length < 2) { closeSuggestions(); return; }
    suggestTimer = window.setTimeout(() => fetchSuggestions(q), 110);
  });
  nameInput.addEventListener('keydown', (e) => {
    const open = !listbox.hidden && suggestions.length > 0;
    if (e.key === 'ArrowDown' && open) {
      e.preventDefault();
      setActive(Math.min(activeIndex + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp' && open) {
      e.preventDefault();
      setActive(Math.max(activeIndex - 1, 0));
    } else if (e.key === 'Enter' && open && activeIndex >= 0) {
      e.preventDefault();
      chooseSuggestion(activeIndex);
    } else if (e.key === 'Escape' && open) {
      e.preventDefault();
      closeSuggestions();
    } else if (e.key === 'Tab') {
      closeSuggestions();
    }
  });
  nameInput.addEventListener('blur', () => window.setTimeout(closeSuggestions, 150));

  // --- finding a player ----------------------------------------------------------

  function pickPlayer(p) {
    setPlayer(p);
    const year = readYear(yearInput, 'card-error', false);
    if (year === undefined) return;
    if (year) { generate(); return; }
    $('result').replaceChildren();
    showYearChips(seasonsOf(p), `${p.name} has cards for these seasons — pick one:`);
    yearInput.focus();
  }

  function showCandidates(players, year) {
    const box = $('candidates');
    box.replaceChildren(el('p', { class: 'note', text: 'Several players have that name — which one?' }));
    for (const p of players) {
      let meta = p.meta;
      if (year && !p.has_year) meta += ` · no ${year} season`;
      const b = el('button', {
        type: 'button', class: 'candidate', 'aria-pressed': 'false',
        onclick: () => {
          for (const other of box.querySelectorAll('.candidate')) other.setAttribute('aria-pressed', 'false');
          b.setAttribute('aria-pressed', 'true');
          pickPlayer(p);
        },
      }, el('b', { text: p.name }), el('span', { class: 'meta', text: meta }));
      box.append(b);
    }
    box.hidden = false;
    const first = box.querySelector('.candidate');
    if (first) first.focus();
  }

  async function search(name) {
    const year = readYear(yearInput, 'card-error', false);
    if (year === undefined) return;
    hideError('card-error'); clearCandidates(); hideYears();
    $('result').replaceChildren();
    const done = busy('Looking up players…');
    setButtons(true);
    try {
      const url = '/api/search?name=' + encodeURIComponent(name) + (year ? '&year=' + year : '');
      const data = await api('card', url);
      const players = data.players || [];
      if (!players.length) {
        showError('card-error', `No player found named “${name}”. Check the spelling — a last name alone works too.`);
        return;
      }
      const inYear = year ? players.filter((p) => p.has_year) : [];
      if (players.length === 1) pickPlayer(players[0]);
      else if (inYear.length === 1) pickPlayer(inYear[0]);
      else showCandidates(players, year);
    } catch (err) {
      if (!isAbort(err)) showError('card-error', err.message);
    } finally {
      done(); setButtons(false);
    }
  }

  function setButtons(disabled) {
    for (const id of ['find-btn', 'random-btn']) {
      const b = $(id);
      b.disabled = disabled;
      b.setAttribute('aria-busy', String(disabled));
    }
  }

  $('card-form').addEventListener('submit', (e) => {
    e.preventDefault();
    closeSuggestions();
    const name = nameInput.value.trim();
    if (!name) { showError('card-error', 'Enter a player name.'); nameInput.focus(); return; }
    // Same player, new year: keep the choice (don't search again).
    if (state.player && name === state.player.name) { generate(); return; }
    search(name);
  });
  yearInput.addEventListener('change', () => {
    if (state.player && nameInput.value.trim() === state.player.name && yearInput.value.trim()) generate();
  });

  $('random-btn').addEventListener('click', async () => {
    hideError('card-error'); clearCandidates(); hideYears();
    const done = busy('Picking a random season…');
    setButtons(true);
    try {
      const p = await api('card', '/api/random');
      setPlayer(p);
      state.kindChoice = p.kind;
      yearInput.value = p.year;
      generate();
    } catch (err) {
      if (!isAbort(err)) showError('card-error', err.message);
    } finally {
      done(); setButtons(false);
    }
  });

  // --- making the card --------------------------------------------------------------

  async function generate() {
    const p = state.player;
    if (!p) return;
    const year = readYear(yearInput, 'card-error', true);
    if (!year) {
      if (year === null) showYearChips(seasonsOf(p), `${p.name} has cards for these seasons — pick one:`);
      return;
    }
    let kind = 'auto';
    const chosen = state.kindChoice;
    if (chosen && ((chosen === 'batter' ? p.batting_years : p.pitching_years) || []).includes(year)) kind = chosen;
    hideError('card-error'); hideYears();
    const done = busy(`Making ${p.name}'s ${year} card…`);
    setButtons(true);
    try {
      const data = await api('card', '/api/generate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: p.player_id, year, kind }),
      });
      p.batting_years = data.batting_years || p.batting_years;
      p.pitching_years = data.pitching_years || p.pitching_years;
      state.data = data;
      renderCard(data);
      announce(`${data.name} ${data.year} ${data.kind} card is ready.`);
    } catch (err) {
      if (isAbort(err)) return;
      $('result').replaceChildren();
      const other = err.data && err.data.other_kind;
      showError('card-error', err.message, other ? {
        label: `Show the ${other} card`,
        run: () => { state.kindChoice = other; generate(); },
      } : null);
      if (err.data && err.data.years && err.data.years.length) {
        showYearChips(err.data.years, 'Seasons with a card: ');
      }
    } finally {
      done(); setButtons(false);
    }
  }

  function warningsBox(items, title) {
    return el('div', { class: 'warnings' },
      el('p', { text: title }),
      el('ul', {}, items.map((w) => el('li', { text: w }))));
  }

  function differs(label, actual, card) {
    const a = parseFloat(actual); const c = parseFloat(card);
    if (Number.isNaN(a) || Number.isNaN(c)) return false;
    if (String(actual).startsWith('.') || label.toLowerCase().includes('average')) return Math.abs(a - c) >= 0.005;
    return Math.abs(a - c) >= Math.max(2, 0.06 * Math.abs(a));
  }

  function honestyTable(rows, year) {
    const table = el('table', { class: 'accuracy' },
      el('thead', {}, el('tr', {},
        el('th', { scope: 'col', text: 'Stat' }),
        el('th', { scope: 'col', text: `Actual ${year}` }),
        el('th', { scope: 'col', text: 'This card' }))));
    const body = el('tbody');
    for (const [label, actual, card] of rows) {
      const off = differs(label, actual, card);
      body.append(el('tr', {},
        el('th', { scope: 'row', text: label }),
        el('td', { text: actual }),
        el('td', { class: off ? 'off' : null, title: off ? 'The card differs here — see the notes above.' : null, text: card })));
    }
    table.append(body);
    return table;
  }

  function yearNav(d) {
    const years = d.years || [];
    const i = years.indexOf(d.year);
    const nav = el('div', { class: 'yearnav', role: 'group', 'aria-label': 'Other seasons' });
    const go = (y) => () => { yearInput.value = y; generate(); };
    if (i > 0) nav.append(el('button', { type: 'button', class: 'secondary small', onclick: go(years[i - 1]), 'aria-label': `Previous season, ${years[i - 1]}`, text: `◀ ${years[i - 1]}` }));
    if (i >= 0 && i < years.length - 1) nav.append(el('button', { type: 'button', class: 'secondary small', onclick: go(years[i + 1]), 'aria-label': `Next season, ${years[i + 1]}`, text: `${years[i + 1]} ▶` }));
    return nav;
  }

  function kindToggle(d) {
    const box = el('fieldset', { class: 'kind-toggle' }, el('legend', { text: 'Card:' }));
    for (const kind of ['batter', 'pitcher']) {
      const input = el('input', {
        type: 'radio', name: 'kind', value: kind, checked: d.kind === kind,
        onchange: () => { state.kindChoice = kind; generate(); },
      });
      box.append(el('label', {}, input, kind === 'batter' ? 'Batter card' : 'Pitcher card'));
    }
    return box;
  }

  function renderCard(d) {
    const root = $('result');
    const panel = el('section', { class: 'panel result-panel', 'aria-labelledby': 'result-title' });
    const handWord = d.kind === 'pitcher' ? `throws ${d.hand}` : `bats ${d.hand}`;
    const sub = [d.team, LEAGUES[d.league] || d.league, handWord].filter(Boolean).join(' · ');
    panel.append(el('div', { class: 'result-head' },
      el('div', {},
        el('h2', { id: 'result-title', tabindex: '-1', text: `${d.name} · ${d.year}` }),
        el('p', { class: 'result-sub', text: sub })),
      yearNav(d)));
    if (d.kinds && d.kinds.length > 1) panel.append(kindToggle(d));
    if (d.team_note) panel.append(el('p', { class: 'team-note', text: d.team_note }));
    if (d.warnings.length) panel.append(warningsBox(d.warnings, 'Heads up:'));

    const tabs = [
      el('button', { type: 'button', role: 'tab', id: 'side-tab-basic', 'aria-controls': 'side-panel', text: 'Basic side' }),
      el('button', { type: 'button', role: 'tab', id: 'side-tab-advanced', 'aria-controls': 'side-panel', text: 'Advanced side (vs L/R)' }),
    ];
    const tablist = el('div', { class: 'side-tabs', role: 'tablist', 'aria-label': 'Card side' }, tabs);
    const sidePanel = el('div', { class: 'side-panel', id: 'side-panel', role: 'tabpanel' });
    const actions = el('div', { class: 'card-actions' },
      el('button', { type: 'button', class: 'primary', onclick: () => printSides(d, state.side), text: 'Print this side' }),
      el('button', { type: 'button', class: 'secondary', onclick: () => printSides(d, 'both'), text: 'Print both sides' }),
      el('a', { class: 'button secondary', href: d.downloads.html, download: '', text: 'Save card' }),
      el('a', { class: 'button secondary', href: d.downloads.json, download: '', text: 'Save card data' }));
    const tip = el('p', { class: 'note print-tip' });
    const TIP = {
      basic: 'Prints at real card size (2.6 inches wide) — keep the print scale at 100%.',
      advanced: 'Prints at real card size (the advanced side is 5.2 inches wide) — keep the print scale at 100%.',
    };

    function showSide(side, focus) {
      state.side = side;
      for (const t of tabs) {
        const on = t.id === `side-tab-${side}`;
        t.setAttribute('aria-selected', String(on));
        t.tabIndex = on ? 0 : -1;
        if (on) { sidePanel.setAttribute('aria-labelledby', t.id); if (focus) t.focus(); }
      }
      const content = [];
      if (side === 'advanced') {
        content.push(el('p', { class: 'explainer', text: d.advanced_explainer }));
        if (d.advanced_warnings.length) content.push(warningsBox(d.advanced_warnings, 'Advanced side notes:'));
      }
      const stage = el('div', { class: 'card-stage' });
      stage.append(cardFragment(side === 'advanced' ? d.advanced_html : d.card_html));
      tip.textContent = TIP[side];
      content.push(stage, actions, tip,
        el('h3', { text: `How well does the ${side} side match ${d.year}?` }),
        el('p', { class: 'note', text: d.honesty_notes[side] }),
        honestyTable(d.honesty[side], d.year));
      sidePanel.replaceChildren(...content);
    }
    for (const t of tabs) t.addEventListener('click', () => showSide(t.id.slice(9)));
    tabKeys(tabs, (t) => showSide(t.id.slice(9), true));
    panel.append(tablist, sidePanel);
    showSide(state.side === 'advanced' ? 'advanced' : 'basic');
    root.replaceChildren(panel);
  }

  // --- printing --------------------------------------------------------------------------

  function printNodes(nodes, title) {
    const root = $('print-root');
    root.replaceChildren(...nodes);
    const oldTitle = document.title;
    document.title = title;
    let restored = false;
    const restore = () => {
      if (restored) return;
      restored = true;
      document.title = oldTitle;
      root.replaceChildren();
      window.removeEventListener('afterprint', restore);
    };
    // window.print() blocks until the dialog closes in current browsers;
    // the print area stays harmlessly hidden if afterprint never comes.
    window.addEventListener('afterprint', restore);
    // scale any card that would print taller than a real card (4.1in)
    if (window.somFitCards) window.somFitCards(root);
    window.print();
  }

  function printSides(d, sides) {
    const wrap = el('div', { class: 'print-single' });
    if (sides !== 'advanced') wrap.append(cardFragment(d.card_html));
    if (sides !== 'basic') wrap.append(cardFragment(d.advanced_html));
    const what = sides === 'both' ? 'card' : `${sides} side`;
    printNodes([wrap], `${d.name} ${d.year} ${d.kind} ${what}`);
  }

  function sheetPages(htmls, side) {
    const per = side === 'advanced' ? 2 : 4;
    const pages = [];
    for (let i = 0; i < htmls.length; i += per) {
      const page = el('section', { class: `sheet-page sheet-${side}` });
      for (const h of htmls.slice(i, i + per)) page.append(el('div', { class: 'sheet-cell' }, cardFragment(h)));
      pages.push(page);
    }
    return pages;
  }

  // --- team sets ---------------------------------------------------------------------------

  const teamYear = $('team-year');
  const teamState = { year: null, data: null, view: 'basic', print: 'basic' };

  $('team-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const year = readYear(teamYear, 'team-error', true);
    if (year) loadTeams(year);
  });

  async function loadTeams(year) {
    hideError('team-error');
    const list = $('team-list');
    list.replaceChildren();
    const done = busy(`Finding the ${year} teams…`);
    $('teams-btn').disabled = true;
    try {
      const data = await api('teams', '/api/teams?year=' + year);
      teamState.year = year;
      if (!data.leagues.length) {
        showError('team-error', `No teams found for ${year}. Try a year from ${data.first_year} to ${data.last_year}.`);
        return;
      }
      for (const lg of data.leagues) {
        const name = LEAGUES[lg.league] || lg.league;
        const grid = el('div', { class: 'team-buttons' });
        for (const t of lg.teams) {
          grid.append(el('button', {
            type: 'button', class: 'team-btn', 'aria-pressed': 'false',
            'aria-label': `${t.name}, ${t.W} wins, ${t.L} losses`,
            onclick: (e) => {
              for (const b of list.querySelectorAll('.team-btn')) b.setAttribute('aria-pressed', 'false');
              e.currentTarget.setAttribute('aria-pressed', 'true');
              loadTeam(year, t.team_id);
            },
          }, el('span', { text: t.name }), el('span', { class: 'wl', text: `${t.W}–${t.L}` })));
        }
        list.append(el('div', { class: 'league' }, el('h3', { text: `${year} ${name}` }), grid));
      }
      const first = list.querySelector('.team-btn');
      if (first) first.focus();
    } catch (err) {
      if (!isAbort(err)) showError('team-error', err.message);
    } finally {
      done();
      $('teams-btn').disabled = false;
    }
  }

  async function loadTeam(year, teamId) {
    hideError('team-error');
    const root = $('team-result');
    root.replaceChildren();
    const done = busy('Making every card on the roster…');
    try {
      const data = await api('team', `/api/team?year=${year}&team=${encodeURIComponent(teamId)}`);
      teamState.data = data;
      renderTeam(data);
      announce(`${data.title}: ${data.cards.length} cards ready.`);
    } catch (err) {
      if (!isAbort(err)) showError('team-error', err.message);
    } finally {
      done();
    }
  }

  function radioGroup(legend, name, options, current, onChange) {
    const fs = el('fieldset', {}, el('legend', { text: legend }));
    for (const [value, label] of options) {
      fs.append(el('label', {}, el('input', {
        type: 'radio', name, value, checked: value === current,
        onchange: () => onChange(value),
      }), label));
    }
    return fs;
  }

  function teamGrid(cards, view) {
    const grid = el('div', { class: view === 'advanced' ? 'team-grid adv' : 'team-grid' });
    for (const c of cards) {
      const caption = el('figcaption', {},
        el('span', { class: 'pos', text: c.position }), el('span', { class: 'usage', text: c.usage }),
        c.traded_note ? el('span', { class: 'traded', text: c.traded_note }) : null,
        el('button', {
          type: 'button', class: 'linklike', text: 'Open this card',
          'aria-label': `Open ${c.name}'s ${c.kind} card`,
          onclick: () => openFromTeam(c),
        }));
      const fig = el('figure', {});
      fig.append(cardFragment(view === 'advanced' ? c.advanced_html : c.card_html), caption);
      grid.append(fig);
    }
    return grid;
  }

  function openFromTeam(c) {
    setPlayer({ player_id: c.player_id, name: c.name, batting_years: [], pitching_years: [] });
    state.kindChoice = c.kind;
    state.player[c.kind === 'batter' ? 'batting_years' : 'pitching_years'] = [teamState.data.team.year];
    yearInput.value = teamState.data.team.year;
    setMode('card');
    generate();
    window.scrollTo({ top: 0 });
  }

  function renderTeam(d) {
    const root = $('team-result');
    const panel = el('section', { class: 'panel', 'aria-labelledby': 'team-title' });
    const batters = d.cards.filter((c) => c.kind === 'batter');
    const pitchers = d.cards.filter((c) => c.kind === 'pitcher');
    panel.append(el('h2', { id: 'team-title', class: 'team-title', tabindex: '-1', text: d.title }),
      el('p', { class: 'result-sub', text: `${LEAGUES[d.team.league] || d.team.league} · ${d.team.W}–${d.team.L} · ${d.cards.length} cards (${batters.length} batters, ${pitchers.length} pitchers)` }));
    const grids = el('div');
    const draw = () => {
      grids.replaceChildren(
        el('h3', { text: `Batters (${batters.length})` }), teamGrid(batters, teamState.view),
        el('h3', { text: `Pitchers (${pitchers.length})` }), teamGrid(pitchers, teamState.view));
    };
    const save = el('a', { class: 'button secondary', download: '', href: d.downloads[teamState.print], text: 'Save team sheet' });
    const controls = el('div', { class: 'team-controls' },
      radioGroup('Show', 'team-view', [['basic', 'Basic sides'], ['advanced', 'Advanced sides']], teamState.view,
        (v) => { teamState.view = v; draw(); }),
      radioGroup('Print', 'team-print', [['basic', 'Basic sides'], ['advanced', 'Advanced sides'], ['both', 'Both']], teamState.print,
        (v) => { teamState.print = v; save.href = d.downloads[v]; }),
      el('div', { class: 'actions', style: 'margin:0' },
        el('button', { type: 'button', class: 'primary', onclick: () => printTeam(d), text: 'Print sheets' }), save));
    panel.append(controls,
      el('p', { class: 'note', text: 'Sheets print at real card size: basic sides 4 to a page, advanced sides 2 to a page. Keep the print scale at 100%.' }));
    draw();
    panel.append(grids);
    if (d.left_out.length) {
      panel.append(el('h3', { text: `Left out (${d.left_out.length})` }),
        el('p', { class: 'note', text: `Cards go to players with at least ${d.thresholds.pa} plate appearances or ${d.thresholds.ip} innings for this team (about 50 PA or 20 IP over a 154-game season).` }),
        el('ul', { class: 'left-out' }, d.left_out.map((x) => el('li', {}, el('b', { text: x.name }), `: ${x.reason}`))));
    }
    root.replaceChildren(panel);
    root.hidden = false;
    panel.querySelector('#team-title').focus();
  }

  function printTeam(d) {
    const pages = [];
    if (teamState.print !== 'advanced') pages.push(...sheetPages(d.cards.map((c) => c.card_html), 'basic'));
    if (teamState.print !== 'basic') pages.push(...sheetPages(d.cards.map((c) => c.advanced_html), 'advanced'));
    const what = { basic: 'basic sides', advanced: 'advanced sides', both: 'cards' }[teamState.print];
    printNodes(pages, `${d.title} ${what}`);
  }

  // --- go -----------------------------------------------------------------------------------

  setMode('card');
  checkHealth();
})();
