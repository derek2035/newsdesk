// 归档搜索：一次加载预生成索引，客户端全文筛选。几千条规模不需要后端。
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var items = [];
  var gradeLabel = { below: "未达 C" };

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function readUrl() {
    var p = new URLSearchParams(location.search);
    ["q", "from", "to", "grade", "type", "source"].forEach(function (k) { if (p.get(k)) $(k).value = p.get(k); });
  }
  function writeUrl() {
    var p = new URLSearchParams();
    ["q", "from", "to", "grade", "type", "source"].forEach(function (k) { if ($(k).value) p.set(k, $(k).value); });
    var qs = p.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  }

  function render() {
    var q = $("q").value.trim().toLowerCase(), from = $("from").value, to = $("to").value;
    var grade = $("grade").value, type = $("type").value, source = $("source").value;
    var terms = q ? q.split(/\s+/) : [];
    var out = items.filter(function (it) {
      if (from && it.date < from) return false;
      if (to && it.date > to) return false;
      if (grade && it.grade !== grade) return false;
      if (type && it.type !== type) return false;
      if (source && it.sources.indexOf(source) < 0) return false;
      var hay = (it.title + " " + it.summary).toLowerCase();
      return terms.every(function (t) { return hay.indexOf(t) >= 0; });
    });
    $("count").textContent = "共 " + out.length + " 条";
    $("results").innerHTML = out.map(function (it) {
      var title = it.grade === "below" ? esc(it.title) : '<a class="a-title" href="events/' + esc(it.slug) + '.html">' + esc(it.title) + "</a>";
      return '<li><div class="a-meta"><time>' + esc(it.time) + '</time><span class="grade grade-' + esc(it.grade.replace("+", "plus")) + '">' +
        esc(gradeLabel[it.grade] || it.grade) + '</span><span class="type-chip">' + esc(it.type_label) + "</span><span>" +
        esc(it.primary_source) + (it.media_count ? " · " + it.media_count + " 家独立报道" : "") + "</span></div>" + title +
        (it.summary ? '<p class="a-sum">' + esc(it.summary) + "</p>" : "") + "</li>";
    }).join("");
    writeUrl();
  }

  fetch("data/index.json").then(function (r) { return r.json(); }).then(function (data) {
    items = data;
    var sources = {};
    data.forEach(function (it) { it.sources.forEach(function (s) { sources[s] = 1; }); });
    Object.keys(sources).sort().forEach(function (s) {
      var o = document.createElement("option"); o.value = s; o.textContent = s; $("source").appendChild(o);
    });
    readUrl();
    render();
  });
  ["q", "from", "to", "grade", "type", "source"].forEach(function (k) {
    $(k).addEventListener(k === "q" ? "input" : "change", render);
  });
})();
