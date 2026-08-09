const $ = id => document.getElementById(id);
const token = window.DEPLOY_SYS_TOKEN;
let state = { projects: [], revision: 0, active_execution: null };
let selected = { project: null, service: null, target: null };
let mode = "run";
let dirty = false;
let activeExecution = null;
let outputCursor = 0;
let polling = false;
let editing = { project: false, service: false, target: false };

const lines = value => value.split(/\r?\n/).map(line => line.trimEnd()).filter(line => line.trim());
const shellModes = new Set(["auto", "zsh", "bash", "powershell", "cmd"]);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", "X-Deploy-Sys-Token": token, ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json();
  if (!response.ok || body.error) {
    const error = new Error(body.error || response.statusText);
    error.code = body.code;
    throw error;
  }
  return body;
}

function toast(message, type = "") {
  const node = $("toast");
  node.textContent = message;
  node.className = `show ${type}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => { node.className = ""; }, 3600);
}

async function guarded(button, action, successMessage = "") {
  if (button) button.disabled = true;
  try {
    const result = await action();
    if (successMessage) toast(successMessage, "success");
    return result;
  } catch (error) {
    toast(error.message || "操作失败。", "error");
    return null;
  } finally {
    if (button) button.disabled = false;
    updateControls();
  }
}

function currentProject() { return state.projects.find(project => project.id === selected.project) || null; }
function services() { return currentProject()?.services || []; }
function currentService() { return services().find(service => service.id === selected.service) || null; }
function targets() { return currentService()?.targets || {}; }
function currentTarget() { return targets()[selected.target] || null; }
function currentLines() { return mode === "status" ? (currentTarget()?.status_commands || []) : (currentTarget()?.commands?.run || []); }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

function normalizeSelection() {
  if (!currentProject()) selected.project = state.projects[0]?.id || null;
  if (!currentService()) selected.service = services()[0]?.id || null;
  if (!currentTarget()) selected.target = Object.keys(targets())[0] || null;
}

function applyState(nextState) {
  state = nextState;
  normalizeSelection();
  $("configPath").textContent = nextState.config_path || "";
  $("version").textContent = `v${nextState.version || ""}`;
  if (nextState.recovered_from_backup) toast("检测到配置损坏，已从最近备份恢复。", "error");
  if (nextState.active_execution && !activeExecution) connectExecution(nextState.active_execution);
  render();
}

async function reload(force = false) {
  if (dirty && !force && !confirm("命令尚未保存，刷新会丢失本次编辑。是否继续？")) return false;
  const data = await api("/api/state");
  dirty = false;
  applyState(data);
  return true;
}

function safeChange(change) {
  if (dirty && !confirm("命令尚未保存，切换后会丢失本次编辑。是否继续？")) return;
  change();
  dirty = false;
  render();
}

function item(label, sub, active, click) {
  const node = document.createElement("div");
  node.className = `item${active ? " active" : ""}`;
  node.innerHTML = `<div>${escapeHtml(label)}</div>${sub ? `<div class="sub">${escapeHtml(sub)}</div>` : ""}`;
  node.addEventListener("click", click);
  return node;
}

function render() {
  const projectBox = $("projects"); projectBox.replaceChildren();
  state.projects.forEach(project => projectBox.appendChild(item(project.name || project.id, project.id, project.id === selected.project, () => safeChange(() => { selected.project = project.id; selected.service = null; selected.target = null; }))));
  const serviceBox = $("services"); serviceBox.replaceChildren();
  services().forEach(service => serviceBox.appendChild(item(service.name || service.id, service.id, service.id === selected.service, () => safeChange(() => { selected.service = service.id; selected.target = null; }))));
  const targetBox = $("targets"); targetBox.replaceChildren();
  Object.keys(targets()).forEach(targetName => {
    const button = document.createElement("button");
    button.className = `target${targetName === selected.target ? " active" : ""}`;
    button.textContent = targetName;
    button.addEventListener("click", () => safeChange(() => { selected.target = targetName; }));
    targetBox.appendChild(button);
  });
  document.querySelectorAll(".tab").forEach(tab => tab.classList.toggle("active", tab.dataset.mode === mode));
  $("commandLabel").textContent = mode === "status" ? "状态检查命令，可直接粘贴多行" : "执行命令，可直接粘贴多行";
  if (!dirty) $("commands").value = currentLines().join("\n");
  $("shellMode").value = currentTarget()?.shell || "auto";
  $("dirty").hidden = !dirty;
  $("projectDetails").textContent = detailsText();
  updateControls();
}

function detailsText() {
  const project = currentProject();
  if (!project) return `还没有项目。\n配置文件：${state.config_path || ""}`;
  const output = [`项目：${project.name} (${project.id})`, `配置文件：${state.config_path || ""}`, "", "服务："];
  for (const service of project.services || []) {
    output.push(`- ${service.name || service.id} (${service.id})`);
    for (const [targetName, target] of Object.entries(service.targets || {})) {
      const runCount = (target.commands?.run || []).length;
      const statusCount = (target.status_commands || []).length;
      output.push(`  ${targetName}: 执行 ${runCount} 行，状态检查 ${statusCount} 行`);
    }
  }
  return output.join("\n");
}

function updateControls() {
  const hasProject = Boolean(currentProject());
  const hasService = Boolean(currentService());
  const hasTarget = Boolean(currentTarget());
  const running = Boolean(activeExecution && !activeExecution.done);
  $("addServiceBtn").disabled = !hasProject;
  $("editProjectBtn").disabled = !hasProject;
  $("deleteProjectBtn").disabled = !hasProject;
  $("addTargetBtn").disabled = !hasService;
  $("editServiceBtn").disabled = !hasService;
  $("deleteServiceBtn").disabled = !hasService;
  $("editTargetBtn").disabled = !hasTarget;
  $("deleteTargetBtn").disabled = !hasTarget;
  $("saveCommandsBtn").disabled = !hasTarget || running;
  $("executeBtn").disabled = !hasTarget || dirty || running || !currentLines().length;
  $("executeBtn").textContent = mode === "status" ? "执行检查" : "执行";
  $("cancelBtn").hidden = !running;
}

function openDialog(id) { $(id).showModal(); }
function closeDialog(id) { $(id).close(); }

function showProjectDialog(edit = false) {
  editing.project = edit;
  const project = currentProject();
  $("projectDialogTitle").textContent = edit ? "编辑项目" : "新增项目";
  $("projectId").value = edit ? project.id : "";
  $("projectName").value = edit ? project.name || project.id : "";
  openDialog("projectDialog");
}

function showServiceDialog(edit = false) {
  if (!currentProject()) return toast("请先选择项目。", "error");
  editing.service = edit;
  const service = currentService();
  $("serviceDialogTitle").textContent = edit ? "编辑服务" : "新增服务";
  $("serviceId").value = edit ? service.id : "";
  $("serviceName").value = edit ? service.name || service.id : "";
  $("serviceCreateFields").hidden = edit;
  if (!edit) { $("serviceTarget").value = "默认"; $("serviceCommands").value = ""; }
  openDialog("serviceDialog");
}

function showTargetDialog(edit = false) {
  if (!currentService()) return toast("请先选择服务。", "error");
  editing.target = edit;
  const target = currentTarget();
  $("targetDialogTitle").textContent = edit ? "编辑执行目标" : "新增执行目标";
  $("targetName").value = edit ? selected.target : "默认";
  $("targetShell").value = edit ? target.shell || "auto" : "auto";
  $("targetCreateFields").hidden = edit;
  if (!edit) $("targetCommands").value = "";
  openDialog("targetDialog");
}

async function submitProject(event) {
  event.preventDefault();
  const oldId = selected.project;
  const data = await guarded(event.submitter, () => api(editing.project ? "/api/projects/update" : "/api/projects", { method: "POST", body: JSON.stringify({ revision: state.revision, project_id: oldId, id: $("projectId").value, name: $("projectName").value }) }), "项目已保存。");
  if (!data) return;
  selected.project = $("projectId").value.trim(); selected.service = null; selected.target = null;
  dirty = false; closeDialog("projectDialog"); applyState(data.state);
}

async function submitService(event) {
  event.preventDefault();
  const payload = editing.service ? { revision: state.revision, project_id: selected.project, service_id: selected.service, id: $("serviceId").value, name: $("serviceName").value } : { revision: state.revision, project_id: selected.project, id: $("serviceId").value, name: $("serviceName").value, target_name: $("serviceTarget").value, commands: lines($("serviceCommands").value) };
  const data = await guarded(event.submitter, () => api(editing.service ? "/api/services/update" : "/api/services", { method: "POST", body: JSON.stringify(payload) }), "服务已保存。");
  if (!data) return;
  selected.service = $("serviceId").value.trim(); selected.target = editing.service ? selected.target : $("serviceTarget").value.trim(); dirty = false;
  closeDialog("serviceDialog"); applyState(data.state);
}

async function submitTarget(event) {
  event.preventDefault();
  const shell = $("targetShell").value.trim().toLowerCase() || "auto";
  if (!shellModes.has(shell)) return toast("Shell 仅支持 auto、zsh、bash、powershell 或 cmd。", "error");
  const payload = editing.target ? { revision: state.revision, project_id: selected.project, service_id: selected.service, target_name: selected.target, name: $("targetName").value, shell } : { revision: state.revision, project_id: selected.project, service_id: selected.service, target_name: $("targetName").value, shell, commands: lines($("targetCommands").value) };
  const data = await guarded(event.submitter, () => api(editing.target ? "/api/targets/update" : "/api/targets", { method: "POST", body: JSON.stringify(payload) }), "执行目标已保存。");
  if (!data) return;
  selected.target = $("targetName").value.trim(); dirty = false; closeDialog("targetDialog"); applyState(data.state);
}

async function saveCommands() {
  const shell = $("shellMode").value.trim().toLowerCase() || "auto";
  if (!shellModes.has(shell)) return toast("Shell 仅支持 auto、zsh、bash、powershell 或 cmd。", "error");
  const commandList = lines($("commands").value);
  if (!commandList.length) return toast("至少需要输入一行命令。", "error");
  const endpoint = "/api/commands";
  const data = await guarded($("saveCommandsBtn"), () => api(endpoint, { method: "POST", body: JSON.stringify({ revision: state.revision, project_id: selected.project, service_id: selected.service, target_name: selected.target, mode, commands: commandList, shell }) }), "命令已保存。");
  if (!data) return;
  dirty = false; applyState(data.state);
}

async function deleteSelected(kind) {
  const labels = { project: currentProject()?.name || selected.project, service: currentService()?.name || selected.service, target: selected.target };
  if (!confirm(`确认删除${kind === "project" ? "项目" : kind === "service" ? "服务" : "执行目标"}“${labels[kind]}”？`)) return;
  const data = await guarded(null, () => api("/api/delete", { method: "POST", body: JSON.stringify({ revision: state.revision, kind, project_id: selected.project, service_id: selected.service, target_name: selected.target }) }), "已删除。");
  if (!data) return;
  if (kind === "project") selected = { project: null, service: null, target: null };
  if (kind === "service") { selected.service = null; selected.target = null; }
  if (kind === "target") selected.target = null;
  dirty = false; applyState(data.state);
}

async function execute() {
  const endpoint = mode === "status" ? "/api/status-executions" : "/api/executions";
  const data = await guarded($("executeBtn"), () => api(endpoint, { method: "POST", body: JSON.stringify({ project_id: selected.project, service_id: selected.service, target_name: selected.target }) }));
  if (!data) return;
  $("log").textContent = "";
  connectExecution(data.execution);
  toast("任务已开始执行。", "success");
}

async function cancelExecution() {
  if (!activeExecution) return;
  await guarded($("cancelBtn"), () => api("/api/executions/cancel", { method: "POST", body: JSON.stringify({ execution_id: activeExecution.id }) }), "已发送取消请求。");
}

function connectExecution(execution) {
  activeExecution = execution;
  outputCursor = 0;
  polling = false;
  updateControls();
  pollExecution();
}

async function pollExecution() {
  if (!activeExecution || polling) return;
  polling = true;
  try {
    const data = await api(`/api/executions/${encodeURIComponent(activeExecution.id)}?cursor=${outputCursor}`);
    if (data.truncated) $("log").textContent += "\n[早期输出已截断，完整内容请查看日志。]\n";
    if (data.output) appendLog(data.output);
    outputCursor = data.cursor;
    activeExecution = data;
    if (data.done) {
      toast(`任务结束：${statusLabel(data.status)}${data.log_path ? `，日志：${data.log_path}` : ""}`, data.status === "success" ? "success" : "error");
      activeExecution = null;
    }
  } catch (error) {
    toast(error.message || "读取执行日志失败。", "error");
    activeExecution = null;
  } finally {
    polling = false;
    updateControls();
  }
  if (activeExecution) window.setTimeout(pollExecution, 500);
}

function statusLabel(status) { return ({ running: "运行中", success: "成功", failed: "失败", cancelled: "已取消", timed_out: "超时" })[status] || status; }
function appendLog(text) { const log = $("log"); log.textContent += text; if (log.textContent.length > 300000) log.textContent = log.textContent.slice(-300000); log.scrollTop = log.scrollHeight; }

function bind() {
  $("refreshBtn").addEventListener("click", () => guarded($("refreshBtn"), () => reload()));
  $("addProjectBtn").addEventListener("click", () => showProjectDialog(false)); $("editProjectBtn").addEventListener("click", () => showProjectDialog(true));
  $("addServiceBtn").addEventListener("click", () => showServiceDialog(false)); $("editServiceBtn").addEventListener("click", () => showServiceDialog(true));
  $("addTargetBtn").addEventListener("click", () => showTargetDialog(false)); $("editTargetBtn").addEventListener("click", () => showTargetDialog(true));
  $("deleteProjectBtn").addEventListener("click", () => deleteSelected("project")); $("deleteServiceBtn").addEventListener("click", () => deleteSelected("service")); $("deleteTargetBtn").addEventListener("click", () => deleteSelected("target"));
  $("projectForm").addEventListener("submit", submitProject); $("serviceForm").addEventListener("submit", submitService); $("targetForm").addEventListener("submit", submitTarget);
  document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => closeDialog(button.dataset.close)));
  document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", () => safeChange(() => { mode = tab.dataset.mode; })));
  $("commands").addEventListener("input", () => { dirty = true; updateControls(); $("dirty").hidden = false; });
  $("shellMode").addEventListener("input", () => { dirty = true; updateControls(); $("dirty").hidden = false; });
  $("saveCommandsBtn").addEventListener("click", saveCommands); $("executeBtn").addEventListener("click", execute); $("cancelBtn").addEventListener("click", cancelExecution); $("clearLogBtn").addEventListener("click", () => { $("log").textContent = ""; });
  window.addEventListener("beforeunload", event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
}

window.addEventListener("load", async () => { bind(); await guarded(null, () => reload(true)); });
