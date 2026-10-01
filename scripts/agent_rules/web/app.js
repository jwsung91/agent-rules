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
function clearAI() {
  $("ai-review").hidden = true;
  $("ai-summary").textContent =
    "선택 사항 · AI와 함께 프로젝트에 맞는 규칙을 작성하세요.";
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
function invalidate() {
  previews.clear();
  $("apply").disabled = true;
  $("preview").replaceChildren();
}
function message(text) {
  $("message").textContent = text;
}
function controls(value) {
  busy = value;
  document
    .querySelectorAll("button,select,textarea,input:not([readonly])")
    .forEach((e) => (e.disabled = value));
  $("apply").disabled =
    value ||
    !selected.size ||
    [...selected].some((p) => !previews.get(p)?.token);
  $("ai-close").disabled = false;
  $("ai-preview").disabled = value || !aiTarget || !selected.has(aiTarget);
  render();
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
  $("ai-open").disabled = busy || selected.size !== 1;
  $("repositories").replaceChildren();
  const filter = $("search").value.toLowerCase();
  for (const repo of repositories.filter((r) =>
    r.name.toLowerCase().includes(filter),
  )) {
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
      invalidate();
      $("selected").textContent = `${selected.size}개 선택`;
      if (selected.size === 1) await aiRun("memories");
    };
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = repo.name;
    const sub = document.createElement("small");
    sub.textContent = `${repo.profile || "신규"} · ${repo.path}`;
    name.append(sub);
    const state = document.createElement("span");
    state.className = "state";
    state.textContent = repo.error ? "오류" : repo.status;
    row.append(box, name, state);
    $("repositories").append(row);
  }
  $("empty").hidden = repositories.length > 0;
  $("count").textContent = `${repositories.length}개`;
}
function showPreview(repo, data) {
  const heading = document.createElement("h3");
  heading.textContent = `${repo.name} · ${data.files.length}개 변경${data.code ? " · 적용 불가" : ""}`;
  $("preview").append(heading);
  for (const file of data.files) {
    const details = document.createElement("details"),
      summary = document.createElement("summary"),
      pre = document.createElement("pre");
    summary.textContent = `${file.action} · ${file.path}`;
    for (const line of file.diff.split("\n")) {
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
    $("preview").append(details);
  }
}
async function run(action) {
  if (busy) return;
  const chosen = repositories.filter((r) => selected.has(r.path));
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
        if (action === "check") repo.status = result.status;
        if (action === "apply") {
          previews.delete(repo.path);
          repo.status = result.code ? "적용 오류" : "적용 완료 · 재검사 필요";
          if (!result.code) {
            repo.profile = options(repo).profile;
            repo.status = "적용 완료 · 검사 중…";
            render();
            message(`${repo.name} · 적용 후 상태 확인 중…`);
            try {
              const checked = await api("check", options(repo));
              repo.status = checked.status;
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
            ? "미리보기 완료 · 내용을 검토한 뒤 3. 선택한 변경 적용을 누르세요."
            : `${chosen.length}개 적용 및 상태 확인 완료`,
    );
  } finally {
    controls(false);
    render();
  }
}
$("discover").onclick = async () => {
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
    repositories = data.repositories;
    render();
    message(
      `${repositories.length}개 저장소 발견 · 대상을 선택하고 1. 상태 확인을 누르세요.`,
    );
    log("저장소 탐색 완료");
  } catch (e) {
    message(e.message);
    log(e.message);
  } finally {
    controls(false);
  }
};
$("search").oninput = render;
for (const id of ["profile", "operation", "visibility", "skills"])
  $(id).onchange = () => {
    invalidate();
    message("설정 변경됨 · 미리보기를 다시 실행하세요.");
  };
$("check").onclick = () => run("check");
$("preview-button").onclick = () => run("preview");
$("apply").onclick = () => run("apply");
(async () => {
  controls(true);
  try {
    const response = await fetch("/api/session");
    if (!response.ok) throw new Error("서버 연결 실패");
    const data = await response.json();
    session = data.token;
    $("workspace").value = data.workspace;
    controls(false);
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
async function aiRun(action) {
  if (busy) return;
  controls(true);
  $("ai-status").textContent =
    action === "analyze"
      ? "Codex 분석 중… 최대 5분이 걸릴 수 있습니다."
      : "확인 중…";
  try {
    const data = ["connection", "models"].includes(action) ? {} : aiSelection();
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
      $("ai-status").textContent = `${result.models.length}개 모델 조회 완료`;
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
      aiTarget = data.path;
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
        `적용 대상: ${data.path} · 아래 변경 미리보기에서 교체 내용을 확인하세요.`;
      $("ai-status").textContent =
        "제안 완료 · 근거와 질문을 확인하고 규칙을 편집하세요. 아직 파일은 변경되지 않았습니다.";
      invalidate();
    }
  } catch (error) {
    $("ai-status").textContent = error.message;
  } finally {
    controls(false);
  }
}
$("ai-connect").onclick = () => aiRun("connection");
$("ai-context").onclick = () => aiRun("context");
$("ai-analyze").onclick = () => aiRun("analyze");
$("ai-rules").oninput = invalidate;

$("ai-models").onclick = () => aiRun("models");
$("ai-home").onclick = () => aiRun("memories");

$("ai-open").onclick = () => {
  if (busy || selected.size !== 1) return;
  $("ai-project").textContent = [...selected][0];
  $("ai-dialog").showModal();
};
$("ai-close").onclick = () => $("ai-dialog").close();
$("ai-preview").onclick = async () => {
  if (busy || !aiTarget || !selected.has(aiTarget)) return;
  $("ai-dialog").close();
  await run("preview");
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
      const button = document.createElement("button");
      button.textContent = directory.name;
      button.onclick = () => browseFolder(directory.path);
      $("folder-list").append(button);
    }
    $("folder-status").textContent = folderInfo.directories.length
      ? ""
      : "하위 폴더가 없습니다.";
    $("folder-select").disabled = false;
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
$("workspace-close").onclick = () => $("workspace-dialog").close();
$("folder-parent").onclick = () =>
  folderInfo && browseFolder(folderInfo.parent);
$("folder-home").onclick = () => folderInfo && browseFolder(folderInfo.home);
$("folder-select").onclick = () => {
  if (!folderInfo) return;
  $("workspace").value = folderInfo.path;
  $("workspace").oninput();
  $("workspace-dialog").close();
  message("폴더 선택됨 · 경로 적용·탐색을 눌러 변경하세요.");
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
$("workspace").onfocus = suggestWorkspace;
$("workspace").oninput = () => {
  clearTimeout(suggestionTimer);
  suggestionVersion++;
  $("workspace-suggestions").replaceChildren();
  suggestionTimer = setTimeout(suggestWorkspace, 250);
  invalidate();
  selected.clear();
  clearAI();
  $("selected").textContent = "0개 선택";
  render();
  message("입력한 경로는 아직 적용되지 않았습니다. 경로 적용·탐색을 누르세요.");
};
