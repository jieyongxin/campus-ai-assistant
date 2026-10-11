/**
 * 一行代码把校园 AI 客服挂到学校官网上。
 *
 * <script src="https://你的域名/widget.js"
 *         data-api="https://你的域名"
 *         data-color="#0B4F9E"
 *         data-title="滇池学院智能客服"
 *         data-position="right"
 *         defer></script>
 */
(function () {
  var script = document.currentScript || (function () {
    var all = document.getElementsByTagName("script");
    return all[all.length - 1];
  })();
  if (!script || script.dataset.dcaiMounted) return;
  script.dataset.dcaiMounted = "1";
  var api = (script.dataset.api || new URL(script.src, location.href).origin).replace(/\/$/, "");
  var color = script.dataset.color || "#0B4F9E";
  var title = script.dataset.title || "智能客服";
  var side = script.dataset.position === "left" ? "left:22px" : "right:22px";
  var root = document.createElement("div");
  root.setAttribute("data-dcai-root", "");
  root.style.cssText = "position:fixed;bottom:0;" + side +
    ";z-index:2147483000;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif";
  var panel = document.createElement("div");
  panel.style.cssText = "position:fixed;bottom:96px;" + side +
    ";width:400px;height:min(680px,calc(100vh - 130px));background:#fff;border-radius:18px;overflow:hidden;" +
    "box-shadow:0 18px 60px rgba(16,38,73,.28);transition:opacity .22s ease,transform .22s ease;" +
    "opacity:0;transform:translateY(14px) scale(.98);pointer-events:none;";
  var frame = document.createElement("iframe");
  frame.title = title;
  frame.setAttribute("allow", "clipboard-write");
  frame.style.cssText = "width:100%;height:100%;border:0;display:block";
  panel.appendChild(frame);
  var btn = document.createElement("button");
  btn.type = "button";
  btn.setAttribute("aria-label", title);
  btn.style.cssText = "display:flex;align-items:center;gap:9px;height:54px;padding:0 20px;border:0;" +
    "border-radius:27px;background:" + color + ";color:#fff;font-size:15px;font-weight:600;cursor:pointer;" +
    "box-shadow:0 10px 28px rgba(11,79,158,.36);margin-bottom:22px;font-family:inherit;transition:transform .18s";
  btn.innerHTML = '<span style="font-size:19px">💬</span><span>' + title + "</span>";
  var opened = false;
  function toggle(open) {
    opened = (open === undefined) ? !opened : open;
    if (opened && !frame.src) frame.src = api + "/";
    panel.style.opacity = opened ? "1" : "0";
    panel.style.transform = opened ? "none" : "translateY(14px) scale(.98)";
    panel.style.pointerEvents = opened ? "auto" : "none";
    btn.querySelector("span:last-child").textContent = opened ? "收起对话" : title;
  }
  btn.onclick = function () { toggle(); };
  btn.onmouseenter = function () { btn.style.transform = "translateY(-2px)"; };
  btn.onmouseleave = function () { btn.style.transform = "none"; };
  if (window.matchMedia("(max-width:560px)").matches) {
    panel.style.width = "calc(100vw - 24px)";
    panel.style.height = "calc(100vh - 120px)";
    panel.style.bottom = "88px";
  }
  root.appendChild(panel);
  root.appendChild(btn);
  document.body.appendChild(root);
  window.DCAI = { open: function () { toggle(true); }, close: function () { toggle(false); } };
})();
