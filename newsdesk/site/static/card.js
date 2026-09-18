// 事件卡交互：角标悬停显示原文片段；点击跳到页面内原文段落并高亮；原文段落里标出被引片段。
(function () {
  var dataEl = document.getElementById("cites");
  if (!dataEl) return;
  var cites = JSON.parse(dataEl.textContent);
  var pop = document.querySelector(".popover");

  function norm(s) { return s.replace(/\s+/g, " ").trim(); }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // 在一段文本里把若干 quote 包成 <mark>（忽略大小写与空白差异）
  function highlight(text, quotes) {
    var t = norm(text), lower = t.toLowerCase(), ranges = [];
    quotes.forEach(function (q) {
      var nq = norm(q).toLowerCase();
      if (nq.length < 2) return;
      var i = lower.indexOf(nq);
      if (i >= 0) ranges.push([i, i + nq.length]);
    });
    ranges.sort(function (a, b) { return a[0] - b[0]; });
    var out = "", pos = 0;
    ranges.forEach(function (r) {
      if (r[0] < pos) return;
      out += escapeHtml(t.slice(pos, r[0])) + "<mark>" + escapeHtml(t.slice(r[0], r[1])) + "</mark>";
      pos = r[1];
    });
    return out + escapeHtml(t.slice(pos));
  }

  document.querySelectorAll(".passage").forEach(function (el) {
    var quotes = JSON.parse(el.getAttribute("data-quotes") || "[]");
    if (quotes.length) el.innerHTML = highlight(el.textContent, quotes);
  });

  function showPop(a) {
    var c = cites[a.getAttribute("data-cite")];
    if (!c || !pop) return;
    pop.innerHTML = '<div class="pop-quote">' + highlight(c.text.length > 600 ? c.quote : c.text, [c.quote]) +
      '</div><div class="pop-src">' + escapeHtml(c.source + " · " + c.doc_title + (c.date && c.date !== "时间未知" ? " · " + c.date : "")) +
      (c.kind === "headline" ? "（媒体标题）" : "") + "</div>";
    pop.hidden = false;
    var r = a.getBoundingClientRect();
    var top = window.scrollY + r.bottom + 8;
    var left = Math.max(16, Math.min(window.scrollX + r.left - 20, window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 16));
    pop.style.top = top + "px";
    pop.style.left = left + "px";
  }
  function hidePop() { if (pop) pop.hidden = true; }

  document.querySelectorAll(".cite").forEach(function (a) {
    a.addEventListener("mouseenter", function () { showPop(a); });
    a.addEventListener("focus", function () { showPop(a); });
    a.addEventListener("mouseleave", hidePop);
    a.addEventListener("blur", hidePop);
    a.addEventListener("click", function (e) {
      var c = cites[a.getAttribute("data-cite")];
      hidePop();
      if (c && c.kind === "headline") {
        e.preventDefault();
        window.open(c.url, "_blank", "noopener");
        return;
      }
      var target = document.getElementById("p-" + (c && c.passage_id));
      if (target) {
        e.preventDefault();
        // 段落可能在「附属文件 / 上一版文件」的折叠块里：先展开再跳
        var fold = target.closest("details");
        while (fold) {
          fold.open = true;
          fold = fold.parentElement && fold.parentElement.closest("details");
        }
        target.scrollIntoView({ block: "center" });
        target.classList.remove("flash");
        void target.offsetWidth;
        target.classList.add("flash");
        history.replaceState(null, "", "#p-" + c.passage_id);
      }
    });
  });
  document.addEventListener("scroll", hidePop, { passive: true });
})();
