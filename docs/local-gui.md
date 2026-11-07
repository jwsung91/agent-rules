# Local Deployment GUI

The GUI runs directly as a Python process. It uses the existing deployment
planner, checks, and writer; no Docker, database, or frontend build is needed.
AI proposals additionally need the chosen CLI. Optional [Docker packaging](docker-gui.md)
runs only the GUI; a host bridge invokes your existing AI CLIs. Dependencies are separate from the standard-library CLI.

## Linux and WSL

Run from the agent-rules checkout with Python 3.10+ and Git installed. The
launch script creates `~/.venvs/agent-rules` if needed, installs
`requirements-gui.txt` on every run so dependency updates are picked up, and
starts the GUI. The workspace defaults to the folder that contains this
checkout; options after it are passed to `scripts/gui.py`.
`AGENT_RULES_VENV` overrides the venv path. `./start.sh --local` from the
checkout root does the same.

```bash
scripts/local/start.sh [/path/to/workspace] [--port 8766] [--open-browser]
```

`scripts/gui.py` itself also defaults `--workspace` to `AGENT_RULES_WORKSPACE`
or the folder containing the checkout, and reads `AGENT_RULES_PORT`,
`AGENT_RULES_SHARED_URL`, `AGENT_RULES_SOURCE_REF`, and `AGENT_RULES_MAX_DEPTH`
as defaults for the matching options. Source status (local and remote heads) is
refreshed at most every 30 seconds, so pulling the checkout while the GUI runs
is picked up without a restart; template changes still apply to new previews only.

The equivalent manual steps:

```bash
python3 -m venv ~/.venvs/agent-rules
~/.venvs/agent-rules/bin/python -m pip install -r requirements-gui.txt
~/.venvs/agent-rules/bin/python scripts/gui.py --workspace /path/to/workspace
```

If venv creation is unavailable, install your distribution's Python venv
package first. Visit `http://127.0.0.1:8765` from the same machine. WSL users can
open that URL in a Windows browser when localhost forwarding is available.
`--open-browser` optionally uses the server environment's browser handler; WSL
users can open the URL manually if that environment has no browser handler.
Use `--port 8766` when the default port is occupied. Stop with Ctrl+C.

## Native Windows

Run in PowerShell from the checkout:

```powershell
py -3 -m venv "$env:LOCALAPPDATA\agent-rules-venv"
& "$env:LOCALAPPDATA\agent-rules-venv\Scripts\python.exe" -m pip install -r requirements-gui.txt
& "$env:LOCALAPPDATA\agent-rules-venv\Scripts\python.exe" scripts/gui.py --workspace C:\workspace --open-browser
```

Use a Linux path when the server runs in WSL, and a Windows path when running
native Windows Python. The server accesses its own filesystem, not the browser
computer's filesystem.

## Headless Linux

Keep the server bound to loopback and forward its port over SSH:

```bash
ssh -L 8765:127.0.0.1:8765 user@linux-host
```

Start the server on the Linux host, then open the local forwarded URL in your
browser. Use the same local and remote port so origin checks match. The GUI is
for one trusted local user, not a public or multi-user service.

## Workflow

1. Start with an explicit `--workspace` as the initial folder. Change it by
   typing an absolute server path (or `~`) and pressing Enter or leaving the
   input, or by confirming **이 위치로 탐색** in the **찾아보기** dialog. Discovery
   runs automatically; **다시 탐색** (↻) refreshes the current location. General
   folders remain navigable, but only a Git repository or a parent containing
   selectable repositories within depth three can be confirmed. The picker
   labels Git roots and navigation folders and hides `.git` internals. Valid
   `.git` files (worktrees/separate Git directories) are supported; a fake
   `.git` marker and ordinary source subdirectories cannot be selected. While typing, native browser autocomplete suggests up to
   30 matching server directories; a trailing slash lists child folders.
   Suggestions never change the active workspace. The picker browses server directories, not the browser
   computer; WSL uses Linux paths. Switching clears selected repositories, AI
   drafts and all server preview tokens, including previews from other tabs.
   Other tabs should refresh after a switch. Invalid paths keep the active
   server workspace unchanged. The local user can select directories outside
   the initial folder; it is no longer a fixed server-lifetime boundary.
   Discovery searches to depth three,
   stops at Git repositories, skips symlink directories, and excludes the
   agent-rules source checkout. No repository is selected automatically.
2. Select intended repositories. The search field and the status filter
   (**전체**, **확인 필요**, **미설치**) narrow the list; selections persist when
   filtered, and the selected count includes hidden selections. **전체 선택**
   toggles only the visible repositories without discovery errors.
3. Choose an agent, operation, visibility, and whether to install shared skills.
   Automatic mode uses recorded profiles and syncs existing adoptions; new
   repositories default to Codex installation. Visibility is explicitly selected
   and defaults to local; choose tracked for shared installations.
4. Selecting repositories or changing deployment settings automatically runs
   health checks and prepares the file diff after a short debounce.
5. Review the preview, including baselines and `.gitignore` changes. Stale
   responses are discarded when the selection or settings change.
6. **적용** shows the changed repository and file counts and is enabled
   only when every selected repository has a valid preview and changes exist.
   Unchanged repositories are skipped. Applying automatically runs another
   health check. Use **다시 검사** to retry checks or refresh external changes.
   Warnings and failures remain visible in the status and execution log.

A preview expires after 15 minutes and can be applied once. Changing the UI
selection or options discards its preview. The server also rejects a preview
when managed target files, source content, Git index, or Git configuration
change. Refresh after restarting the server. Do not concurrently edit affected
files or run another deployment process while applying; this is not a filesystem
transaction or a lock against external programs.

Operations are serialized within this server, and each batch is processed
sequentially. A failure does not roll back successful repositories. A disk or
permission error during writing can leave partial changes; inspect the log and
run a fresh health check. Closing the tab does not reliably cancel a request
already executing on the server. Logs and preview tokens live only in memory.

## Scope and local access

The first version supports discovery, checks, installation, sync, and diffs.
Use the CLI for removal, force overwrite, local rule copies, custom boundary or
validation arguments, and persistent batch lists. Existing local settings are
preserved by the same merge engine as the CLI. Suggested validation commands are
not executed by the GUI. The GUI does not commit, push, or need signing keys.

Direct execution binds to `127.0.0.1`, validates Host and Origin, requires a
session token for API operations, and serves no external scripts. Do not expose
it through a public proxy. Paths must stay within the currently selected workspace; the GUI
refuses symlinks in managed output paths. This is not protection against other
processes running as the same OS user.

## Implementation and validation

- `scripts/gui.py`, `scripts/ai_bridge.py`: stable command entrypoints.
- `scripts/agent_rules/gui/launch.py`: direct-execution launcher and optional browser opening.
- `scripts/agent_rules/gui/web.py`: loopback HTTP API and static asset routes.
- `scripts/agent_rules/gui/service.py`: structured previews and approval state,
  delegating to existing planning, applying, checking, and discovery modules.
- `scripts/agent_rules/gui/ai.py`: local AI CLI calls and memory inspection.
- `scripts/agent_rules/gui/bridge.py`, `host_bridge.py`: server-side job exchange
  and host-side polling, respectively.
- `scripts/agent_rules/gui/assets/`: plain HTML, CSS, and JavaScript.
- `tests/test_gui.py`: temporary-repository workflows, stale previews, access
  restrictions, conflicting files, and failure reporting.

Install `requirements-dev.txt` to run the full suite including GUI tests.
See [repository architecture](architecture.md) for dependency boundaries.

## Codex and Claude Code rule proposals

Select one repository and open **AI로 작성**. The dialog initially shows
the analysis tool (Codex or Claude Code), model, and proposal action. Connection and memory controls are in a collapsed
settings section; the editable rules and evidence appear after a proposal.
Use **변경 검토로** to return to the deployment preview. Closing the dialog
keeps its draft, but changing the repository selection or analysis tool clears it.
The analysis tool is independent of the deployment profile: either tool can
propose rules for Codex, Claude, or a combined installation. Closing a
running analysis does not cancel it.
The server invokes the selected local CLI using its saved authentication.
Codex uses `--sandbox read-only` and no interactive approvals. Claude Code uses
`--restricted --safe-mode --strict-mcp-config`, only `Read,Glob,Grep`, and
`--permission-mode dontAsk`. Custom hooks, MCP, plugins and automatic instruction
loading are disabled for Claude; selected memory contents are supplied explicitly.
Its account/environment default model applies when no model is selected; user
settings files are ignored in this restricted run. Sessions are not persisted.
The Claude integration requires a CLI supporting these flags (tested 2.1.286). Analysis can take up to
five minutes; other GUI operations wait until it completes. The selected
repository and supplied memory context are processed by the CLI's configured
AI service and consume its usage allowance. Closing the tab does not cancel it.

Install and log in to the chosen CLI in the server's environment (Linux CLI for WSL).
Set `--codex /absolute/path/to/codex` or `AGENT_RULES_CODEX` to choose the
executable. Use `--claude /absolute/path/to/claude` or `AGENT_RULES_CLAUDE`
for Claude Code. The Codex model dropdown queries the official Codex app-server `model/list` interface
and retains a CLI-default option. The list is refreshed on page load and can
be refreshed manually. Claude offers the documented `sonnet`, `opus`, and `haiku`
aliases; this is explicitly labeled as an alias list, not a live account model
catalog. Availability depends on the account and organization. See the official
[Claude CLI reference](https://code.claude.com/docs/en/cli-reference) and
[model configuration](https://code.claude.com/docs/en/model-config).
The GUI never asks for or stores an API key.

Project AGENTS.md, CLAUDE.md, MEMORY.md, `.codex/memories/*.md`,
`.claude/memory/*.md`, and the matching Claude project auto-memory directory
are candidates. Additional Markdown absolute paths can be supplied explicitly
for relevant Codex or Claude memories outside the repository. The home-memory picker automatically scans `$CODEX_HOME/memories` (default
`~/.codex/memories`) and `$CLAUDE_CONFIG_DIR/projects/<project-key>/memory`
(default `~/.claude/projects/<project-key>/memory`) when one
repository is selected. It preselects Codex filenames matching the repository
name and Claude project matches; other home files remain optional. This filename
heuristic is not proof of relevance: review the selected files before analysis.
Global Codex conversation history is not automatically collected. Missing project memory is normal.
In direct mode paths resolve on the server; Windows memories require WSL-accessible
paths when the server runs in WSL. In Docker mode the host bridge resolves memory
paths on the host PC; see [Docker setup](docker-gui.md). The list is limited to 40 files and 200KB total.
Memory is historical evidence, not authority: proposals must compare it with
current code and identify unresolved questions and supporting files.

Review the proposal and edit the complete list of project boundaries (one per
line). Existing boundaries should be retained when still valid. A nonempty
list replaces that local section through the existing preview/apply workflow;
a blank list preserves existing rules. AI output is never applied automatically.
The preview expires and rejects intervening managed-file changes as usual.

The latest successful proposal for each repository is saved where the AI runs
(the host bridge in Docker mode), under `$XDG_CACHE_HOME/agent-rules/ai-proposals/`
(default `~/.cache/agent-rules/ai-proposals/`; override with
`AGENT_RULES_PROPOSAL_DIR`). The record is written to a temporary file in the
same directory and then replaces the previous one, so an interrupted write keeps
the last complete proposal. Files are owner-only because proposals can quote
memory contents; target repositories are not modified. After a GUI or container
restart, **AI로 작성** shows **저장된 제안 불러오기** with the save time, tool,
and model. If the repository HEAD has moved since the analysis, the note says so;
loading still requires review and the normal preview/apply workflow.

Frontend regression tests: `node --test tests/gui_frontend.test.cjs`.

저장소 목록에는 설치된 에이전트만 표시합니다. 규칙 파일이 있으면 이름(예: `Claude`)을, agent-rules 메타데이터가 없으면 `Codex (사용자 규칙)`처럼 상태를 함께 표시하며, 경로는 행에 마우스를 올리면 보입니다. `사용자 규칙`은 agent-rules 메타데이터가 없는 파일이며, 설치 표시는 공유 스킬의 정상 여부를 보증하지 않습니다. 상태 확인과 적용 후 검사에서 표시를 갱신합니다. 에이전트 설정의 `기존 유지`는 기존 프로필을 사용하며, 신규 저장소에는 Codex를 선택합니다.

저장소 선택 또는 배포 설정 변경 시 350ms 동안 연속 입력을 모은 뒤 상태 검사와 변경 미리보기를 순서대로 실행합니다. 설정 변경 전 응답은 폐기하며, 충돌·실패·변경 없음 상태에서는 적용을 막습니다. 실제 파일 변경은 변경 저장소·파일 수가 표시된 적용 버튼으로만 실행합니다. `다시 검사`로 외부 변경도 재검사할 수 있습니다. 상태 색상은 초록(정상·설치), 회색(미설치), 파랑(진행·사용자 규칙), 주황(경고), 빨강(실패)이며 문구를 함께 제공합니다. AI 분석은 자동 실행하지 않습니다.

화면 상단의 진행 표시줄(①저장소 ②설정 ③검토 ④적용)은 화면을 나누지 않고 각 영역의 상태만 요약합니다. 단계를 누르면 해당 영역으로 이동해 잠시 강조하며, ④는 적용 버튼에 포커스를 둡니다. ③은 준비 중·파일 수·변경 없음을 표시하고, 적용할 수 없는 저장소가 있으면 빨간 `!`로 바뀝니다. 이때 하단 상태 메시지에 원인 저장소 이름을 표시하고 실행 로그를 자동으로 펼칩니다. 실행 로그는 평소 접혀 있으며 하단 바의 **로그**로 열고 닫습니다. Gemini 프로필에는 공유 스킬 경로가 없어 스킬 스위치가 비활성화됩니다.

## Source and discovery settings

Use launch options to select the source repository URL, source branch, and
repository discovery depth. Defaults remain the shared agent-rules URL, `main`,
and depth `3` (the workspace root is depth zero). Depth must be positive.

```bash
python scripts/gui.py --workspace /path/to/workspace \
  --shared-url https://github.com/your-org/agent-rules \
  --source-ref stable --max-depth 5
```

Source options control generated links, metadata, and version checks. Files are
always generated from the current agent-rules checkout; these options do not
clone or switch branches. Use a checkout matching the selected source.
The adoption CLI also accepts `--source-ref` alongside `--shared-url` for
install, sync, and check operations, including batch operations; see
[Source repository and branch](scripted-adoption.md#source-repository-and-branch).
Unlike the CLI, the GUI always uses its launch settings rather than the source
recorded in each repository.
