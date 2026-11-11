// Click a column header of a table.sortable to sort its rows; click again to reverse.
// A cell's data-sort overrides its text (dates, prices); empty values always go last.
document.querySelectorAll("table.sortable").forEach(table => {
  table.querySelectorAll("thead th").forEach((th, column) => {
    if (!th.textContent.trim() || th.hasAttribute("data-nosort")) return;
    th.classList.add("sorter");
    th.addEventListener("click", () => {
      const ascending = th.dataset.dir !== "asc";
      table.querySelectorAll("thead th").forEach(other => delete other.dataset.dir);
      th.dataset.dir = ascending ? "asc" : "desc";
      const body = table.tBodies[0];
      const rows = [...body.rows].map(row => [value(row.cells[column]), row]);
      rows.sort(([a], [b]) => {
        if (a === "" || b === "") return (a === "") - (b === "");
        const order = typeof a === "number" && typeof b === "number" ? a - b
          : String(a).localeCompare(String(b), undefined, {numeric: true, sensitivity: "base"});
        return ascending ? order : -order;
      });
      rows.forEach(([, row]) => body.appendChild(row));
    });
  });
});

function value(cell) {
  if (!cell) return "";
  const text = (cell.dataset.sort ?? cell.textContent).trim();
  if (text === "" || text === "—") return "";
  const number = text.replace(/[€,\s]/g, "");
  return /^-?\d+(\.\d+)?$/.test(number) ? parseFloat(number) : text;
}
