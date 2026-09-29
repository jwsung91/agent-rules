"use strict";
const $ = (id) => document.getElementById(id);
let session = "",
  repositories = [],
  selected = new Set(),
  previews = new Map(),
  busy = false;
function log(text) {
  $("log").textContent += `\n[${new Date().toLocaleTimeString()}] ${text}\n`;
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
    .querySelectorAll("button,select,input:not([readonly])")
    .forEach((e) => (e.disabled = value));
  $("apply").disabled =
    value ||
    !selected.size ||
    [...selected].some((p) => !previews.get(p)?.token);
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
    box.onchange = () => {
      box.checked ? selected.add(repo.path) : selected.delete(repo.path);
      invalidate();
      $("selected").textContent = `${selected.size}개 선택`;
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
          if (!result.code) repo.profile = options(repo).profile;
        }
        if (result.code) failed++;
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
        : `${chosen.length}개 처리 완료`,
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
  $("selected").textContent = "0개 선택";
  controls(true);
  message("저장소 탐색 중…");
  try {
    const data = await api("discover", {});
    repositories = data.repositories;
    render();
    message(`${repositories.length}개 저장소 발견`);
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
  } catch (e) {
    message(e.message);
  }
})();
