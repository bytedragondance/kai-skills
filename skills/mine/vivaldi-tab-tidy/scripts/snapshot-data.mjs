import { readFileSync, statSync } from "node:fs";
import { join } from "node:path";

export const SNAPSHOT_FILES = [
  "browser-snapshot.json",
  "stacks.json",
  "workspaces.json",
  "workspace-rules.json",
];

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function duplicateIds(items) {
  const seen = new Set();
  const duplicates = new Set();
  for (const item of items) {
    if (seen.has(item.id)) duplicates.add(item.id);
    seen.add(item.id);
  }
  return [...duplicates];
}

function sortedJson(value) {
  return JSON.stringify(value.sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right))));
}

export function loadBrowserSnapshot(path) {
  const target = statSync(path).isDirectory() ? join(path, "browser-snapshot.json") : path;
  return readJson(target);
}

export function loadSnapshotBundle(directory) {
  if (!statSync(directory).isDirectory()) throw new Error(`Full snapshot directory required: ${directory}`);
  return {
    browser: readJson(join(directory, "browser-snapshot.json")),
    stacks: readJson(join(directory, "stacks.json")),
    workspaces: readJson(join(directory, "workspaces.json")),
    rules: readJson(join(directory, "workspace-rules.json")),
  };
}

export function validateSnapshotBundle(bundle) {
  const errors = [];
  const { browser, stacks, workspaces, rules } = bundle;
  if (!Array.isArray(browser.tabs) || !Array.isArray(browser.windows) || !Array.isArray(browser.workspaces)) errors.push("Browser snapshot is missing tabs, windows, or workspaces");
  if (!Array.isArray(stacks.stacks)) errors.push("Stack snapshot is missing stacks");
  if (!Array.isArray(workspaces.windows) || !Array.isArray(workspaces.workspaces)) errors.push("Workspace snapshot is missing windows or workspaces");
  if (!Array.isArray(rules.rules)) errors.push("Workspace-rule snapshot is missing rules");
  if (errors.length) return { errors };

  if (browser.totals?.tabs !== browser.tabs.length) errors.push("Browser tab total does not match the tab list");
  if (stacks.total !== stacks.stacks.length) errors.push("Stack total does not match the stack list");
  if (workspaces.total !== workspaces.workspaces.length) errors.push("Workspace total does not match the Workspace list");
  if (rules.total !== rules.rules.length) errors.push("Workspace-rule total does not match the rule list");

  for (const [label, items] of [["browser tab", browser.tabs], ["browser window", browser.windows], ["browser Workspace", browser.workspaces], ["stack", stacks.stacks], ["Workspace-list window", workspaces.windows], ["Workspace-list Workspace", workspaces.workspaces]]) {
    const duplicates = duplicateIds(items);
    if (duplicates.length) errors.push(`Duplicate ${label} IDs: ${duplicates.join(", ")}`);
  }

  const browserWorkspaceSummary = browser.workspaces.map(({ id, name, index }) => ({ id, name, index }));
  const listedWorkspaceSummary = workspaces.workspaces.map(({ id, name, index }) => ({ id, name, index }));
  if (sortedJson(browserWorkspaceSummary) !== sortedJson(listedWorkspaceSummary)) errors.push("Browser and Workspace views disagree about Workspace identity or order");
  const browserWindowSummary = browser.windows.map(({ id, activeWorkspaceId }) => ({ id, activeWorkspaceId: activeWorkspaceId ?? null }));
  const listedWindowSummary = workspaces.windows.map(({ id, activeWorkspaceId }) => ({ id, activeWorkspaceId: activeWorkspaceId ?? null }));
  if (sortedJson(browserWindowSummary) !== sortedJson(listedWindowSummary)) errors.push("Browser and Workspace views disagree about windows");

  const workspaceIds = new Set(browser.workspaces.map((workspace) => String(workspace.id)));
  const windowIds = new Set(browser.windows.map((window) => Number(window.id)));
  const tabsById = new Map(browser.tabs.map((tab) => [Number(tab.id), tab]));
  for (const tab of browser.tabs) {
    if (!windowIds.has(Number(tab.windowId))) errors.push(`Tab ${tab.id} references unknown window ${tab.windowId}`);
    if (tab.workspaceId != null && !workspaceIds.has(String(tab.workspaceId))) errors.push(`Tab ${tab.id} references unknown Workspace ${tab.workspaceId}`);
  }

  const listedTabIds = new Set();
  for (const stack of stacks.stacks) {
    if (!windowIds.has(Number(stack.windowId))) errors.push(`Stack ${stack.id} references unknown window ${stack.windowId}`);
    if (stack.workspaceId != null && !workspaceIds.has(String(stack.workspaceId))) errors.push(`Stack ${stack.id} references unknown Workspace ${stack.workspaceId}`);
    for (const nested of stack.tabs || []) {
      const id = Number(nested.id);
      if (listedTabIds.has(id)) errors.push(`Tab ${id} appears in multiple stack entries`);
      listedTabIds.add(id);
      const tab = tabsById.get(id);
      if (!tab) { errors.push(`Stack ${stack.id} contains unknown tab ${id}`); continue; }
      if (tab.groupId !== stack.id || nested.groupId !== stack.id) errors.push(`Stack membership disagrees for tab ${id}`);
      if (Number(tab.windowId) !== Number(stack.windowId) || Number(nested.windowId) !== Number(stack.windowId)) errors.push(`Stack window disagrees for tab ${id}`);
      if (String(tab.workspaceId) !== String(stack.workspaceId) || String(nested.workspaceId) !== String(stack.workspaceId)) errors.push(`Stack Workspace disagrees for tab ${id}`);
      if ((tab.groupTitle || "") !== (stack.name || "") || (nested.groupTitle || "") !== (stack.name || "")) errors.push(`Stack name disagrees for tab ${id}`);
      if ((tab.groupColor || "") !== (stack.color || "") || (nested.groupColor || "") !== (stack.color || "")) errors.push(`Stack color disagrees for tab ${id}`);
    }
  }
  const groupedIds = new Set(browser.tabs.filter((tab) => tab.groupId).map((tab) => Number(tab.id)));
  if (groupedIds.size !== listedTabIds.size || [...groupedIds].some((id) => !listedTabIds.has(id))) errors.push("Browser and stack views disagree about grouped tabs");

  for (const rule of rules.rules) {
    const workspaceId = rule.workspaceId ?? rule.workspace?.id;
    if (workspaceId != null && !workspaceIds.has(String(workspaceId))) errors.push(`Workspace rule references unknown Workspace ${workspaceId}`);
  }

  return {
    errors,
    totals: { tabs: browser.tabs.length, stacks: stacks.stacks.length, workspaces: workspaces.workspaces.length, rules: rules.rules.length },
  };
}

export function compareSnapshotConfiguration(before, after, { allowRuntimeIdChanges = false } = {}) {
  const errors = [];
  const workspaceFields = (bundle) => bundle.workspaces.workspaces.map(({ id, name, emoji, iconId, index }) => ({ id, name, emoji: emoji ?? "", iconId: iconId ?? null, index }));
  const windowFields = (bundle) => bundle.workspaces.windows.map(({ id, activeWorkspaceId }) => ({
    ...(allowRuntimeIdChanges ? {} : { id }),
    activeWorkspaceId: activeWorkspaceId ?? null,
  }));
  if (sortedJson(workspaceFields(before)) !== sortedJson(workspaceFields(after))) errors.push("Workspace configuration changed");
  if (sortedJson(windowFields(before)) !== sortedJson(windowFields(after))) errors.push("Window-to-Workspace assignment changed");
  if (JSON.stringify(before.rules.rules) !== JSON.stringify(after.rules.rules)) errors.push("Workspace routing rules changed");
  return errors;
}
