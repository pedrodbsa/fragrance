// Table behaviour shared by every page.

// Click a column header of a table.sortable to sort its rows; click again to reverse.
// A cell's data-sort overrides its text (dates, prices); empty values always go last.
// The sort is kept in the address (?sort=price, ?sort=-price for reversed; a page's second
// table uses sort2, and so on), so reloading or sharing the link keeps it.
document.querySelectorAll("table.sortable").forEach((table, n) => {
  const param = n === 0 ? "sort" : `sort${n + 1}`;
  const headers = [...table.querySelectorAll("thead th")];
  headers.forEach((th, column) => {
    if (!th.textContent.trim() || th.hasAttribute("data-nosort")) return;
    th.classList.add("sorter");
    th.dataset.key = th.textContent.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
    th.addEventListener("click", () => {
      sortBy(table, headers, column, th.dataset.dir !== "asc");
      remember(param, (th.dataset.dir === "asc" ? "" : "-") + th.dataset.key);
    });
  });
  const saved = new URLSearchParams(location.search).get(param);
  if (saved) {
    const column = headers.findIndex(th => th.dataset.key === saved.replace(/^-/, ""));
    if (column >= 0) sortBy(table, headers, column, !saved.startsWith("-"));
  }
});

function sortBy(table, headers, column, ascending) {
  headers.forEach(other => delete other.dataset.dir);
  headers[column].dataset.dir = ascending ? "asc" : "desc";
  const body = table.tBodies[0];
  const rows = [...body.rows].map(row => [value(row.cells[column]), row]);
  rows.sort(([a], [b]) => {
    if (a === "" || b === "") return (a === "") - (b === "");
    const order = typeof a === "number" && typeof b === "number" ? a - b
      : String(a).localeCompare(String(b), undefined, {numeric: true, sensitivity: "base"});
    return ascending ? order : -order;
  });
  rows.forEach(([, row]) => body.appendChild(row));
}

function remember(param, sort) {
  const url = new URL(location.href);
  url.searchParams.set(param, sort);
  history.replaceState(null, "", url);
  // Forms send you back to this page when done: keep the sort there too.
  document.querySelectorAll("input[name=back]").forEach(input => input.value = url.pathname + url.search);
}

function value(cell) {
  if (!cell) return "";
  const text = (cell.dataset.sort ?? cell.textContent).trim();
  if (text === "" || text === "—") return "";
  const number = text.replace(/[€,\s]/g, "");
  return /^-?\d+(\.\d+)?$/.test(number) ? parseFloat(number) : text;
}

// Click anywhere on a row that has a checkbox to tick it, not only the box itself. Links,
// buttons and other controls in the row keep working as usual.
document.addEventListener("click", event => {
  const row = event.target.closest("tbody tr");
  if (!row || event.target.closest("a, button, input, select, label, textarea")) return;
  const box = row.querySelector("td:first-child input[type=checkbox]");
  if (!box) return;
  box.checked = !box.checked;
  box.dispatchEvent(new Event("change", {bubbles: true}));  // e.g. the Orders page totals
});
