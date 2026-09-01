const $ = (selector) => document.querySelector(selector);
let currentJobId = null;
let pendingOutlineJobId = null;
let taskDrawerTimer = null;

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

function setControlValue(selector, value) {
  const control = $(selector);
  if (control && value !== undefined && value !== null) control.value = String(value);
}

function restoreRequest(request = {}) {
  setControlValue("#objective", request.objective || request.topic || "");
  setControlValue("#audience", request.primary_audience);
  setControlValue("#brand", request.brand_name);
  setControlValue("#cta", request.call_to_action);
  setControlValue("#image-count", request.image_count);
  setControlValue("#theme", request.theme);
  setControlValue("#target-length", request.target_length);
  setControlValue("#tone", request.tone);
  setControlValue("#structure", request.structure);
  setControlValue("#fact-policy", request.fact_policy);
  setControlValue("#forbidden-words", request.forbidden_words);
  updateCount();
}

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

function resetWorkspace() {
  currentJobId = null;
  pendingOutlineJobId = null;
  $("#generation-form").reset();
  $("#objective").value = "";
  $("#files").value = "";
  $("#outline").value = "";
  $("#feedback").value = "";
  $("#preview").src = "about:blank";
  $("#outline-panel").hidden = true;
  $("#result-panel").hidden = true;
  $("#progress").hidden = true;
  $("#empty-state").hidden = false;
  clearError();
  renderFiles();
  updateCount();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openTaskDrawer() {
  window.clearTimeout(taskDrawerTimer);
  $("#task-backdrop").hidden = false;
  $("#task-drawer").hidden = false;
  document.body.classList.add("drawer-open");
  window.requestAnimationFrame(() => {
    $("#task-backdrop").classList.add("is-open");
    $("#task-drawer").classList.add("is-open");
  });
  loadJobs();
}

function closeTaskDrawer() {
  $("#task-backdrop").classList.remove("is-open");
  $("#task-drawer").classList.remove("is-open");
  document.body.classList.remove("drawer-open");
  taskDrawerTimer = window.setTimeout(() => {
    $("#task-backdrop").hidden = true;
    $("#task-drawer").hidden = true;
  }, 180);
}

function formatTaskDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未知" : new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function taskStatusLabel(status) {
  return status === "completed" ? "已完成" : status === "outline_ready" ? "待确认大纲" : "处理中";
}

function renderJobs(items) {
  const list = $("#task-list");
  list.replaceChildren();
  $("#task-count").textContent = String(items.length);
  $("#task-empty").hidden = Boolean(items.length);

  items.forEach((item) => {
    const row = document.createElement("article");
    row.className = "task-row";

    const statusLine = document.createElement("div");
    statusLine.className = "task-status-line";
    const status = document.createElement("span");
    status.className = `task-status ${item.status === "completed" ? "completed" : "pending"}`;
    status.textContent = taskStatusLabel(item.status);
    const date = document.createElement("time");
    date.dateTime = item.updated_at;
    date.textContent = formatTaskDate(item.updated_at);
    statusLine.append(status, date);

    const title = document.createElement("h3");
    title.textContent = item.title || item.topic || "未命名任务";
    const description = document.createElement("p");
    description.textContent = item.objective || "未填写内容目标";
    const meta = document.createElement("div");
    meta.className = "task-meta";
    meta.textContent = `${item.theme || "默认主题"}${item.parent_job_id ? " · 修改版本" : ""}`;

    const actions = document.createElement("div");
    actions.className = "task-actions";
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "task-open-button";
    openButton.textContent = item.status === "completed" ? "查看成品" : "继续任务";
    openButton.addEventListener("click", () => openJob(item.job_id));
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "task-delete-button";
    deleteButton.title = "删除任务";
    deleteButton.setAttribute("aria-label", `删除任务：${title.textContent}`);
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => removeJob(item.job_id, title.textContent));
    actions.append(openButton, deleteButton);
    row.append(statusLine, title, description, meta, actions);
    list.append(row);
  });
}

async function loadJobs() {
  $("#task-loading").hidden = false;
  try {
    const items = await requestJson("/api/jobs");
    renderJobs(items);
  } catch (error) {
    if (!$("#task-drawer").hidden) showError(getErrorMessage(error));
  } finally {
    $("#task-loading").hidden = true;
  }
}

async function openJob(jobId) {
  clearError();
  try {
    const data = await requestJson(`/api/jobs/${jobId}`);
    restoreRequest(data.request);
    closeTaskDrawer();
    if (data.status === "completed" && data.preview_url) {
      updateResult(data);
      showToast("已打开历史成品");
    } else {
      showOutline(data);
      showToast("已恢复待确认大纲");
    }
  } catch (error) {
    showError(getErrorMessage(error));
  }
}

async function removeJob(jobId, title) {
  if (!window.confirm(`确定删除“${title}”吗？该任务的文章和图片也会一并删除。`)) return;
  try {
    await requestJson(`/api/jobs/${jobId}`, { method: "DELETE" });
    if (currentJobId === jobId || pendingOutlineJobId === jobId) resetWorkspace();
    await loadJobs();
    showToast("任务已删除");
  } catch (error) {
    showError(getErrorMessage(error));
  }
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
    loadJobs();
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
    loadJobs();
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
    loadJobs();
  } catch (error) {
    showError(getErrorMessage(error));
  } finally {
    button.disabled = false;
    button.innerHTML = "生成新版本 <span aria-hidden=\"true\">↗</span>";
  }
});

$("#new-task").addEventListener("click", () => {
  closeTaskDrawer();
  resetWorkspace();
  showToast("已新建空白任务");
});
$("#open-tasks").addEventListener("click", openTaskDrawer);
$("#close-tasks").addEventListener("click", closeTaskDrawer);
$("#task-backdrop").addEventListener("click", closeTaskDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("#task-drawer").hidden) closeTaskDrawer();
});

requestJson("/api/health").then(() => { $("#health-label").textContent = "服务正常"; $(".status-dot").classList.add("online"); }).catch(() => { $("#health-label").textContent = "服务未连接"; });
loadThemes();
loadJobs();
