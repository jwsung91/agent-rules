// Run with: node --test tests/gui_frontend.test.cjs
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function element() {
  return {
    value: "",
    textContent: "",
    checked: true,
    disabled: false,
    append() {},
    replaceChildren() {},
    setAttribute() {},
  };
}

async function app(checkResult, applyCode = 0) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  get("profile").value = "auto";
  get("operation").value = "auto";
  get("visibility").value = "local";
  const calls = [];
  const context = vm.createContext({
    setTimeout: () => 0,
    clearTimeout: () => {},
    document: {
      getElementById: get,
      querySelectorAll: () => [],
      createElement: element,
    },
    fetch: async (url, request) => {
      if (url === "/api/session")
        return {
          ok: true,
          json: async () => ({ token: "session", workspace: "/work" }),
        };
      if (url === "/api/ai/models")
        return { ok: true, json: async () => ({ models: [] }) };
      calls.push([url, JSON.parse(request.body)]);
      if (url === "/api/check" && checkResult instanceof Error)
        throw checkResult;
      const result =
        url === "/api/apply" ? { code: applyCode, log: "apply" } : checkResult;
      return { ok: true, json: async () => result };
    },
  });
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../scripts/agent_rules/web/app.js"),
      "utf8",
    ),
    context,
  );
  await new Promise(setImmediate);
  vm.runInContext(
    `repositories = [{ path: "/work/demo", name: "demo", profile: null, status: "미설치" }]; selected.add("/work/demo"); previews.set("/work/demo", { token: "preview" });`,
    context,
  );
  await vm.runInContext('run("apply")', context);
  return {
    context,
    calls,
    get,
    status: vm.runInContext("repositories[0].status", context),
  };
}

test("successful apply checks the installed profile and updates status", async () => {
  const result = await app({ code: 0, status: "정상", log: "healthy" });
  assert.deepEqual(
    result.calls.map(([url]) => url),
    ["/api/apply", "/api/check"],
  );
  assert.equal(result.calls[1][1].profile, "codex");
  assert.equal(result.status, "정상");
  assert.equal(result.get("apply").disabled, true);
  assert.match(result.get("message").textContent, /적용 및 상태 확인 완료/);
});

test("post-apply warnings remain visible", async () => {
  const result = await app({ code: 2, status: "경고", log: "warning" });
  assert.equal(result.status, "경고");
  assert.match(result.get("message").textContent, /확인 필요/);
});

test("check network failure does not report a failed apply", async () => {
  const result = await app(new Error("offline"));
  assert.equal(result.status, "적용 완료 · 검사 실패");
  assert.equal(result.get("apply").disabled, true);
  assert.match(result.get("log").textContent, /offline/);
});

test("failed apply is not followed by a health check", async () => {
  const result = await app(null, 1);
  assert.equal(result.calls.length, 1);
  assert.equal(result.status, "적용 오류");
});

test("AI proposal stays editable and only enters the reviewed preview", async () => {
  const ui = await app({ code: 0, status: "정상", log: "healthy" });
  const requests = [];
  ui.context.fetch = async (url, request) => {
    requests.push([url, JSON.parse(request.body)]);
    const result =
      url === "/api/ai/analyze"
        ? {
            rules: [{ text: "Preserve the API.", evidence: "README.md" }],
            questions: [],
            memories_used: [],
            memory_files: [],
          }
        : { code: 0, files: [], token: "reviewed", log: "preview" };
    return { ok: true, json: async () => result };
  };
  await vm.runInContext('aiRun("analyze")', ui.context);
  assert.equal(ui.get("ai-rules").value, "Preserve the API.");
  assert.equal(ui.get("apply").disabled, true);
  ui.get("ai-rules").value = "Preserve the reviewed API.";
  await vm.runInContext('run("preview")', ui.context);
  assert.deepEqual(
    requests.map(([url]) => url),
    ["/api/ai/analyze", "/api/preview"],
  );
  assert.deepEqual(requests[1][1].boundaries, ["Preserve the reviewed API."]);
  assert.equal(ui.get("apply").disabled, false);
  vm.runInContext("clearAI(); invalidate()", ui.context);
  assert.equal(ui.get("ai-rules").value, "");
  assert.equal(ui.get("apply").disabled, true);
});

test("editing workspace invalidates selections and reviewed changes", async () => {
  const ui = await app({ code: 0, status: "정상", log: "healthy" });
  vm.runInContext(
    'previews.set("/work/demo", {token: "old"}); aiTarget = "/work/demo";',
    ui.context,
  );
  ui.get("workspace").value = "/new/workspace";
  ui.get("workspace").oninput();
  assert.equal(vm.runInContext("selected.size", ui.context), 0);
  assert.equal(vm.runInContext("previews.size", ui.context), 0);
  assert.equal(vm.runInContext("aiTarget", ui.context), null);
  assert.equal(ui.get("apply").disabled, true);
});

test("changing AI provider resets model, proposal and previews", async () => {
  const ui = await app({ code: 0, status: "정상", log: "healthy" });
  const requests = [];
  ui.context.fetch = async (url, request) => {
    requests.push([url, JSON.parse(request.body)]);
    return {
      ok: true,
      json: async () =>
        url.endsWith("models")
          ? {
              models: [{ model: "sonnet", name: "Sonnet" }],
              message: "aliases",
            }
          : { roots: [], files: [] },
    };
  };
  vm.runInContext(
    'aiTarget = "/work/demo"; previews.set("/work/demo", {token: "old"})',
    ui.context,
  );
  ui.get("ai-rules").value = "old proposal";
  ui.get("ai-model").value = "codex-model";
  ui.get("ai-provider").value = "claude";
  await ui.get("ai-provider").onchange();
  assert.equal(ui.get("ai-model").value, "");
  assert.equal(ui.get("ai-rules").value, "");
  assert.equal(ui.get("apply").disabled, true);
  assert.equal(vm.runInContext("aiTarget", ui.context), null);
  assert.ok(requests.every(([, body]) => body.provider === "claude"));
});

async function workspaceUI() {
  const ui = await app({ code: 0, status: "정상", log: "healthy" });
  const changes = [];
  ui.context.fetch = async (url, request) => {
    const data = JSON.parse(request.body);
    if (url === "/api/workspace/change") changes.push(data.path);
    return {
      ok: true,
      json: async () => ({ workspace: data.path, repositories: [] }),
    };
  };
  ui.get("workspace-dialog").close = () => {};
  return { ...ui, changes };
}

test("Enter and leaving edited workspace automatically discover once", async () => {
  const ui = await workspaceUI();
  ui.get("workspace").value = "/new";
  let prevented = false;
  await ui.get("workspace").onkeydown({
    key: "Enter",
    preventDefault: () => {
      prevented = true;
    },
  });
  await ui.get("workspace").onblur({ relatedTarget: null });
  assert.ok(prevented);
  assert.deepEqual(ui.changes, ["/new"]);
  ui.get("workspace").value = "/next";
  await ui
    .get("workspace")
    .onblur({ relatedTarget: { id: "workspace-browse" } });
  assert.deepEqual(ui.changes, ["/new", "/next"]);
});

test("folder picker confirmation immediately discovers only eligible locations", async () => {
  const ui = await workspaceUI();
  vm.runInContext(
    'folderInfo = {path: "/plain", repository_count: 0}',
    ui.context,
  );
  await ui.get("folder-select").onclick();
  assert.equal(ui.changes.length, 0);
  vm.runInContext(
    'folderInfo = {path: "/repos", repository_count: 2}',
    ui.context,
  );
  await ui.get("folder-select").onclick();
  assert.deepEqual(ui.changes, ["/repos"]);
});

test("opening folder picker and IME composition do not prematurely apply text", async () => {
  const ui = await workspaceUI();
  ui.get("workspace").value = "/typing";
  ui.get("workspace-browse").onpointerdown();
  await ui
    .get("workspace")
    .onblur({ relatedTarget: { id: "workspace-browse" } });
  await ui.get("workspace").onkeydown({ key: "Enter", isComposing: true });
  assert.equal(ui.changes.length, 0);
});
