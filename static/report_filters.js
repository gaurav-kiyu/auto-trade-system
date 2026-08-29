/* Excel-like column filters for report tables.
 * Adds one filter row beneath <thead> for every report table unless
 * data-no-column-filters is present. Filtering is client-side and preserves
 * the current table rows. Dynamic tables are observed via MutationObserver.
 */
(function () {
  "use strict";
  const FILTERED = "data-report-filters-installed";

  function norm(v) { return String(v ?? "").trim().toLowerCase(); }

  function install(table) {
    if (!(table instanceof HTMLTableElement) || table.hasAttribute(FILTERED) || table.hasAttribute("data-no-column-filters") || table.tHead?.querySelector(".column-filter, .report-column-filter-row")) return;
    const thead = table.tHead;
    if (!thead || !thead.rows.length) return;
    const header = thead.rows[thead.rows.length - 1];
    const cols = header.cells.length;
    if (!cols) return;

    const row = document.createElement("tr");
    row.className = "report-column-filter-row";
    for (let i = 0; i < cols; i++) {
      const cell = document.createElement("th");
      cell.scope = "col";
      const input = document.createElement("input");
      input.type = "search";
      input.className = "report-column-filter";
      input.placeholder = "Filter…";
      input.setAttribute("aria-label", `Filter ${header.cells[i]?.textContent?.trim() || `column ${i + 1}`}`);
      input.dataset.column = String(i);
      cell.appendChild(input);
      row.appendChild(cell);
    }
    thead.appendChild(row);

    const apply = () => {
      const filters = [...row.querySelectorAll("input")].map(x => norm(x.value));
      [...table.tBodies].forEach(tbody => {
        [...tbody.rows].forEach(tr => {
          // Don't filter nested/subtotal rows without cells.
          const visible = filters.every((f, i) => !f || norm(tr.cells[i]?.textContent).includes(f));
          tr.hidden = !visible;
        });
      });
    };
    row.querySelectorAll("input").forEach(input => {
      input.addEventListener("input", apply);
      input.addEventListener("keydown", e => { if (e.key === "Escape") { input.value = ""; apply(); }});
    });
    table.setAttribute(FILTERED, "1");
  }

  function scan(root) {
    if (!root) return;
    if (root instanceof HTMLTableElement) install(root);
    root.querySelectorAll?.("table").forEach(install);
  }


  function collectTables() {
    return [...document.querySelectorAll("table")].map((table, idx) => {
      const thead = table.tHead;
      const headers = thead && thead.rows.length ? [...thead.rows[thead.rows.length - 1].cells].map(c => c.textContent.trim()) : [];
      const rows = [...table.tBodies].flatMap(tb => [...tb.rows].filter(r => !r.hidden).map(r => [...r.cells].map(c => c.textContent.trim())));
      return {name: table.getAttribute("data-report-name") || `Report${idx + 1}`, headers, rows};
    }).filter(t => t.headers.length);
  }

  async function exportPage(fmt) {
    const tables = collectTables();
    if (!tables.length) {
      window.alert("No tabular report data is available on this page.");
      return;
    }
    const res = await fetch(`/api/reports/table-export/${fmt}`, {
      method: "POST",
      credentials: "include",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({tables})
    });
    if (!res.ok) throw new Error(`Export failed: HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fmt === "xlsx" ? "report_export.xlsx" : "report_export.pdf";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function addExportToolbar() {
    if (document.querySelector("[data-report-export-toolbar]") || !document.querySelector("table")) return;
    const bar = document.createElement("div");
    bar.dataset.reportExportToolbar = "1";
    bar.style.cssText = "display:flex;gap:.5rem;flex-wrap:wrap;margin:0 0 1rem";
    for (const [fmt, label] of [["pdf","📄 Export PDF"],["xlsx","📊 Export Excel"]]) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "btn btn-ghost"; b.textContent = label;
      b.addEventListener("click", async () => {
        b.disabled = true;
        try { await exportPage(fmt); } catch (e) { console.error(e); window.alert("Report export failed. Check the Console/Network log."); }
        finally { b.disabled = false; }
      });
      bar.appendChild(b);
    }
    const first = document.querySelector("table");
    first.parentElement?.parentElement?.insertBefore(bar, first.parentElement);
  }
  function boot() {
    scan(document);
    addExportToolbar();
    const observer = new MutationObserver(mutations => {
      for (const m of mutations) for (const node of m.addedNodes) {
        if (node.nodeType === 1) { scan(node); addExportToolbar(); }
      }
    });
    observer.observe(document.documentElement, {childList: true, subtree: true});
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
