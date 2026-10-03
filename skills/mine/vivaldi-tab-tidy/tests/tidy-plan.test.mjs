import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const skillDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const planScript = join(skillDir, "scripts", "tidy-plan.mjs");
const snapshotScript = join(skillDir, "scripts", "snapshot.mjs");
const fixtureDir = join(skillDir, "tests", "fixtures");
const prePath = join(fixtureDir, "synthetic-pre.json");
const postPath = join(fixtureDir, "synthetic-post.json");
const planPath = join(fixtureDir, "valid-plan.json");
const fixedArgs = ["--fixed-url", "https://docs.example.test/work-index", "--fixed-url", "http://127.0.0.1:8787/"];

function run(args) {
  return spawnSync(process.execPath, [planScript, ...args, ...fixedArgs], { encoding: "utf8" });
}

function read(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function writeJson(path, value) {
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
}

function codebaseMergeRequestCase() {
  const before = read(prePath);
  before.tabs.find((tab) => tab.id === 104).url = "https://code.byted.org/team/project/merge_requests/7?to_version=1";
  before.tabs.find((tab) => tab.id === 105).url = "https://code.byted.org/team/project/merge_requests/7/changes?dv_filepath=src%2Fmain.ts#note_1";
  before.tabs.find((tab) => tab.id === 106).url = "https://code.byted.org/team/project/merge_requests/7?to_version=2";

  const plan = read(planPath);
  plan.close = [
    { tab_id: 105, keep_tab_id: 104, reason: "same_merge_request" },
    { tab_id: 106, keep_tab_id: 104, reason: "same_merge_request" },
  ];
  plan.assign = plan.assign.filter((item) => item.tab_id !== 106);

  const after = read(postPath);
  after.tabs = after.tabs.filter((tab) => tab.id !== 106);
  after.tabs.find((tab) => tab.id === 104).url = "https://code.byted.org/team/project/merge_requests/7";
  after.totals.tabs = after.tabs.length;
  return { before, plan, after };
}

test("audit finds exact duplicates without collapsing query variants", () => {
  const result = run(["audit", "--snapshot", prePath, "--workspace", "CSI"]);
  assert.equal(result.status, 0, result.stderr);
  const report = JSON.parse(result.stdout);
  assert.deepEqual(report.exact_duplicate_groups.map((group) => group.url), [
    "https://code.example.test/merge_requests/7?to_version=1",
  ]);
  assert.equal(report.exact_duplicate_groups[0].keeper_id, 104);
  assert.deepEqual(report.exact_duplicate_groups[0].close_ids, [105]);
  assert.ok(report.ungrouped_tabs.some((tab) => tab.id === 106));
  assert.deepEqual(report.protected_ids, [101, 102, 103]);
});

test("audit treats Codebase MR paths, parameters, and fragments as one merge request", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-codebase-audit-"));
  try {
    const { before } = codebaseMergeRequestCase();
    const snapshotPath = join(tempDir, "snapshot.json");
    writeJson(snapshotPath, before);
    const result = run(["audit", "--snapshot", snapshotPath, "--workspace", "CSI"]);
    assert.equal(result.status, 0, result.stderr);
    const report = JSON.parse(result.stdout);
    assert.deepEqual(report.exact_duplicate_groups, []);
    assert.equal(report.same_merge_request_groups.length, 1);
    assert.equal(report.same_merge_request_groups[0].identity, "https://code.byted.org/team/project/merge_requests/7");
    assert.equal(report.same_merge_request_groups[0].canonical_url, "https://code.byted.org/team/project/merge_requests/7");
    assert.equal(report.same_merge_request_groups[0].keeper_id, 104);
    assert.deepEqual(new Set(report.same_merge_request_groups[0].close_ids), new Set([105, 106]));
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator accepts same-MR closes and emits the canonical keeper URL", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-codebase-validate-"));
  try {
    const { before, plan } = codebaseMergeRequestCase();
    const snapshotPath = join(tempDir, "snapshot.json");
    const codebasePlanPath = join(tempDir, "plan.json");
    writeJson(snapshotPath, before);
    writeJson(codebasePlanPath, plan);
    const result = run(["validate", "--snapshot", snapshotPath, "--plan", codebasePlanPath, "--workspace", "CSI"]);
    assert.equal(result.status, 0, result.stdout);
    const report = JSON.parse(result.stdout);
    assert.deepEqual(report.url_normalizations, [{
      tab_id: 104,
      from_url: "https://code.byted.org/team/project/merge_requests/7?to_version=1",
      to_url: "https://code.byted.org/team/project/merge_requests/7",
      reason: "same_merge_request",
    }]);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator keeps same-MR matching narrow to the Codebase host and MR number", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-codebase-boundary-"));
  try {
    const { before, plan } = codebaseMergeRequestCase();
    before.tabs.find((tab) => tab.id === 106).url = "https://code.byted.org/team/project/merge_requests/8?to_version=2";
    plan.close = [{ tab_id: 106, keep_tab_id: 104, reason: "same_merge_request" }];
    plan.keep_ungrouped.push(105);
    const snapshotPath = join(tempDir, "snapshot.json");
    const invalidPath = join(tempDir, "plan.json");
    writeJson(snapshotPath, before);
    writeJson(invalidPath, plan);
    const result = run(["validate", "--snapshot", snapshotPath, "--plan", invalidPath, "--workspace", "CSI"]);
    assert.notEqual(result.status, 0);
    assert.match(result.stdout, /not the same Codebase merge request/);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("audit supports nested Codebase namespaces without matching MR lists", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-codebase-namespace-"));
  try {
    const { before } = codebaseMergeRequestCase();
    before.tabs.find((tab) => tab.id === 104).url = "https://code.byted.org/org/team/project/merge_requests/7";
    before.tabs.find((tab) => tab.id === 105).url = "https://code.byted.org/org/team/project/merge_requests/7/changes?tab=diff";
    before.tabs.find((tab) => tab.id === 106).url = "https://code.byted.org/org/team/project/merge_requests?state=opened";
    const snapshotPath = join(tempDir, "snapshot.json");
    writeJson(snapshotPath, before);
    const result = run(["audit", "--snapshot", snapshotPath, "--workspace", "CSI"]);
    assert.equal(result.status, 0, result.stderr);
    const report = JSON.parse(result.stdout);
    assert.equal(report.same_merge_request_groups.length, 1);
    assert.equal(report.same_merge_request_groups[0].canonical_url, "https://code.byted.org/org/team/project/merge_requests/7");
    assert.deepEqual(report.same_merge_request_groups[0].close_ids, [105]);
    assert.ok(report.ungrouped_tabs.some((tab) => tab.id === 106));
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator defers a same-MR group when a lower-ranked copy is protected", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-codebase-protected-"));
  try {
    const { before, plan } = codebaseMergeRequestCase();
    before.tabs.find((tab) => tab.id === 103).active = false;
    before.tabs.find((tab) => tab.id === 104).active = true;
    before.tabs.find((tab) => tab.id === 105).pinned = true;
    plan.protected.push(104, 105);
    plan.close = [];
    plan.needs_confirmation = [105, 106];
    const snapshotPath = join(tempDir, "snapshot.json");
    const deferredPath = join(tempDir, "plan.json");
    writeJson(snapshotPath, before);
    writeJson(deferredPath, plan);
    const result = run(["validate", "--snapshot", snapshotPath, "--plan", deferredPath, "--workspace", "CSI"]);
    assert.equal(result.status, 0, result.stdout);
    const report = JSON.parse(result.stdout);
    assert.equal(report.audit.same_merge_request_groups[0].auto_close_allowed, false);
    assert.deepEqual(report.url_normalizations, []);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator does not canonicalize a fixed MR entrypoint implicitly", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-codebase-fixed-"));
  try {
    const { before, plan } = codebaseMergeRequestCase();
    const fixedMrUrl = before.tabs.find((tab) => tab.id === 105).url;
    before.tabs.find((tab) => tab.id === 104).groupId = null;
    before.tabs.find((tab) => tab.id === 104).groupTitle = "";
    before.tabs.find((tab) => tab.id === 104).groupColor = "";
    plan.protected.push(105);
    plan.keep_ungrouped.push(105);
    plan.close = [
      { tab_id: 104, keep_tab_id: 105, reason: "same_merge_request" },
      { tab_id: 106, keep_tab_id: 105, reason: "same_merge_request" },
    ];
    const snapshotPath = join(tempDir, "snapshot.json");
    const invalidPath = join(tempDir, "plan.json");
    writeJson(snapshotPath, before);
    writeJson(invalidPath, plan);
    const result = run(["validate", "--snapshot", snapshotPath, "--plan", invalidPath, "--workspace", "CSI", "--fixed-url", fixedMrUrl]);
    assert.notEqual(result.status, 0);
    assert.match(result.stdout, /Same-MR group contains protected or distinct named-stack context and must be deferred/);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("valid plan covers every candidate and emits complete rebuild sets", () => {
  const result = run(["validate", "--snapshot", prePath, "--plan", planPath, "--workspace", "CSI"]);
  assert.equal(result.status, 0, result.stderr);
  const report = JSON.parse(result.stdout);
  assert.equal(report.ok, true);
  const build = report.execution_groups.find((group) => group.target_stack === "当前｜Build");
  assert.deepEqual(build.complete_member_ids, [104, 109, 106]);
  assert.equal(build.target_color, "color1");
  const tools = report.execution_groups.find((group) => group.target_stack === "工具｜账号与权限");
  assert.equal(tools.target_color, "color2");
});

test("validator supports an explicit scope-expanding stack rename", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-rename-"));
  try {
    const plan = read(planPath);
    const build = plan.assign.find((item) => item.tab_id === 106);
    build.source_stack = "当前｜Build";
    build.target_stack = "当前｜Build Maintenance";
    build.target_kind = "renamed";
    const renamedPath = join(tempDir, "plan.json");
    writeJson(renamedPath, plan);
    const result = run(["validate", "--snapshot", prePath, "--plan", renamedPath, "--workspace", "CSI"]);
    assert.equal(result.status, 0, result.stdout);
    const report = JSON.parse(result.stdout);
    const renamed = report.execution_groups.find((group) => group.target_kind === "renamed");
    assert.equal(renamed.source_stack, "当前｜Build");
    assert.equal(renamed.target_stack, "当前｜Build Maintenance");
    assert.equal(renamed.target_color, "color1");
    assert.deepEqual(renamed.complete_member_ids, [104, 109, 106]);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator rejects consuming one existing stack through two rebuilds", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-double-consume-"));
  try {
    const plan = read(planPath);
    const build = plan.assign.find((item) => item.tab_id === 106);
    build.source_stack = "当前｜Build";
    build.target_stack = "当前｜Build Maintenance";
    build.target_kind = "renamed";
    plan.assign.push({ tab_id: 107, target_stack: "当前｜Build", target_kind: "existing" });
    plan.assign = plan.assign.filter((item) => !(item.tab_id === 107 && item.target_stack === "当前｜Research"));
    const invalidPath = join(tempDir, "plan.json");
    writeJson(invalidPath, plan);
    const result = run(["validate", "--snapshot", prePath, "--plan", invalidPath, "--workspace", "CSI"]);
    assert.notEqual(result.status, 0);
    assert.match(result.stdout, /Existing stack is consumed by multiple rebuilds/);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator rejects query-insensitive closing", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-invalid-url-"));
  try {
    const plan = read(planPath);
    plan.close = [{ tab_id: 106, keep_tab_id: 104, reason: "exact_url_duplicate" }];
    plan.needs_confirmation = [105];
    plan.assign = plan.assign.filter((item) => item.tab_id !== 106);
    const invalidPath = join(tempDir, "plan.json");
    writeJson(invalidPath, plan);
    const result = run(["validate", "--snapshot", prePath, "--plan", invalidPath, "--workspace", "CSI"]);
    assert.notEqual(result.status, 0);
    assert.match(result.stdout, /not an exact full-URL duplicate/);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator rejects a lower-priority exact-duplicate keeper", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-invalid-keeper-"));
  try {
    const plan = read(planPath);
    plan.close = [{ tab_id: 104, keep_tab_id: 105, reason: "exact_url_duplicate" }];
    plan.assign = plan.assign.filter((item) => item.tab_id !== 106);
    plan.keep_ungrouped.push(106);
    plan.needs_confirmation = [105];
    const invalidPath = join(tempDir, "plan.json");
    writeJson(invalidPath, plan);
    const result = run(["validate", "--snapshot", prePath, "--plan", invalidPath, "--workspace", "CSI"]);
    assert.notEqual(result.status, 0);
    assert.match(result.stdout, /keeper violates the safety priority/);
    assert.match(result.stdout, /destroy named stack 当前｜Build/);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator rejects partially handling an exact duplicate group", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-incomplete-duplicate-"));
  try {
    const plan = read(planPath);
    plan.close = [];
    plan.keep_ungrouped.push(105);
    const invalidPath = join(tempDir, "plan.json");
    writeJson(invalidPath, plan);
    const result = run(["validate", "--snapshot", prePath, "--plan", invalidPath, "--workspace", "CSI"]);
    assert.notEqual(result.status, 0);
    assert.match(result.stdout, /must close all lower-priority instances or defer the whole group/);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator permits deferring an entire exact duplicate group", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-deferred-duplicate-"));
  try {
    const plan = read(planPath);
    plan.close = [];
    plan.needs_confirmation = [105];
    const deferredPath = join(tempDir, "plan.json");
    writeJson(deferredPath, plan);
    const result = run(["validate", "--snapshot", prePath, "--plan", deferredPath, "--workspace", "CSI"]);
    assert.equal(result.status, 0, result.stdout);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator defers duplicates when both copies are protected", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-protected-duplicate-"));
  try {
    const snapshot = read(prePath);
    snapshot.tabs.find((tab) => tab.id === 104).pinned = true;
    snapshot.tabs.find((tab) => tab.id === 105).pinned = true;
    snapshot.tabs.find((tab) => tab.id === 109).pinned = true;
    const snapshotPath = join(tempDir, "snapshot.json");
    writeJson(snapshotPath, snapshot);
    const plan = read(planPath);
    plan.protected.push(104, 105, 109);
    plan.close = [];
    plan.assign = plan.assign.filter((item) => item.tab_id !== 106);
    plan.keep_ungrouped.push(106);
    plan.needs_confirmation = [105];
    const deferredPath = join(tempDir, "plan.json");
    writeJson(deferredPath, plan);
    const result = run(["validate", "--snapshot", snapshotPath, "--plan", deferredPath, "--workspace", "CSI"]);
    assert.equal(result.status, 0, result.stdout);
    const report = JSON.parse(result.stdout);
    assert.equal(report.audit.exact_duplicate_groups[0].auto_close_allowed, false);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("fixed URL protects an entrypoint even when it is not pinned", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-unpinned-fixed-"));
  try {
    const snapshot = read(prePath);
    snapshot.tabs.find((tab) => tab.id === 101).pinned = false;
    const snapshotPath = join(tempDir, "snapshot.json");
    writeJson(snapshotPath, snapshot);
    const plan = read(planPath);
    plan.protected = plan.protected.filter((id) => id !== 101);
    plan.keep_ungrouped = plan.keep_ungrouped.filter((id) => id !== 101);
    plan.needs_confirmation.push(101);
    const invalidPath = join(tempDir, "plan.json");
    writeJson(invalidPath, plan);
    const result = run(["validate", "--snapshot", snapshotPath, "--plan", invalidPath, "--workspace", "CSI"]);
    assert.notEqual(result.status, 0);
    assert.match(result.stdout, /Protected list is missing active, pinned, or fixed tab 101/);
    assert.match(result.stdout, /Fixed entrypoint is not kept ungrouped: 101/);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("window scope never mixes ordinary tabs from two windows", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-window-scope-"));
  try {
    const snapshot = read(prePath);
    snapshot.windows = [
      { id: 1, focused: true, activeWorkspaceId: null },
      { id: 2, focused: false, activeWorkspaceId: null },
    ];
    snapshot.tabs = [
      { ...snapshot.tabs[0], id: 201, windowId: 1, workspaceId: null, url: "https://docs.example.test/work-index" },
      { ...snapshot.tabs[1], id: 202, windowId: 1, workspaceId: null, url: "http://127.0.0.1:8787/" },
      { ...snapshot.tabs[4], id: 203, windowId: 1, workspaceId: null, url: "https://same.example.test/" },
      { ...snapshot.tabs[5], id: 204, windowId: 2, workspaceId: null, url: "https://same.example.test/" },
    ];
    snapshot.totals.tabs = snapshot.tabs.length;
    const snapshotPath = join(tempDir, "snapshot.json");
    writeJson(snapshotPath, snapshot);
    const result = run(["audit", "--snapshot", snapshotPath, "--workspace", "window", "--window-id", "1"]);
    assert.equal(result.status, 0, result.stdout);
    const report = JSON.parse(result.stdout);
    assert.equal(report.window_id, 1);
    assert.equal(report.totals.tabs, 3);
    assert.deepEqual(report.exact_duplicate_groups, []);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator rejects closing active tabs and moving fixed entrypoints", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-invalid-protected-"));
  try {
    const plan = read(planPath);
    plan.close = [{ tab_id: 103, keep_tab_id: 103, reason: "exact_url_duplicate" }];
    plan.keep_ungrouped = [102, 105, 110];
    plan.assign.push({ tab_id: 101, target_stack: "当前｜Research", target_kind: "new" });
    const invalidPath = join(tempDir, "plan.json");
    writeJson(invalidPath, plan);
    const result = run(["validate", "--snapshot", prePath, "--plan", invalidPath, "--workspace", "CSI"]);
    assert.notEqual(result.status, 0);
    assert.match(result.stdout, /Protected tab cannot be closed: 103/);
    assert.match(result.stdout, /Fixed entrypoint is not kept ungrouped: 101/);
    assert.match(result.stdout, /Pinned tab must not be assigned: 101/);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("validator rejects non-duplicate close reasons", () => {
  const tempDir = mkdtempSync(join(tmpdir(), "vivaldi-plan-authorized-"));
  try {
    const plan = read(planPath);
    plan.close.push({ tab_id: 110, reason: "user_authorized", authorization: "Close the interview notes tab." });
    plan.keep_ungrouped = plan.keep_ungrouped.filter((id) => id !== 110);
    const invalidPath = join(tempDir, "invalid.json");
    writeJson(invalidPath, plan);
    const rejected = run(["validate", "--snapshot", prePath, "--plan", invalidPath, "--workspace", "CSI"]);
    assert.notEqual(rejected.status, 0);
    assert.match(rejected.stdout, /Unsupported close reason/);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test("verify enforces set conservation and semantic stack identity", () => {
  const root = mkdtempSync(join(tmpdir(), "vivaldi-verify-bundles-"));
  const before = join(root, "before");
  const after = join(root, "after");
  mkdirSync(before);
  mkdirSync(after);
  try {
    writeBundle(before, read(prePath));
    writeBundle(after, read(postPath));
    const result = run(["verify", "--before", before, "--after", after, "--plan", planPath, "--workspace", "CSI"]);
    assert.equal(result.status, 0, result.stderr);
    const report = JSON.parse(result.stdout);
    assert.deepEqual(report.totals, { before: 11, closed: 1, concurrent_additions: 0, after: 10 });
    assert.deepEqual(report.unnamed_tab_ids, []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("verify remaps runtime tab and window IDs after a browser restart", () => {
  const root = mkdtempSync(join(tmpdir(), "vivaldi-verify-restart-"));
  const beforeDir = join(root, "before");
  const afterDir = join(root, "after");
  mkdirSync(beforeDir);
  mkdirSync(afterDir);
  try {
    const before = read(prePath);
    const after = read(postPath);
    before.bridge = { id: "bridge-before" };
    after.bridge = { id: "bridge-after" };
    after.windows[0].id = 2;
    const groupIds = new Map();
    for (const tab of after.tabs) {
      tab.id += 1000;
      tab.windowId = 2;
      if (tab.groupId) {
        if (!groupIds.has(tab.groupId)) groupIds.set(tab.groupId, `${tab.groupId}-restored`);
        tab.groupId = groupIds.get(tab.groupId);
      }
    }
    writeBundle(beforeDir, before);
    writeBundle(afterDir, after);
    const result = run(["verify", "--before", beforeDir, "--after", afterDir, "--plan", planPath, "--workspace", "CSI"]);
    assert.equal(result.status, 0, result.stdout);
    const report = JSON.parse(result.stdout);
    assert.equal(report.runtime_ids_remapped, true);
    assert.deepEqual(report.totals, { before: 11, closed: 1, concurrent_additions: 0, after: 10 });
    assert.match(report.warnings.join("\n"), /Browser restart remapped 10 surviving tabs/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("verify rejects a closed duplicate identity reintroduced after restart", () => {
  const root = mkdtempSync(join(tmpdir(), "vivaldi-verify-restart-duplicate-"));
  const beforeDir = join(root, "before");
  const afterDir = join(root, "after");
  mkdirSync(beforeDir);
  mkdirSync(afterDir);
  try {
    const before = read(prePath);
    const after = read(postPath);
    before.bridge = { id: "bridge-before" };
    after.bridge = { id: "bridge-after" };
    after.windows[0].id = 2;
    for (const tab of after.tabs) {
      tab.id += 1000;
      tab.windowId = 2;
    }
    after.tabs.push({ ...after.tabs.find((tab) => tab.id === 1104), id: 2999, title: "Reintroduced duplicate", groupId: null, groupTitle: "", groupColor: "" });
    after.totals.tabs = after.tabs.length;
    writeBundle(beforeDir, before);
    writeBundle(afterDir, after);
    const result = run(["verify", "--before", beforeDir, "--after", afterDir, "--plan", planPath, "--workspace", "CSI"]);
    assert.notEqual(result.status, 0);
    assert.match(result.stdout, /Closed duplicate identity still has an unexpected copy/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("verify requires a same-MR keeper to use the canonical URL", () => {
  const root = mkdtempSync(join(tmpdir(), "vivaldi-verify-codebase-mr-"));
  const beforeDir = join(root, "before");
  const afterDir = join(root, "after");
  mkdirSync(beforeDir);
  mkdirSync(afterDir);
  try {
    const { before, plan, after } = codebaseMergeRequestCase();
    const codebasePlanPath = join(root, "plan.json");
    writeBundle(beforeDir, before);
    writeBundle(afterDir, after);
    writeJson(codebasePlanPath, plan);
    const result = run(["verify", "--before", beforeDir, "--after", afterDir, "--plan", codebasePlanPath, "--workspace", "CSI"]);
    assert.equal(result.status, 0, result.stdout);
    const report = JSON.parse(result.stdout);
    assert.deepEqual(report.totals, { before: 11, closed: 2, concurrent_additions: 0, after: 9 });

    const nonCanonical = structuredClone(after);
    nonCanonical.tabs.find((tab) => tab.id === 104).url = "https://code.byted.org/team/project/merge_requests/7?to_version=1";
    writeBundle(afterDir, nonCanonical);
    const rejected = run(["verify", "--before", beforeDir, "--after", afterDir, "--plan", codebasePlanPath, "--workspace", "CSI"]);
    assert.notEqual(rejected.status, 0);
    assert.match(rejected.stdout, /Same-MR keeper was not normalized/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("verify rejects wrong target colors", () => {
  const root = mkdtempSync(join(tmpdir(), "vivaldi-verify-invalid-"));
  const before = join(root, "before");
  const after = join(root, "after");
  mkdirSync(before);
  mkdirSync(after);
  try {
    writeBundle(before, read(prePath));
    const post = read(postPath);
    for (const tab of post.tabs.filter((tab) => tab.groupTitle === "工具｜账号与权限")) tab.groupColor = "color3";
    writeBundle(after, post);
    const result = run(["verify", "--before", before, "--after", after, "--plan", planPath, "--workspace", "CSI"]);
    assert.notEqual(result.status, 0);
    assert.match(result.stdout, /Target stack color is wrong/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("verify rejects Workspace configuration drift", () => {
  const root = mkdtempSync(join(tmpdir(), "vivaldi-verify-workspace-drift-"));
  const before = join(root, "before");
  const after = join(root, "after");
  mkdirSync(before);
  mkdirSync(after);
  try {
    writeBundle(before, read(prePath));
    const post = read(postPath);
    post.workspaces[0].name = "Changed";
    writeBundle(after, post);
    const result = run(["verify", "--before", before, "--after", after, "--plan", planPath, "--workspace", "CSI"]);
    assert.notEqual(result.status, 0);
    assert.match(result.stdout, /Workspace configuration changed/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

function writeBundle(directory, browser) {
  const groupIds = [...new Set(browser.tabs.map((tab) => tab.groupId).filter(Boolean))];
  writeJson(join(directory, "browser-snapshot.json"), browser);
  writeJson(join(directory, "stacks.json"), {
    stacks: groupIds.map((id) => ({
      id,
      name: browser.tabs.find((tab) => tab.groupId === id).groupTitle,
      color: browser.tabs.find((tab) => tab.groupId === id).groupColor,
      windowId: browser.tabs.find((tab) => tab.groupId === id).windowId,
      workspaceId: browser.tabs.find((tab) => tab.groupId === id).workspaceId,
      tabs: browser.tabs.filter((tab) => tab.groupId === id),
    })),
    total: groupIds.length,
  });
  writeJson(join(directory, "workspaces.json"), { windows: browser.windows, workspaces: browser.workspaces, total: browser.workspaces.length });
  writeJson(join(directory, "workspace-rules.json"), { rules: [], total: 0 });
}

test("snapshot writes four files to a private ref without touching the worktree", () => {
  const root = mkdtempSync(join(tmpdir(), "vivaldi-snapshot-test-"));
  const source = join(root, "source");
  const output = join(root, "output");
  const repo = join(root, "repo");
  mkdirSync(source);
  mkdirSync(repo);
  try {
    const browser = read(prePath);
    writeBundle(source, browser);
    execFileSync("git", ["init", "--quiet", repo]);

    const result = spawnSync(process.execPath, [snapshotScript, "--phase", "pre-tidy", "--repo", repo, "--source-dir", source, "--output-dir", output, "--ref", "refs/vivaldi-snapshots/test-pre"], { encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr);
    const report = JSON.parse(result.stdout);
    assert.equal(report.totals.tabs, 11);
    assert.equal(report.totals.stacks, 2);
    assert.match(execFileSync("git", ["-C", repo, "show-ref", "--verify", "refs/vivaldi-snapshots/test-pre"], { encoding: "utf8" }), /refs\/vivaldi-snapshots\/test-pre/);
    for (const filename of ["browser-snapshot.json", "stacks.json", "workspaces.json", "workspace-rules.json"]) {
      execFileSync("git", ["-C", repo, "cat-file", "-e", `refs/vivaldi-snapshots/test-pre:${filename}`]);
    }
    assert.equal(execFileSync("git", ["-C", repo, "status", "--porcelain"], { encoding: "utf8" }), "");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("snapshot rejects inconsistent browser and stack membership", () => {
  const root = mkdtempSync(join(tmpdir(), "vivaldi-snapshot-invalid-"));
  const source = join(root, "source");
  const output = join(root, "output");
  const repo = join(root, "repo");
  mkdirSync(source);
  mkdirSync(repo);
  try {
    const browser = read(prePath);
    writeJson(join(source, "browser-snapshot.json"), browser);
    writeJson(join(source, "stacks.json"), { stacks: [], total: 0 });
    writeJson(join(source, "workspaces.json"), { windows: browser.windows, workspaces: browser.workspaces, total: browser.workspaces.length });
    writeJson(join(source, "workspace-rules.json"), { rules: [], total: 0 });
    execFileSync("git", ["init", "--quiet", repo]);
    const result = spawnSync(process.execPath, [snapshotScript, "--phase", "pre-tidy", "--repo", repo, "--source-dir", source, "--output-dir", output, "--ref", "refs/vivaldi-snapshots/test-pre"], { encoding: "utf8" });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /disagree about grouped tabs/);
    const ref = spawnSync("git", ["-C", repo, "show-ref", "--verify", "--quiet", "refs/vivaldi-snapshots/test-pre"]);
    assert.notEqual(ref.status, 0);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("snapshot rejects swapped stack memberships", () => {
  const root = mkdtempSync(join(tmpdir(), "vivaldi-snapshot-swapped-"));
  const source = join(root, "source");
  const output = join(root, "output");
  const repo = join(root, "repo");
  mkdirSync(source);
  mkdirSync(repo);
  try {
    const browser = read(prePath);
    writeBundle(source, browser);
    const stacksPath = join(source, "stacks.json");
    const stacks = read(stacksPath);
    [stacks.stacks[0].tabs, stacks.stacks[1].tabs] = [stacks.stacks[1].tabs, stacks.stacks[0].tabs];
    writeJson(stacksPath, stacks);
    execFileSync("git", ["init", "--quiet", repo]);
    const result = spawnSync(process.execPath, [snapshotScript, "--phase", "pre-tidy", "--repo", repo, "--source-dir", source, "--output-dir", output, "--ref", "refs/vivaldi-snapshots/test-pre"], { encoding: "utf8" });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Stack membership disagrees/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("scripts expose usage without touching Vivaldi or Git", () => {
  const planHelp = spawnSync(process.execPath, [planScript, "--help"], { encoding: "utf8" });
  const snapshotHelp = spawnSync(process.execPath, [snapshotScript, "--help"], { encoding: "utf8" });
  assert.equal(planHelp.status, 0, planHelp.stderr);
  assert.equal(snapshotHelp.status, 0, snapshotHelp.stderr);
  assert.match(planHelp.stdout, /^@USAGE tidy-plan\.mjs/m);
  assert.match(snapshotHelp.stdout, /^@USAGE snapshot\.mjs/m);
});
