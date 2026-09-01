const $ = (selector) => document.querySelector(selector);
let currentJobId = null;
let pendingOutlineJobId = null;

function showError(message) {
  const banner = $("#error-banner");
  banner.textContent = message;
  banner.hidden = false;
}

function clearError() { $("#error-banner").hidden = true; }

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.hidden = false;
  window.setTimeout(() => { toast.hidden = true; }, 3500);
}

function setBusy(isBusy, detail) {
  $("#progress").hidden = !isBusy;
  $("#generation-form button[type=submit]").disabled = isBusy;
  $("#outline-form button[type=submit]").disabled = isBusy;
  $("#progress-detail").textContent = detail || "正在读取资料与受众上下文…";
  if (isBusy) $("#empty-state").hidden = true;
}

function getErrorMessage(error) {
  const detail = error?.detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || "输入有误").join("；");
  return detail || error?.message || "请求失败，请稍后重试";
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw data;
  return data;
}

function renderFiles() {
  const files = [...$("#files").files];
  const list = $("#file-list");
  list.textContent = files.length ? files.map((file) => `${file.name} · ${Math.ceil(file.size / 1024)} KB`).join("\n") : "尚未选择文件";
  list.classList.toggle("has-files", Boolean(files.length));
  list.style.whiteSpace = files.length ? "pre-line" : "normal";
}

function updateCount() { $("#char-count").textContent = `${$("#objective").value.length} / 300`; }

function requestPayload() {
  return {
    topic: $("#objective").value.trim().slice(0, 120),
    primary_audience: $("#audience").value,
    objective: $("#objective").value.trim(),
    brand_name: $("#brand").value.trim(),
    call_to_action: $("#cta").value.trim() || "了解更多",
    image_count: Number($("#image-count").value),
    theme: $("#theme").value,
    target_length: Number($("#target-length").value),
    tone: $("#tone").value,
    structure: $("#structure").value,
    fact_policy: $("#fact-policy").value,
    forbidden_words: $("#forbidden-words").value.trim(),
  };
}

function updateResult(data) {
  currentJobId = data.job_id;
  pendingOutlineJobId = null;
  $("#outline-panel").hidden = true;
  $("#result-title").textContent = data.title || "公众号成品";
  $("#result-subtitle").textContent = data.image_urls?.length ? `已生成 ${data.image_urls.length} 张配图，文章和排版预览已就绪。` : "文章和排版预览已就绪。";
  $("#preview").src = data.preview_url;
  $("#download-md").href = data.markdown_url;
  $("#download-html").href = data.html_url;
  $("#open-preview").onclick = () => window.open(data.preview_url, "_blank", "noopener");
  $("#result-panel").hidden = false;
  $("#empty-state").hidden = true;
  if (data.warnings?.length) showToast(data.warnings.join("；"));
  $("#result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function showOutline(data) {
  pendingOutlineJobId = data.job_id;
  $("#outline").value = data.outline;
  $("#result-panel").hidden = true;
  $("#outline-panel").hidden = false;
  $("#outline-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadThemes() {
  try {
    const data = await requestJson("/api/themes");
    $("#theme").innerHTML = data.themes.map((theme) => `<option>${theme}</option>`).join("");
  } catch { /* The built-in fallback remains usable. */ }
}

$("#files").addEventListener("change", renderFiles);
$("#objective").addEventListener("input", updateCount);

$("#generation-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  const files = [...$("#files").files];
  if (!files.length) return showError("请先添加至少一份资料文件。");
  if (!$("#audience").value) return showError("请选择一个主要用户。");
  if (!$("#objective").value.trim()) return showError("请描述这次想生成的内容。");
  const body = new FormData();
  body.append("request", JSON.stringify(requestPayload()));
  files.forEach((file) => body.append("files", file));
  setBusy(true, "正在根据资料和质量要求生成文章大纲…");
  try {
    const data = await requestJson("/api/outlines", { method: "POST", body });
    setBusy(false);
    showOutline(data);
    showToast("大纲已生成，请确认后再写正文");
  } catch (error) {
    setBusy(false);
    showError(getErrorMessage(error));
    $("#empty-state").hidden = false;
  }
});

$("#outline-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  if (!pendingOutlineJobId) return showError("请先生成文章大纲。");
  const outline = $("#outline").value.trim();
  if (outline.length < 20) return showError("请保留至少一条有实际内容的大纲要点。");
  const body = new FormData();
  body.append("outline", outline);
  setBusy(true, "正在按确认的大纲生成正文、图片和排版预览…");
  try {
    const data = await requestJson(`/api/outlines/${pendingOutlineJobId}/generate`, { method: "POST", body });
    setBusy(false);
    updateResult(data);
    showToast("公众号成品已生成");
  } catch (error) {
    setBusy(false);
    showError(getErrorMessage(error));
  }
});

$("#edit-brief").addEventListener("click", () => {
  $("#outline-panel").hidden = true;
  $("#generation-form").scrollIntoView({ behavior: "smooth", block: "start" });
});

$("#revision-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentJobId) return;
  const feedback = $("#feedback").value.trim();
  if (!feedback) return showToast("请先填写修改意见");
  const body = new FormData();
  body.append("feedback", feedback);
  const button = $("#revision-form button");
  button.disabled = true;
  button.textContent = "正在生成…";
  clearError();
  try {
    const data = await requestJson(`/api/jobs/${currentJobId}/revision`, { method: "POST", body });
    updateResult(data);
    $("#feedback").value = "";
    showToast("新版本已生成，原版本仍保留");
  } catch (error) {
    showError(getErrorMessage(error));
  } finally {
    button.disabled = false;
    button.innerHTML = "生成新版本 <span aria-hidden=\"true\">↗</span>";
  }
});

requestJson("/api/health").then(() => { $("#health-label").textContent = "服务正常"; $(".status-dot").classList.add("online"); }).catch(() => { $("#health-label").textContent = "服务未连接"; });
loadThemes();
