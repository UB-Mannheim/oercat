/**
 * OER catalogue search: full-text search (MiniSearch) plus faceted filters.
 *
 * All configuration comes from the #oer-config JSON block rendered by
 * layouts/home.html (facets, labels, UI strings), so adding a facet needs no
 * change here. State lives in the URL query string (?q=…&type=Tutorial), which
 * keeps every view shareable and bookmarkable.
 */
import MiniSearch from "./vendor/minisearch.js";

const cfg = JSON.parse(document.getElementById("oer-config").textContent);
const PAGE_SIZE = 24;
const FACET_PREVIEW = 8; // values shown per filter group before "show all"
const FACET_MAX = 60; // cap for very large groups; use the group's search box instead
const DEFAULT_OPEN = ["type"]; // filter groups expanded on page load

const $ = (id) => document.getElementById(id);
const els = {
  q: $("q"),
  facets: $("facets"),
  results: $("results"),
  count: $("result-count"),
  active: $("active-filters"),
  sort: $("sort"),
  more: $("load-more"),
  yearFrom: $("year-from"),
  yearTo: $("year-to"),
  filtersOpen: $("filters-open"),
  filtersClose: $("filters-close"),
};

/** Everything that is reflected in the URL. */
const state = { q: "", filters: {}, yearFrom: "", yearTo: "", sort: "", shown: PAGE_SIZE };
/** View-only state (not in the URL). */
const ui = {
  open: new Set(DEFAULT_OPEN),
  expanded: new Set(),
  facetQuery: {},
};

let docs = [];
let byId = new Map();
let index;

// --- helpers -----------------------------------------------------------------

/** Lower case without diacritics, so "kunstliche" finds "Künstliche". */
const fold = (s) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

const label = (facet, value) => cfg.labels[facet]?.[value] ?? value;
const t = (key, n) => (cfg.i18n[key] ?? key).replace("{n}", n);
const plural = (key, n) => t(n === 1 ? `${key}_one` : `${key}_other`, n.toLocaleString(cfg.lang));

/** Wrap matched search terms in <mark>. `text` is plain text; returns HTML. */
function highlight(text, terms) {
  if (!terms?.length || !text) return esc(text);
  const folded = fold(text);
  if (folded.length !== text.length) return esc(text); // unusual characters: skip highlighting
  const ranges = [];
  for (const term of terms) {
    const re = new RegExp(`(?<![\\p{L}\\p{N}])${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "gu");
    for (const m of folded.matchAll(re)) ranges.push([m.index, m.index + term.length]);
  }
  if (!ranges.length) return esc(text);
  ranges.sort((a, b) => a[0] - b[0]);
  let html = "";
  let pos = 0;
  for (const [start, end] of ranges) {
    if (start < pos) continue;
    html += esc(text.slice(pos, start)) + "<mark>" + esc(text.slice(start, end)) + "</mark>";
    pos = end;
  }
  return html + esc(text.slice(pos));
}

/** A ~260 character excerpt of the description, centred on the first match. */
function snippet(text, terms) {
  const length = 260;
  let start = 0;
  if (terms?.length) {
    const folded = fold(text);
    const hits = terms.map((term) => folded.indexOf(term)).filter((i) => i >= 0);
    if (hits.length && Math.min(...hits) > length - 60) start = Math.min(...hits) - 60;
  }
  let part = text.slice(start, start + length);
  if (start > 0) part = "…" + part.slice(part.indexOf(" ") + 1);
  if (start + length < text.length) part = part.slice(0, part.lastIndexOf(" ")) + " …";
  return highlight(part, terms);
}

// --- URL state -----------------------------------------------------------------

function readURL() {
  const params = new URLSearchParams(location.search);
  state.q = params.get("q") ?? "";
  state.sort = params.get("sort") ?? "";
  state.yearFrom = params.get("from") ?? "";
  state.yearTo = params.get("to") ?? "";
  state.filters = {};
  for (const { key } of cfg.facets) {
    const values = params.getAll(key);
    if (values.length) state.filters[key] = new Set(values);
  }
}

function writeURL() {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  for (const [key, values] of Object.entries(state.filters)) {
    for (const value of values) params.append(key, value);
  }
  if (state.yearFrom) params.set("from", state.yearFrom);
  if (state.yearTo) params.set("to", state.yearTo);
  if (state.sort) params.set("sort", state.sort);
  const query = params.toString() ? `?${params}` : "";
  history.replaceState(null, "", location.pathname + query);

  // Keep the current search when switching the UI language.
  document.querySelectorAll("[data-lang-switch]").forEach((a) => (a.search = query));
  try {
    sessionStorage.setItem(`oer-last-search-${cfg.lang}`, location.href);
  } catch {
    /* storage unavailable: the back link falls back to the start page */
  }
}

// --- search and filtering --------------------------------------------------------

function buildIndex() {
  index = new MiniSearch({
    fields: Object.keys(cfg.searchFields),
    extractField: (doc, field) => {
      const value = doc[field];
      return Array.isArray(value) ? value.join(" ") : value;
    },
    processTerm: (term) => fold(term),
  });
  index.addAll(docs);
}

/**
 * Text search: hits sorted by relevance, or null if there is no query.
 * Exact and prefix matches first; only if nothing is found, retry with typo
 * tolerance ("pyhton" → "python") so normal results stay precise.
 */
function search() {
  const q = state.q.trim();
  if (!q) return null;
  const options = { boost: cfg.searchFields, prefix: true, combineWith: "AND" };
  const hits = index.search(q, options);
  if (hits.length) return hits;
  return index.search(q, { ...options, fuzzy: (term) => (term.length >= 5 ? 2 : term.length >= 3 ? 1 : 0) });
}

const selectedCount = () => Object.values(state.filters).reduce((n, s) => n + s.size, 0);

/** Does `doc` pass every active filter, ignoring the facet `except`? */
function matches(doc, except) {
  for (const [key, values] of Object.entries(state.filters)) {
    if (key === except || !values.size) continue;
    if (!doc[key].some((v) => values.has(v))) return false; // OR within a facet
  }
  if (state.yearFrom && !(doc.year >= +state.yearFrom)) return false;
  if (state.yearTo && !(doc.year <= +state.yearTo)) return false;
  return true;
}

/** Value counts for one facet, computed as if that facet had no selection. */
function facetCounts(pool, key) {
  const counts = new Map();
  for (const doc of pool) {
    if (!matches(doc, key)) continue;
    for (const value of doc[key]) counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return counts;
}

const SORTS = {
  added: (a, b) => b.id - a.id,
  newest: (a, b) => (b.date || "").localeCompare(a.date || "") || b.id - a.id,
  title: (a, b) => a.title.localeCompare(b.title, cfg.lang),
};

// --- rendering -----------------------------------------------------------------

function renderFacetGroup(facet, counts) {
  const { key } = facet;
  const selected = state.filters[key] ?? new Set();
  const order = Object.keys(cfg.labels[key] ?? {});
  let values = [...new Set([...counts.keys(), ...selected])];
  if (!values.length) return "";

  if (facet.ordered) {
    values.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  } else {
    values.sort((a, b) => (counts.get(b) ?? 0) - (counts.get(a) ?? 0) || label(key, a).localeCompare(label(key, b), cfg.lang));
  }

  const query = ui.facetQuery[key] ?? "";
  if (query) values = values.filter((v) => fold(label(key, v)).includes(fold(query)));

  const total = values.length;
  const expanded = ui.expanded.has(key) || query;
  const limit = expanded ? FACET_MAX : FACET_PREVIEW;
  const visible = values.filter((v, i) => i < limit || selected.has(v));

  const items = visible
    .map((value) => {
      const id = `${key}|${value}`;
      return `<li><label>
        <input type="checkbox" data-facet="${esc(key)}" data-value="${esc(value)}" data-fid="${esc(id)}"${selected.has(value) ? " checked" : ""}>
        <span class="value">${esc(label(key, value))}</span>
        <span class="count">${counts.get(value) ?? 0}</span>
      </label></li>`;
    })
    .join("");

  const search = facet.large
    ? `<input type="search" class="facet-search" placeholder="${esc(t("filter_values"))}" aria-label="${esc(cfg.facetTitles[key])}: ${esc(t("filter_values"))}" data-facet-search="${esc(key)}" data-fid="search|${esc(key)}" value="${esc(query)}">`
    : "";
  const toggle =
    total > FACET_PREVIEW && !query
      ? `<button type="button" class="link-button" data-expand="${esc(key)}" data-fid="expand|${esc(key)}">${esc(expanded ? t("show_less") : t("show_more", total))}</button>`
      : "";
  const badge = selected.size ? `<span class="selected-count">${selected.size}</span>` : "";

  return `<details class="facet" data-facet-group="${esc(key)}"${ui.open.has(key) || selected.size ? " open" : ""}>
    <summary>${esc(cfg.facetTitles[key])}${badge}</summary>
    ${search}<ul>${items}</ul>${toggle}
  </details>`;
}

function renderFacets(pool) {
  // Re-rendering replaces the elements, so remember focus and caret position.
  const focused = document.activeElement?.dataset?.fid;
  const caret = document.activeElement?.selectionStart;

  els.facets.innerHTML = cfg.facets.map((f) => renderFacetGroup(f, facetCounts(pool, f.key))).join("");

  if (focused) {
    const el = [...els.facets.querySelectorAll("[data-fid]")].find((e) => e.dataset.fid === focused);
    if (el) {
      el.focus();
      if (caret != null && el.type === "search") el.setSelectionRange(caret, caret);
    }
  }
}

function renderActiveFilters() {
  const chips = [];
  for (const [key, values] of Object.entries(state.filters)) {
    for (const value of values) {
      chips.push(`<button type="button" class="active-filter" data-remove="${esc(key)}" data-value="${esc(value)}" aria-label="${esc(t("remove_filter"))}: ${esc(label(key, value))}">
        <span>${esc(cfg.facetTitles[key])}:</span> ${esc(label(key, value))}</button>`);
    }
  }
  if (state.yearFrom || state.yearTo) {
    chips.push(`<button type="button" class="active-filter" data-remove="year" aria-label="${esc(t("remove_filter"))}: ${esc(t("year"))}">
      <span>${esc(t("year"))}:</span> ${esc(state.yearFrom || "…")}–${esc(state.yearTo || "…")}</button>`);
  }
  if (chips.length > 1) {
    chips.push(`<button type="button" class="link-button" data-remove="all">${esc(t("reset_filters"))}</button>`);
  }
  els.active.innerHTML = chips.join("");
  els.filtersOpen.textContent = selectedCount() ? `${t("filters")} (${selectedCount()})` : t("filters");
}

function renderCard(doc, terms) {
  const authors =
    doc.authors.length > 3 ? `${doc.authors.slice(0, 3).join(", ")} ${t("et_al")}` : doc.authors.join(", ");
  const badges = [
    ...doc.type.map((v) => `<li class="badge badge-type">${esc(label("type", v))}</li>`),
    ...doc.level.map((v) => `<li class="badge">${esc(label("level", v))}</li>`),
    ...doc.language.map((v) => `<li class="badge">${esc(label("language", v))}</li>`),
    ...doc.license.slice(0, 1).map((v) => `<li class="badge">${esc(v)}</li>`),
    doc.year ? `<li class="badge">${doc.year}</li>` : "",
  ].join("");
  const link = doc.links[0]
    ? `<a class="card-link" href="${esc(doc.links[0])}" target="_blank" rel="noopener">${esc(t("open_resource"))} ↗</a>`
    : "";

  return `<li class="card">
    <h3 class="card-title"><a href="${cfg.oerBase}${doc.id}/">${highlight(doc.title, terms)}</a></h3>
    ${authors ? `<p class="card-authors">${esc(authors)}</p>` : ""}
    <p class="card-snippet">${snippet(doc.description || doc.teaches || "", terms)}</p>
    <div class="card-meta"><ul class="badges">${badges}</ul>${link}</div>
  </li>`;
}

function render() {
  const hits = search();
  const pool = hits ? hits.map((h) => byId.get(h.id)) : docs;
  const terms = new Map(hits?.map((h) => [h.id, h.terms]) ?? []);

  let results = pool.filter((doc) => matches(doc));
  const sort = state.sort && (state.sort !== "relevance" || hits) ? state.sort : hits ? "relevance" : "newest";
  if (SORTS[sort]) results = [...results].sort(SORTS[sort]);
  els.sort.value = sort;

  renderFacets(pool);
  renderActiveFilters();

  els.count.textContent = plural("results", results.length);
  els.results.innerHTML = results.length
    ? results.slice(0, state.shown).map((doc) => renderCard(doc, terms.get(doc.id))).join("")
    : `<li class="empty">${esc(t("no_results"))}</li>`;
  els.more.hidden = results.length <= state.shown;

  writeURL();
}

// --- events ----------------------------------------------------------------------

function update() {
  state.shown = PAGE_SIZE;
  render();
}

function toggleFilter(key, value, on) {
  const values = (state.filters[key] ??= new Set());
  on ? values.add(value) : values.delete(value);
  if (!values.size) delete state.filters[key];
  update();
}

function bindEvents() {
  let timer;
  els.q.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.q = els.q.value;
      update();
    }, 120);
  });

  els.sort.addEventListener("change", () => {
    state.sort = els.sort.value;
    update();
  });

  for (const [el, field] of [[els.yearFrom, "yearFrom"], [els.yearTo, "yearTo"]]) {
    el.addEventListener("change", () => {
      state[field] = el.value;
      update();
    });
  }

  els.facets.addEventListener("change", (e) => {
    const { facet, value } = e.target.dataset;
    if (facet) toggleFilter(facet, value, e.target.checked);
  });

  els.facets.addEventListener("input", (e) => {
    const key = e.target.dataset.facetSearch;
    if (!key) return;
    ui.facetQuery[key] = e.target.value;
    render();
  });

  els.facets.addEventListener("click", (e) => {
    const key = e.target.dataset.expand;
    if (!key) return;
    ui.expanded.has(key) ? ui.expanded.delete(key) : ui.expanded.add(key);
    render();
  });

  // <details> toggle events don't bubble, so listen in the capture phase.
  els.facets.addEventListener(
    "toggle",
    (e) => {
      const key = e.target.dataset?.facetGroup;
      if (key) e.target.open ? ui.open.add(key) : ui.open.delete(key);
    },
    true,
  );

  els.active.addEventListener("click", (e) => {
    const button = e.target.closest("[data-remove]");
    if (!button) return;
    const { remove, value } = button.dataset;
    if (remove === "all") {
      state.filters = {};
      state.yearFrom = state.yearTo = "";
    } else if (remove === "year") {
      state.yearFrom = state.yearTo = "";
    } else {
      return toggleFilter(remove, value, false);
    }
    update();
  });

  els.more.addEventListener("click", () => {
    state.shown += PAGE_SIZE;
    render();
  });

  // Mobile filter drawer.
  const setDrawer = (open) => {
    document.body.classList.toggle("filters-open", open);
    els.filtersOpen.setAttribute("aria-expanded", open);
    if (open) els.filtersClose.focus();
  };
  els.filtersOpen.addEventListener("click", () => setDrawer(true));
  els.filtersClose.addEventListener("click", () => {
    setDrawer(false);
    els.filtersOpen.focus();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("filters-open")) {
      setDrawer(false);
      els.filtersOpen.focus();
    }
  });
}

function syncControls() {
  els.q.value = state.q;
  els.yearFrom.value = state.yearFrom;
  els.yearTo.value = state.yearTo;
  if (state.yearFrom || state.yearTo) els.yearFrom.closest("details").open = true;
}

async function init() {
  readURL();
  syncControls();
  bindEvents();
  try {
    docs = await (await fetch(cfg.indexURL)).json();
  } catch (err) {
    els.count.textContent = String(err);
    return;
  }
  byId = new Map(docs.map((d) => [d.id, d]));
  buildIndex();
  render();
}

init();
