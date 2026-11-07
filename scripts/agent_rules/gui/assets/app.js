"use strict";
const $ = (id) => document.getElementById(id);
let session = "",
  repositories = [],
  selected = new Set(),
  previews = new Map(),
  busy = false,
  aiTarget = null,
  homeMemoryTarget = null,
  homeMemorySelected = new Set();
function log(text) {
  $("log").textContent += `\n[${new Date().toLocaleTimeString()}] ${text}\n`;
}
// Automatic preparation reruns on every selection or option change; repeat
// identical check and preview output as one line instead of the full text.
const lastPreparationLogs = new Map();
function logPreparation(repo, kind, text) {
  const key = `${repo.path}\0${kind}`;
  if (lastPreparationLogs.get(key) === text) {
    log(`${repo.name} · ${kind} · 이전 결과와 같음`);
    return;
  }
  lastPreparationLogs.set(key, text);
  log(`${repo.name} · ${kind}\n${text}`);
}
function clearAI() {
  $("ai-review").hidden = true;
  $("ai-summary").textContent = "저장소 1개를 선택하면 사용할 수 있습니다.";
  homeMemoryTarget = null;
  homeMemorySelected.clear();
  $("ai-memories").value = "";
  $("ai-home-files").replaceChildren();
  aiTarget = null;
  $("ai-rules").value = "";
  $("ai-result").textContent =
    "대상이 변경되었습니다. 규칙 제안을 다시 실행하세요.";
  $("ai-target").textContent = "아직 규칙 제안이 없습니다.";
  $("ai-files").textContent = "참조할 파일을 먼저 확인하세요.";
}
let preparationVersion = 0, preparationTimer = null, preparing = false;
function invalidate() {
  preparationVersion++;
  clearTimeout(preparationTimer);
  for (const repo of repositories) repo.preparation = "";
  previews.clear();
  $("apply").disabled = true;
  $("preview").replaceChildren();
}
function message(text) {
  $("message").textContent = text;
  $("message").className = "";
}
function showLog(open) {
  $("log-panel").hidden = !open;
  $("log-toggle").setAttribute("aria-expanded", String(open));
  $("log-toggle").textContent = open ? "로그 닫기" : "로그";
}
// Progress bar: a summary of the visible workflow, never a separate screen.
const PROFILE_LABELS = { auto: "기존 유지", codex: "Codex", claude: "Claude", gemini: "Gemini", all: "전체" };
function setStep(n, state, sub) {
  $(`step-${n}`).className = `is-${state}`;
  $(`step-${n}-dot`).textContent = state === "done" ? "✓" : state === "blocked" ? "!" : String(n);
  $(`step-${n}-sub`).textContent = sub;
}
function renderSteps() {
  const chosen = repositories.filter((r) => selected.has(r.path));
  if (!chosen.length) {
    setStep(1, "current", "선택 전");
    for (const n of [2, 3, 4]) setStep(n, "todo", "대기");
    return;
  }
  const plans = chosen.map((r) => previews.get(r.path));
  const blocked = chosen.some((r, i) => r.preparation === "준비 실패" ||
    (plans[i] && (!plans[i].token || plans[i].code)));
  const files = plans.reduce((n, plan) => n + (plan?.files?.length || 0), 0);
  const ready = plans.every(Boolean);
  setStep(1, "done", `${chosen.length}개 선택`);
  setStep(2, "done", `${PROFILE_LABELS[$("profile").value] || "기존 유지"} · ${$("visibility").value === "tracked" ? "공유" : "로컬 전용"}`);
  if (blocked) setStep(3, "blocked", "적용 불가 · 로그 확인");
  else if (preparing || scheduled) setStep(3, "current", "준비 중…");
  else if (ready) setStep(3, "done", files ? `${files}개 파일` : "변경 없음");
  else setStep(3, "todo", "대기");
  const applicable = !blocked && ready && files > 0;
  setStep(4, applicable && !busy ? "current" : "todo", applicable ? "적용 가능" : "대기");
}
function controls(value) {
  busy = value;
  document
    .querySelectorAll("button,select,textarea,input:not([readonly])")
    .forEach((e) => (e.disabled = value));
  updateApply();
  $("ai-close").disabled = false;
  $("log-copy").disabled = false;
  $("log-toggle").disabled = false;
  $("ai-preview").disabled = value || !aiTarget || !selected.has(aiTarget);
  render();
}
function updateApply() {
  const plans = [...selected].map((path) => previews.get(path));
  const changed = plans.filter((plan) => plan?.files?.length);
  const count = changed.reduce((total, plan) => total + plan.files.length, 0);
  $("apply").disabled = busy || preparing || !count ||
    plans.some((plan) => !plan?.token || plan.code);
  $("apply").textContent = count
    ? `적용 · ${changed.length}개 저장소 / ${count}개 파일`
    : "적용";
  $("preview-summary").textContent = !selected.size ? ""
    : preparing ? "준비 중…"
    : count ? `${changed.length}개 저장소 · ${count}개 파일` : "";
  renderSteps();
}
function statusTone(status) {
  if (/오류|실패|불가/.test(status)) return "danger";
  if (/중|대기|사용자 규칙/.test(status)) return "info";
  if (/경고|확인 필요|재검사/.test(status)) return "warning";
  if (/정상|설치됨|최신|준비 완료/.test(status)) return "success";
  return "neutral";
}
const STATUS_FILTERS = {
  attention: (tone) => ["warning", "danger", "info"].includes(tone),
  absent: (tone) => tone === "neutral",
};
function visibleRepositories() {
  const query = $("search").value.toLowerCase();
  const matches = STATUS_FILTERS[$("filter").value];
  return repositories.filter((r) => r.name.toLowerCase().includes(query) &&
    (!matches || matches(statusTone(r.error ? "오류" : r.status || ""))));
}
function agentSummary(repo) {
  const names = { codex: "Codex", claude: "Claude", gemini: "Gemini" };
  return Object.entries(names)
    .filter(([key]) => repo.agents?.[key] && repo.agents[key] !== "미설치")
    .map(([key, name]) => repo.agents[key] === "설치됨" ? name : `${name} (${repo.agents[key]})`)
    .join(" · ");
}
// Radio groups expose a select-like value so the settings code stays unchanged.
function segmented(id) {
  const group = $(id);
  if (!group.querySelectorAll) return;
  const radios = [...group.querySelectorAll('input[type="radio"]')];
  Object.defineProperty(group, "value", {
    get: () => radios.find((r) => r.checked)?.value ?? "",
    set: (value) => radios.forEach((r) => { r.checked = r.value === value; }),
  });
}
for (const id of ["profile", "operation", "visibility", "filter"]) segmented(id);
let scheduled = false;
function schedulePreparation() {
  invalidate();
  scheduled = selected.size > 0;
  render();
  if (!selected.size) {
    message("저장소를 선택하면 검사와 미리보기가 자동으로 준비됩니다.");
    return;
  }
  message("선택한 설정으로 검사와 미리보기를 준비합니다…");
  const version = preparationVersion;
  preparationTimer = setTimeout(() => prepareSelection(version), 350);
}
async function prepareSelection(version = preparationVersion) {
  if (version !== preparationVersion || !selected.size) return;
  if (busy || preparing) {
    preparationTimer = setTimeout(() => prepareSelection(version), 350);
    return;
  }
  preparing = true;
  scheduled = false;
  updateApply();
  const chosen = repositories.filter((repo) => selected.has(repo.path));
  try {
    for (const repo of chosen) {
      if (version !== preparationVersion) return;
      const settings = options(repo);
      const boundaries = aiTarget === repo.path
        ? $("ai-rules").value.split("\n").map((s) => s.trim()).filter(Boolean) : [];
      try {
        repo.preparation = "검사 중…";
        render();
        const checked = await api("check", settings);
        if (version !== preparationVersion) return;
        repo.status = checked.status;
        repo.agents = checked.agents;
        logPreparation(repo, "상태 확인", checked.log);
        repo.preparation = "미리보기 생성 중…";
        render();
        const plan = await api("preview", { ...settings, boundaries });
        if (version !== preparationVersion) return;
        previews.set(repo.path, plan);
        showPreview(repo, plan);
        logPreparation(repo, "미리보기", plan.log);
        repo.preparation = plan.code || !plan.token ? "적용 불가"
          : plan.files.length ? "준비 완료" : "이미 최신 상태";
      } catch (error) {
        if (version !== preparationVersion) return;
        previews.delete(repo.path);
        repo.preparation = "준비 실패";
        showPreviewNote(repo, "준비 실패 · 로그 확인");
        log(`${repo.name}: ${error.message}`);
      }
      render();
    }
    if (version !== preparationVersion) return;
    const blockedRepo = chosen.find((repo) => !previews.get(repo.path)?.token || previews.get(repo.path).code);
    const blocked = !!blockedRepo;
    if (blocked) showLog(true);
    const changed = chosen.some((repo) => previews.get(repo.path)?.files.length);
    const warnings = chosen.some((repo) => /경고|확인 필요|오류/.test(repo.status));
    message(blocked ? `${blockedRepo.name}: 적용할 수 없습니다 · 로그에서 원인을 확인하세요.`
      : !changed ? (warnings ? "변경 없음 · 검사 경고는 로그에서 확인하세요." : "이미 최신 상태입니다. 적용할 변경이 없습니다.")
      : `${warnings ? "검사 경고가 있습니다. " : ""}변경 내용을 검토한 뒤 적용하세요. 적용 전에는 파일이 바뀌지 않습니다.`);
    if (blocked) $("message").className = "error";
  } finally {
    preparing = false;
    updateApply();
    render();
  }
}
async function api(path, data) {
  const response = await fetch(`/api/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Session-Token": session },
    body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : JSON.stringify(result.detail),
    );
  return result;
}
function options(repo) {
  const profile =
    $("profile").value === "auto"
      ? repo.profile || "codex"
      : $("profile").value;
  return {
    path: repo.path,
    profile,
    visibility: $("visibility").value,
    skills: profile !== "gemini" && $("skills").checked,
    operation:
      $("operation").value === "auto"
        ? repo.profile
          ? "sync"
          : "install"
        : $("operation").value,
  };
}
function render() {
  $("ai-open").disabled = busy || preparing || selected.size !== 1;
  $("repositories").replaceChildren();
  const visible = visibleRepositories();
  const selectable = visible.filter((r) => !r.error);
  const allSelected = selectable.length > 0 && selectable.every((r) => selected.has(r.path));
  $("select-all").textContent = allSelected ? "선택 해제" : "전체 선택";
  $("select-all").disabled = busy || !selectable.length;
  $("skills").disabled = busy || $("profile").value === "gemini";
  if (!aiTarget)
    $("ai-summary").textContent = selected.size === 1
      ? "선택 사항 · 코드와 메모리를 읽고 규칙을 제안합니다."
      : "저장소 1개를 선택하면 사용할 수 있습니다.";
  $("preview-empty").hidden = $("preview").children.length > 0;
  for (const repo of visible) {
    const row = document.createElement("label");
    row.className = "repo";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = selected.has(repo.path);
    box.disabled = busy || !!repo.error;
    box.setAttribute("aria-label", `${repo.name} 선택`);
    box.onchange = async () => {
      box.checked ? selected.add(repo.path) : selected.delete(repo.path);
      clearAI();
      $("selected").textContent = `${selected.size}개 선택`;
      schedulePreparation();
    };
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = repo.name;
    row.title = repo.path;
    const agents = agentSummary(repo);
    if (agents) {
      const sub = document.createElement("small");
      sub.textContent = agents;
      name.append(sub);
    }
    const state = document.createElement("span");
    const status = repo.error ? "오류" : repo.status;
    state.className = `state tone-${statusTone(status)}`;
    state.textContent = status;
    if (repo.preparation) {
      const preparation = document.createElement("small");
      preparation.className = `preparation tone-${statusTone(repo.preparation)}`;
      preparation.textContent = repo.preparation;
      state.append(preparation);
    }
    row.append(box, name, state);
    $("repositories").append(row);
  }
  $("empty").hidden = repositories.length > 0;
  $("count").textContent = `${repositories.length}개`;
  renderSteps();
}
function previewGroup(repo, note, failed) {
  const group = document.createElement("div"),
    heading = document.createElement("h3"),
    label = document.createElement("span");
  group.className = "preview-repo";
  heading.textContent = repo.name;
  label.textContent = note;
  if (failed) label.className = "error";
  heading.append(label);
  group.append(heading);
  $("preview").append(group);
  return group;
}
function showPreviewNote(repo, note) {
  previewGroup(repo, note, true);
}
function diffStat(diff) {
  let add = 0, del = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+") && !line.startsWith("+++")) add++;
    else if (line.startsWith("-") && !line.startsWith("---")) del++;
  }
  return `+${add} −${del}`;
}
function showPreview(repo, data) {
  const blocked = data.code || !data.token;
  const group = previewGroup(
    repo,
    blocked ? "적용 불가 · 로그 확인" : data.files.length ? `${data.files.length}개 파일` : "이미 최신 상태",
    blocked,
  );
  for (const file of data.files) {
    const details = document.createElement("details"),
      summary = document.createElement("summary"),
      pre = document.createElement("pre");
    const diff = file.diff || "";
    for (const [className, text] of [["action", file.action], ["path", file.path], ["stat", diffStat(diff)]]) {
      const part = document.createElement("span");
      part.className = className;
      part.textContent = text;
      summary.append(part);
    }
    for (const line of diff.split("\n")) {
      const span = document.createElement("span");
      span.textContent = line + "\n";
      span.className = line.startsWith("+")
        ? "addition"
        : line.startsWith("-")
          ? "deletion"
          : "";
      pre.append(span);
    }
    details.append(summary, pre);
    group.append(details);
  }
}
async function run(action) {
  if (busy || preparing) return;
  if (action === "apply") {
    updateApply();
    if ($("apply").disabled) return;
    clearTimeout(preparationTimer);
  }
  const chosen = repositories.filter((r) => selected.has(r.path) &&
    (action !== "apply" || previews.get(r.path)?.files?.length));
  if (!chosen.length) {
    message("저장소를 먼저 선택하세요.");
    return;
  }
  if (action !== "apply") invalidate();
  controls(true);
  let failed = 0;
  try {
    for (const repo of chosen) {
      message(
        `${repo.name} · ${action === "apply" ? "적용" : action === "check" ? "상태 확인" : "미리보기"} 중…`,
      );
      try {
        const result = await api(
          action,
          action === "apply"
            ? { token: previews.get(repo.path)?.token }
            : action === "preview"
              ? {
                  ...options(repo),
                  boundaries:
                    aiTarget === repo.path
                      ? $("ai-rules")
                          .value.split("\n")
                          .map((s) => s.trim())
                          .filter(Boolean)
                      : [],
                }
              : options(repo),
        );
        log(`${repo.name}\n${result.log}`);
        if (action === "preview") {
          previews.set(repo.path, result);
          showPreview(repo, result);
        }
        if (action === "check") {
          repo.status = result.status;
          repo.agents = result.agents;
        }
        if (action === "apply") {
          previews.delete(repo.path);
          repo.preparation = "";
          repo.status = result.code ? "적용 오류" : "적용 완료 · 재검사 필요";
          if (!result.code) {
            repo.profile = options(repo).profile;
            repo.status = "적용 완료 · 검사 중…";
            render();
            message(`${repo.name} · 적용 후 상태 확인 중…`);
            try {
              const checked = await api("check", options(repo));
              repo.status = checked.status;
              repo.agents = checked.agents;
              log(`${repo.name} · 적용 후 상태 확인\n${checked.log}`);
              if (checked.code) failed++;
            } catch (error) {
              failed++;
              repo.status = "적용 완료 · 검사 실패";
              log(
                `${repo.name}: 적용은 완료됐지만 상태 확인에 실패했습니다. ${error.message}`,
              );
            }
          }
        }
        if (result.code) failed++;
        render();
      } catch (error) {
        failed++;
        previews.delete(repo.path);
        log(`${repo.name}: ${error.message}`);
        repo.status = "오류";
      }
    }
    message(
      failed
        ? `${chosen.length}개 중 ${failed}개 확인 필요 · 로그를 확인하세요.`
        : action === "check"
          ? `${chosen.length}개 상태 확인 완료 · 변경하려면 2. 변경 미리보기를 실행하세요.`
          : action === "preview"
            ? "미리보기 완료 · 내용을 검토한 뒤 적용을 누르세요."
            : `${chosen.length}개 적용 및 상태 확인 완료`,
    );
    if (failed) {
      $("message").className = "error";
      showLog(true);
    }
  } finally {
    controls(false);
    render();
  }
}
let appliedWorkspace = "";
async function discoverWorkspace() {
  if (busy) return;
  invalidate();
  selected.clear();
  clearAI();
  $("selected").textContent = "0개 선택";
  controls(true);
  message("저장소 탐색 중…");
  try {
    const data = await api("workspace/change", {
      path: $("workspace").value.trim(),
    });
    $("workspace").value = data.workspace;
    appliedWorkspace = data.workspace;
    repositories = data.repositories;
    render();
    message(
      `${repositories.length}개 저장소 발견 · 대상을 선택하면 검사와 미리보기를 준비합니다.`,
    );
    log("저장소 탐색 완료");
  } catch (e) {
    message(e.message);
    log(e.message);
  } finally {
    controls(false);
  }
}
$("discover").onclick = discoverWorkspace;
$("search").oninput = render;
$("filter").onchange = render;
$("select-all").onclick = () => {
  if (busy) return;
  const selectable = visibleRepositories().filter((r) => !r.error);
  const all = selectable.every((r) => selected.has(r.path));
  for (const repo of selectable)
    all ? selected.delete(repo.path) : selected.add(repo.path);
  clearAI();
  $("selected").textContent = `${selected.size}개 선택`;
  schedulePreparation();
};
$("log-toggle").onclick = () => showLog($("log-panel").hidden);
["panel-repos", "panel-settings", "panel-review", "apply"].forEach((target, i) => {
  $(`step-${i + 1}`).onclick = () => {
    const el = $(target);
    // Keep the target below the sticky progress bar, which wraps on narrow screens.
    const offset = document.querySelector(".steps").getBoundingClientRect().bottom + 16;
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - offset, behavior: "smooth" });
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
    if (target === "apply" && !el.disabled) el.focus();
  };
});
for (const id of ["profile", "operation", "visibility", "skills"])
  $(id).onchange = schedulePreparation;
$("refresh").onclick = schedulePreparation;
$("apply").onclick = () => run("apply");
$("log-copy").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("log").textContent);
    message("실행 로그를 복사했습니다.");
  } catch (_) {
    message("로그를 복사하지 못했습니다. 로그를 직접 선택해 복사하세요.");
  }
};
(async () => {
  controls(true);
  try {
    const response = await fetch("/api/session");
    if (!response.ok) throw new Error("서버 연결 실패");
    const data = await response.json();
    session = data.token;
    $("ai-execution").textContent =
      data.ai_execution === "host"
        ? "AI 실행: 호스트 PC의 Codex·Claude (기존 로그인·메모리 사용)"
        : "AI 실행: 웹서버와 같은 환경";
    $("ai-memory-path-hint").textContent =
      data.ai_execution === "host"
        ? "추가 메모리는 호스트 PC의 절대 경로를 입력하세요."
        : "추가 메모리는 AI 실행 환경의 절대 경로를 입력하세요.";
    $("workspace").value = data.workspace;
    controls(false);
    await discoverWorkspace();
    await aiRun("models");
  } catch (e) {
    message(e.message);
  }
})();

function aiSelection() {
  if (selected.size !== 1)
    throw new Error("AI 분석은 저장소 하나를 선택하세요.");
  return {
    path: [...selected][0],
    provider: $("ai-provider").value || "codex",
    model: $("ai-model").value.trim(),
    memories: [
      ...(homeMemoryTarget === [...selected][0] ? homeMemorySelected : []),
      ...$("ai-memories")
        .value.split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
    ],
  };
}
function showProposal(result, path, status) {
  aiTarget = path;
  $("ai-review").hidden = false;
  $("ai-summary").textContent =
    "규칙 제안 준비됨 · 작성 창에서 검토하고 미리보기에 반영하세요.";
  $("ai-files").textContent = result.memory_files.join("\n");
  $("ai-result").textContent =
    result.rules.map((r) => `${r.text}\n근거: ${r.evidence}`).join("\n\n") +
    "\n\n확인할 질문:\n" +
    (result.questions.join("\n") || "없음") +
    "\n\n참고한 메모리:\n" +
    (result.memories_used.join("\n") || "없음");
  $("ai-rules").value = result.rules
    .map((r) => r.text.replace(/\n/g, " "))
    .join("\n");
  $("ai-target").textContent =
    `적용 대상: ${path} · 아래 변경 미리보기에서 교체 내용을 확인하세요.`;
  $("ai-status").textContent = status;
  invalidate();
}
// The host keeps the latest successful proposal per repository, so a GUI
// restart can reload it instead of running the analysis again.
let savedProposal = null;
async function loadSavedProposal() {
  savedProposal = null;
  $("ai-saved").hidden = true;
  $("ai-saved-note").hidden = true;
  if (selected.size !== 1) return;
  const path = [...selected][0];
  let result;
  try {
    result = await api("ai/saved", { path, provider: $("ai-provider").value || "codex" });
  } catch {
    return; // An offline host bridge only hides the saved-proposal option.
  }
  if (!result.saved || !selected.has(path) || selected.size !== 1) return;
  const saved = result.saved;
  savedProposal = { ...saved, path };
  $("ai-saved").hidden = false;
  $("ai-saved-note").hidden = false;
  $("ai-saved-note").textContent =
    `저장된 제안 · ${new Date(saved.saved_at).toLocaleString()} · ` +
    `${saved.provider === "claude" ? "Claude Code" : "Codex"}` +
    (saved.model ? ` · ${saved.model}` : "") +
    (saved.stale ? " · 저장 이후 커밋이 바뀌었습니다. 현재 코드와 대조하세요." : "");
}
async function aiRun(action) {
  if (busy || preparing) return;
  controls(true);
  $("ai-status").textContent =
    action === "analyze"
      ? "AI 분석 중… 최대 5분이 걸릴 수 있습니다."
      : "확인 중…";
  try {
    const data = ["connection", "models"].includes(action)
      ? { provider: $("ai-provider").value || "codex" }
      : aiSelection();
    const result = await api(`ai/${action}`, data);
    if (action === "models") {
      const previous = $("ai-model").value;
      $("ai-model").replaceChildren();
      for (const item of [
        { model: "", name: "CLI 기본 모델" },
        ...result.models,
      ]) {
        const option = document.createElement("option");
        option.value = item.model;
        option.textContent = item.name;
        $("ai-model").append(option);
      }
      $("ai-model").value = result.models.some((m) => m.model === previous)
        ? previous
        : "";
      $("ai-model-note").textContent =
        result.message || "Codex에서 조회한 모델 목록입니다.";
      $("ai-status").textContent =
        result.message || `${result.models.length}개 모델 조회 완료`;
    } else if (action === "memories") {
      homeMemoryTarget = data.path;
      homeMemorySelected.clear();
      $("ai-home-files").replaceChildren();
      $("ai-home-roots").textContent = result.roots.join(" · ");
      for (const item of result.files) {
        const label = document.createElement("label"),
          box = document.createElement("input");
        box.type = "checkbox";
        box.checked = item.recommended;
        if (box.checked) homeMemorySelected.add(item.path);
        box.onchange = () =>
          box.checked
            ? homeMemorySelected.add(item.path)
            : homeMemorySelected.delete(item.path);
        label.append(box, document.createTextNode(item.name));
        label.title = item.path;
        $("ai-home-files").append(label);
      }
      $("ai-status").textContent =
        `${result.files.length}개 메모리 발견 · 프로젝트명이 맞는 파일만 우선 선택했습니다.`;
    } else if (action === "connection") {
      $("ai-status").textContent = `${result.message} ${result.path || ""}`;
    } else if (action === "context") {
      $("ai-files").textContent =
        result.files.join("\n") || "자동 발견된 프로젝트 메모리 없음";
      $("ai-status").textContent =
        "참조 목록 확인 완료 · 추가 경로를 바꾸면 다시 확인하세요.";
    } else {
      showProposal(
        result,
        data.path,
        "제안 완료 · 근거와 질문을 확인하고 규칙을 편집하세요. 아직 파일은 변경되지 않았습니다." +
          (result.saved === false ? " 결과를 호스트에 저장하지 못했습니다." : ""),
      );
    }
  } catch (error) {
    $("ai-status").textContent = error.message;
  } finally {
    controls(false);
  }
}
$("ai-provider").onchange = async () => {
  if (busy) return;
  invalidate();
  clearAI();
  $("ai-model-note").textContent = "";
  $("ai-model").replaceChildren();
  const option = document.createElement("option");
  option.value = "";
  option.textContent = "CLI 기본 모델";
  $("ai-model").append(option);
  $("ai-model").value = "";
  await aiRun("models");
  if (selected.size === 1) await aiRun("memories");
};
$("ai-connect").onclick = () => aiRun("connection");
$("ai-context").onclick = () => aiRun("context");
$("ai-analyze").onclick = async () => {
  await aiRun("analyze");
  await loadSavedProposal();
};
$("ai-saved").onclick = () => {
  if (busy || !savedProposal || !selected.has(savedProposal.path)) return;
  showProposal(
    savedProposal.proposal,
    savedProposal.path,
    "저장된 제안을 불러왔습니다 · 근거와 질문을 다시 확인하세요. 아직 파일은 변경되지 않았습니다.",
  );
};
$("ai-rules").oninput = invalidate;

$("ai-models").onclick = () => aiRun("models");
$("ai-home").onclick = () => aiRun("memories");

$("ai-open").onclick = async () => {
  if (busy || preparing || selected.size !== 1) return;
  $("ai-project").textContent = [...selected][0];
  $("ai-dialog").showModal();
  if (homeMemoryTarget !== [...selected][0]) await aiRun("memories");
  await loadSavedProposal();
};
$("ai-close").onclick = () => $("ai-dialog").close();
$("ai-preview").onclick = async () => {
  if (busy || !aiTarget || !selected.has(aiTarget)) return;
  $("ai-dialog").close();
  schedulePreparation();
};

let folderInfo = null;
async function browseFolder(path) {
  $("folder-status").textContent = "폴더 확인 중…";
  $("folder-select").disabled = true;
  $("folder-parent").disabled = true;
  $("folder-home").disabled = true;
  $("folder-list").replaceChildren();
  folderInfo = null;
  try {
    folderInfo = await api("workspace/browse", { path });
    $("folder-path").textContent = folderInfo.path;
    for (const directory of folderInfo.directories) {
      if (directory.name.startsWith(".") && !$("folder-hidden").checked)
        continue;
      const button = document.createElement("button");
      button.textContent = `${directory.name} · ${directory.is_repository ? "Git 저장소" : "일반 폴더 (탐색용)"}`;
      button.onclick = () => browseFolder(directory.path);
      $("folder-list").append(button);
    }
    $("folder-status").textContent = folderInfo.repository_count
      ? `선택 가능한 Git 저장소 ${folderInfo.repository_count}개 · 이 위치 또는 하위 3단계`
      : "선택 가능한 Git 저장소가 없습니다. 다른 폴더로 이동하세요. (하위 탐색 깊이 3)";
    $("folder-select").disabled = !folderInfo.repository_count;
    $("folder-parent").disabled = folderInfo.parent === folderInfo.path;
    $("folder-home").disabled = false;
  } catch (error) {
    $("folder-status").textContent = error.message;
  }
}
$("workspace-browse").onclick = () => {
  if (busy) return;
  $("workspace-dialog").showModal();
  browseFolder($("workspace").value.trim());
};
$("folder-hidden").onchange = () =>
  folderInfo && browseFolder(folderInfo.path);
$("workspace-close").onclick = () => $("workspace-dialog").close();
$("folder-parent").onclick = () =>
  folderInfo && browseFolder(folderInfo.parent);
$("folder-home").onclick = () => folderInfo && browseFolder(folderInfo.home);
$("folder-select").onclick = async () => {
  if (!folderInfo || !folderInfo.repository_count || busy) return;
  $("workspace").value = folderInfo.path;
  $("workspace").oninput();
  $("workspace-dialog").close();
  await discoverWorkspace();
};

let suggestionTimer = null;
let suggestionVersion = 0;
async function suggestWorkspace() {
  const version = ++suggestionVersion;
  const value = $("workspace").value;
  try {
    const result = await api("workspace/suggest", { path: value });
    if (version !== suggestionVersion || value !== $("workspace").value) return;
    $("workspace-suggestions").replaceChildren();
    for (const path of result.paths) {
      const option = document.createElement("option");
      option.value = path;
      $("workspace-suggestions").append(option);
    }
  } catch (_) {
    // Suggestions are optional: manual input remains available during a busy server.
  }
}
let workspaceActionPointer = false;
for (const id of ["workspace-browse", "discover"])
  $(id).onpointerdown = () => {
    workspaceActionPointer = true;
  };
$("workspace").onfocus = () => {
  workspaceActionPointer = false;
  return suggestWorkspace();
};
$("workspace").oninput = () => {
  clearTimeout(suggestionTimer);
  suggestionVersion++;
  $("workspace-suggestions").replaceChildren();
  repositories = [];
  suggestionTimer = setTimeout(suggestWorkspace, 250);
  invalidate();
  selected.clear();
  clearAI();
  $("selected").textContent = "0개 선택";
  render();
  message(
    "경로 입력 후 Enter를 누르거나 입력창을 벗어나면 자동으로 탐색합니다.",
  );
};

$("workspace").onkeydown = async (event) => {
  if (event.key !== "Enter" || event.isComposing) return;
  event.preventDefault();
  await discoverWorkspace();
};
$("workspace").onblur = async (event) => {
  const openingPicker =
    workspaceActionPointer &&
    ["workspace-browse", "discover"].includes(event.relatedTarget?.id);
  workspaceActionPointer = false;
  if (openingPicker) return;
  if (
    busy ||
    !$("workspace").value.trim() ||
    $("workspace").value.trim() === appliedWorkspace
  )
    return;
  await discoverWorkspace();
};
