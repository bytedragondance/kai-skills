#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { compareSnapshotConfiguration, loadBrowserSnapshot, loadSnapshotBundle, validateSnapshotBundle } from "./snapshot-data.mjs";

const ROLES = new Set(["当前", "项目", "评审", "分析", "参考", "工具", "证据"]);
const ROLE_COLORS = new Map([["当前", "color1"], ["工具", "color2"], ["参考", "color3"], ["项目", "color4"], ["分析", "color5"], ["评审", "color6"], ["证据", "color9"]]);
const USAGE = `@USAGE tidy-plan.mjs

BRIEF: Audit, validate, or verify a conservative Vivaldi tab-tidy plan.

SYNTAX:
  tidy-plan.mjs audit --snapshot DIR_OR_FILE --fixed-url URL... [--workspace NAME_OR_ID] [--window-id ID]
  tidy-plan.mjs validate --snapshot DIR_OR_FILE --plan FILE --fixed-url URL... [--workspace NAME_OR_ID] [--window-id ID]
  tidy-plan.mjs verify --before DIR --after DIR --plan FILE --fixed-url URL... [--workspace NAME_OR_ID] [--window-id ID]

EXAMPLES:
  node tidy-plan.mjs audit --snapshot /tmp/pre --fixed-url https://example.test/index
  node tidy-plan.mjs validate --snapshot /tmp/pre --plan /tmp/plan.json --fixed-url https://example.test/index
  node tidy-plan.mjs verify --before /tmp/pre --after /tmp/post --plan /tmp/plan.json --fixed-url https://example.test/index
`;

function die(message, details = []) {
  process.stderr.write(`${JSON.stringify({ ok: false, errors: [message, ...details] }, null, 2)}\n`);
  process.exit(1);
}

function parseArgs(argv) {
  const command = argv.shift();
  const result = { command };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith("--")) die(`Unexpected argument: ${key}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) die(`Missing value for ${key}`);
    const name = key.slice(2);
    if (name === "fixed-url" && result[name] != null) {
      result[name] = Array.isArray(result[name]) ? [...result[name], value] : [result[name], value];
    } else {
      result[name] = value;
    }
    index += 1;
  }
  return result;
}

function loadJson(path) {
  try {
    return loadBrowserSnapshot(path);
  } catch (error) {
    die(`Cannot read snapshot ${path}: ${error.message}`);
  }
}

function loadPlan(path) {
  try { return JSON.parse(readFileSync(path, "utf8")); }
  catch (error) { die(`Cannot read plan ${path}: ${error.message}`); }
}

function resolveScope(snapshot, selector, requestedWindowId) {
  const workspaces = snapshot.workspaces || [];
  const windows = snapshot.windows || [];
  const explicitWindowId = requestedWindowId == null ? null : Number(requestedWindowId);
  if (requestedWindowId != null && !Number.isInteger(explicitWindowId)) die(`Invalid --window-id: ${requestedWindowId}`);
  let workspaceId;
  let workspaceName;
  let windowId = explicitWindowId;
  if (selector === "window") {
    workspaceId = null;
    workspaceName = "window";
    if (windowId == null) {
      const focused = windows.filter((window) => window.focused);
      if (windows.length === 1) windowId = Number(windows[0].id);
      else if (focused.length === 1) windowId = Number(focused[0].id);
      else die("Window scope is ambiguous; pass --window-id");
    }
  } else if (selector != null) {
    const exact = workspaces.filter((workspace) => String(workspace.id) === String(selector) || workspace.name.toLocaleLowerCase() === String(selector).toLocaleLowerCase());
    if (exact.length !== 1) die(`Workspace selector must resolve once: ${selector}`);
    workspaceId = exact[0].id;
    workspaceName = exact[0].name;
    if (windowId == null) {
      const containingWindowIds = [...new Set((snapshot.tabs || []).filter((tab) => String(tab.workspaceId) === String(workspaceId)).map((tab) => Number(tab.windowId)))];
      if (containingWindowIds.length !== 1) die(`Workspace ${workspaceName} spans zero or multiple windows; pass --window-id`);
      windowId = containingWindowIds[0];
    }
  } else {
    const focused = windows.filter((window) => window.focused);
    const activeWindow = windows.length === 1 ? windows[0] : focused.length === 1 ? focused[0] : null;
    if (!activeWindow) die("No unique active window; pass --workspace");
    windowId = Number(activeWindow.id);
    workspaceId = activeWindow.activeWorkspaceId ?? null;
    workspaceName = workspaceId == null ? "window" : workspaces.find((workspace) => String(workspace.id) === String(workspaceId))?.name || String(workspaceId);
  }
  if (windowId != null && !windows.some((window) => Number(window.id) === windowId)) die(`Window is absent from snapshot: ${windowId}`);
  const tabs = (snapshot.tabs || []).filter((tab) => {
    const workspaceMatches = workspaceId == null ? tab.workspaceId == null : String(tab.workspaceId) === String(workspaceId);
    const windowMatches = windowId == null || Number(tab.windowId) === windowId;
    return workspaceMatches && windowMatches;
  });
  return { workspaceId, workspaceName, windowId, tabs };
}

function keeperRank(tab, fixedIds) {
  return [Boolean(tab.active), fixedIds.has(tab.id), Boolean(tab.pinned), Boolean(tab.groupId && tab.groupTitle), !tab.discarded, Number(tab.index), Number(tab.id)];
}

function compareRank(left, right, fixedIds) {
  const a = keeperRank(left, fixedIds);
  const b = keeperRank(right, fixedIds);
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] === b[index]) continue;
    return a[index] > b[index] ? -1 : 1;
  }
  return 0;
}

function compareFixedEntryRank(left, right) {
  const rank = (tab) => [!tab.groupId, Boolean(tab.active), Boolean(tab.pinned), !tab.discarded, Number(tab.index), Number(tab.id)];
  const a = rank(left);
  const b = rank(right);
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] === b[index]) continue;
    return a[index] > b[index] ? -1 : 1;
  }
  return 0;
}

function codebaseMergeRequest(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" || parsed.host !== "code.byted.org" || parsed.username || parsed.password) return null;
    const match = parsed.pathname.match(/^\/((?:[^/]+\/)+[^/]+)\/merge_requests\/(\d+)(?:\/changes)?\/?$/);
    if (!match) return null;
    const canonicalUrl = `https://code.byted.org/${match[1]}/merge_requests/${match[2]}`;
    return { identity: canonicalUrl, canonical_url: canonicalUrl };
  } catch {
    return null;
  }
}

function duplicateGroup(tabs, fixedIds, { includeUrls = false, ...extra } = {}) {
  const ranked = [...tabs].sort((left, right) => compareRank(left, right, fixedIds));
  const namedContexts = new Set(ranked.filter((tab) => tab.groupId && tab.groupTitle).map((tab) => tab.groupId));
  const protectedIds = new Set(ranked.filter((tab) => tab.active || tab.pinned || fixedIds.has(tab.id)).map((tab) => tab.id));
  return {
    ...extra,
    keeper_id: ranked[0].id,
    close_ids: ranked.slice(1).map((tab) => tab.id),
    auto_close_allowed: ranked.slice(1).every((tab) => !protectedIds.has(tab.id)) && namedContexts.size <= 1,
    tabs: ranked.map((tab) => ({ id: tab.id, index: tab.index, ...(includeUrls ? { url: tab.url } : {}), active: tab.active, pinned: tab.pinned, discarded: tab.discarded, group: tab.groupTitle || null })),
  };
}

function audit(snapshot, selector, fixedUrls = [], windowId) {
  const scope = resolveScope(snapshot, selector, windowId);
  const fixedEntries = fixedUrls.map((url) => {
    const matches = scope.tabs.filter((tab) => tab.url === url).sort(compareFixedEntryRank);
    if (!matches.length) die(`Fixed entrypoint URL is absent from the selected scope: ${url}`);
    return { url, id: matches[0].id };
  });
  const fixedIds = new Set(fixedEntries.map((entry) => entry.id));
  const byMergeRequest = new Map();
  for (const tab of scope.tabs) {
    const mergeRequest = codebaseMergeRequest(tab.url);
    if (!mergeRequest) continue;
    if (!byMergeRequest.has(mergeRequest.identity)) byMergeRequest.set(mergeRequest.identity, []);
    byMergeRequest.get(mergeRequest.identity).push(tab);
  }
  const mergeRequestGroups = [...byMergeRequest.entries()]
    .filter(([, tabs]) => tabs.length > 1)
    .map(([identity, tabs]) => {
      const group = duplicateGroup(tabs, fixedIds, { identity, canonical_url: identity, includeUrls: true });
      const changesFixedEntrypoint = tabs.some((tab) => fixedIds.has(tab.id) && tab.url !== identity);
      return { ...group, auto_close_allowed: group.auto_close_allowed && !changesFixedEntrypoint };
    });
  const mergeRequestTabIds = new Set(mergeRequestGroups.flatMap((group) => group.tabs.map((tab) => tab.id)));
  const byUrl = new Map();
  for (const tab of scope.tabs.filter((candidate) => !mergeRequestTabIds.has(candidate.id))) {
    if (!byUrl.has(tab.url)) byUrl.set(tab.url, []);
    byUrl.get(tab.url).push(tab);
  }
  const duplicateGroups = [...byUrl.entries()]
    .filter(([url, tabs]) => url && tabs.length > 1)
    .map(([url, tabs]) => duplicateGroup(tabs, fixedIds, { url }));
  const unnamedStackIds = [...new Set(scope.tabs.filter((tab) => tab.groupId && !String(tab.groupTitle || "").trim()).map((tab) => tab.groupId))];
  const candidateIds = new Set(scope.tabs.filter((tab) => !tab.groupId || unnamedStackIds.includes(tab.groupId)).map((tab) => tab.id));
  for (const group of duplicateGroups) for (const id of group.close_ids) candidateIds.add(id);
  for (const group of mergeRequestGroups) for (const id of group.close_ids) candidateIds.add(id);
  const namedStacks = [...new Map(scope.tabs.filter((tab) => tab.groupId && String(tab.groupTitle || "").trim()).map((tab) => [tab.groupId, { id: tab.groupId, name: tab.groupTitle, color: tab.groupColor, member_ids: [] }])).values()];
  for (const stack of namedStacks) stack.member_ids = scope.tabs.filter((tab) => tab.groupId === stack.id).map((tab) => tab.id);
  return {
    workspace: { id: scope.workspaceId, name: scope.workspaceName },
    window_id: scope.windowId,
    totals: { tabs: scope.tabs.length, named_stacks: namedStacks.length, unnamed_stacks: unnamedStackIds.length, grouped: scope.tabs.filter((tab) => tab.groupId).length, ungrouped: scope.tabs.filter((tab) => !tab.groupId).length },
    protected_ids: scope.tabs.filter((tab) => tab.active || tab.pinned || fixedIds.has(tab.id)).map((tab) => tab.id),
    fixed_entrypoints: fixedEntries,
    active_ids: scope.tabs.filter((tab) => tab.active).map((tab) => tab.id),
    pinned_ids: scope.tabs.filter((tab) => tab.pinned).map((tab) => tab.id),
    unnamed_stack_ids: unnamedStackIds,
    ungrouped_tabs: scope.tabs.filter((tab) => !tab.groupId).map((tab) => ({ id: tab.id, index: tab.index, title: tab.title, url: tab.url, active: tab.active, pinned: tab.pinned, discarded: tab.discarded })),
    named_stacks: namedStacks,
    exact_duplicate_groups: duplicateGroups,
    same_merge_request_groups: mergeRequestGroups,
    candidate_ids: [...candidateIds].sort((a, b) => a - b),
  };
}

function validatePlan(snapshot, plan, selector, fixedUrls = [], windowId) {
  const selectedWindowId = windowId ?? plan.window_id;
  const report = audit(snapshot, selector ?? plan.workspace, fixedUrls, selectedWindowId);
  const scope = resolveScope(snapshot, selector ?? plan.workspace, selectedWindowId);
  const tabsById = new Map(scope.tabs.map((tab) => [tab.id, tab]));
  const errors = [];
  if (!("workspace" in plan)) errors.push("workspace is required");
  if (!("window_id" in plan) || !Number.isInteger(Number(plan.window_id))) errors.push("window_id is required and must be an integer");
  const arrays = ["protected", "keep_ungrouped", "close", "assign", "needs_confirmation"];
  for (const key of arrays) if (!Array.isArray(plan[key])) errors.push(`${key} must be an array`);
  if (errors.length) return { ok: false, errors };
  const declaredScope = resolveScope(snapshot, plan.workspace, selectedWindowId);
  if (String(declaredScope.workspaceId) !== String(scope.workspaceId)) {
    errors.push(`Plan Workspace ${declaredScope.workspaceName} does not match selected Workspace ${scope.workspaceName}`);
  }
  if (Number(plan.window_id) !== Number(scope.windowId)) errors.push(`Plan window ${plan.window_id} does not match selected window ${scope.windowId}`);

  const protectedIds = new Set(plan.protected.map(Number));
  const fixedIds = new Set(report.fixed_entrypoints.map((entry) => entry.id));
  const keepUngroupedIds = new Set(plan.keep_ungrouped.map(Number));
  for (const id of report.protected_ids) if (!protectedIds.has(id)) errors.push(`Protected list is missing active, pinned, or fixed tab ${id}`);
  for (const id of protectedIds) if (!tabsById.has(id)) errors.push(`Protected tab is outside the scope or missing: ${id}`);
  for (const id of fixedIds) {
    const tab = tabsById.get(id);
    if (!tab) errors.push(`Fixed entrypoint is outside the scope or missing: ${id}`);
    else if (tab.groupId) errors.push(`Fixed entrypoint is not ungrouped in the baseline: ${id}`);
    if (!protectedIds.has(id)) errors.push(`Fixed entrypoint is not protected: ${id}`);
    if (!keepUngroupedIds.has(id)) errors.push(`Fixed entrypoint is not kept ungrouped: ${id}`);
  }

  const closeIds = new Set();
  const duplicateByUrl = new Map(report.exact_duplicate_groups.map((group) => [group.url, group]));
  const mergeRequestByIdentity = new Map(report.same_merge_request_groups.map((group) => [group.identity, group]));
  for (const item of plan.close) {
    const id = Number(item.tab_id);
    const keeperId = Number(item.keep_tab_id);
    const tab = tabsById.get(id);
    const keeper = Number.isFinite(keeperId) ? tabsById.get(keeperId) : null;
    if (closeIds.has(id)) errors.push(`Tab appears twice in close: ${id}`);
    closeIds.add(id);
    if (!tab) errors.push(`Close mapping contains an unknown tab: ${id}`);
    if (item.reason === "exact_url_duplicate") {
      if (!keeper) errors.push(`Exact-duplicate close has no in-scope keeper: ${id} -> ${item.keep_tab_id}`);
      else if (tab.url !== keeper.url) errors.push(`Close mapping is not an exact full-URL duplicate: ${id} -> ${keeperId}`);
      const expectedKeeper = tab ? duplicateByUrl.get(tab.url)?.keeper_id : null;
      if (expectedKeeper != null && keeperId !== expectedKeeper) errors.push(`Exact-duplicate keeper violates the safety priority: expected ${expectedKeeper}, found ${keeperId}`);
      if (id === keeperId || closeIds.has(keeperId)) errors.push(`Keeper must survive and differ from closed tab: ${id} -> ${keeperId}`);
    } else if (item.reason === "same_merge_request") {
      const tabMergeRequest = tab ? codebaseMergeRequest(tab.url) : null;
      const keeperMergeRequest = keeper ? codebaseMergeRequest(keeper.url) : null;
      if (!keeper) errors.push(`Same-MR close has no in-scope keeper: ${id} -> ${item.keep_tab_id}`);
      else if (!tabMergeRequest || !keeperMergeRequest || tabMergeRequest.identity !== keeperMergeRequest.identity) {
        errors.push(`Close mapping is not the same Codebase merge request: ${id} -> ${keeperId}`);
      }
      const expectedKeeper = tabMergeRequest ? mergeRequestByIdentity.get(tabMergeRequest.identity)?.keeper_id : null;
      if (expectedKeeper != null && keeperId !== expectedKeeper) errors.push(`Same-MR keeper violates the safety priority: expected ${expectedKeeper}, found ${keeperId}`);
      if (id === keeperId || closeIds.has(keeperId)) errors.push(`Keeper must survive and differ from closed tab: ${id} -> ${keeperId}`);
    } else {
      errors.push(`Unsupported close reason for tab ${id}`);
    }
    if (protectedIds.has(id) || tab?.active || tab?.pinned) errors.push(`Protected tab cannot be closed: ${id}`);
  }
  for (const stack of report.named_stacks) {
    const survivors = stack.member_ids.filter((id) => !closeIds.has(id));
    const affected = survivors.length !== stack.member_ids.length;
    if (affected && survivors.length < 2) errors.push(`Closing would destroy named stack ${stack.name}`);
  }
  for (const group of report.exact_duplicate_groups) {
    const planned = new Set(plan.close.filter((item) => item.reason === "exact_url_duplicate" && tabsById.get(Number(item.tab_id))?.url === group.url).map((item) => Number(item.tab_id)));
    const expected = new Set(group.close_ids);
    const deferred = new Set(plan.needs_confirmation.map(Number).filter((id) => expected.has(id)));
    const closesAll = planned.size === expected.size && [...expected].every((id) => planned.has(id));
    const defersAll = planned.size === 0 && deferred.size === expected.size;
    if (closesAll && !group.auto_close_allowed) errors.push(`Exact-duplicate group contains protected or distinct named-stack context and must be deferred: ${group.url}`);
    if (!closesAll && !defersAll) {
      errors.push(`Exact-duplicate group must close all lower-priority instances or defer the whole group: ${group.url}`);
    }
  }
  const urlNormalizations = [];
  for (const group of report.same_merge_request_groups) {
    const planned = new Set(plan.close.filter((item) => {
      const tab = tabsById.get(Number(item.tab_id));
      return item.reason === "same_merge_request" && codebaseMergeRequest(tab?.url)?.identity === group.identity;
    }).map((item) => Number(item.tab_id)));
    const expected = new Set(group.close_ids);
    const deferred = new Set(plan.needs_confirmation.map(Number).filter((id) => expected.has(id)));
    const closesAll = planned.size === expected.size && [...expected].every((id) => planned.has(id));
    const defersAll = planned.size === 0 && deferred.size === expected.size;
    if (closesAll && !group.auto_close_allowed) errors.push(`Same-MR group contains protected or distinct named-stack context and must be deferred: ${group.identity}`);
    if (!closesAll && !defersAll) errors.push(`Same-MR group must close all lower-priority instances or defer the whole group: ${group.identity}`);
    const keeper = tabsById.get(Number(group.keeper_id));
    if (closesAll && keeper?.url !== group.canonical_url) {
      urlNormalizations.push({ tab_id: group.keeper_id, from_url: keeper.url, to_url: group.canonical_url, reason: "same_merge_request" });
    }
  }
  for (const item of plan.close) {
    if (["exact_url_duplicate", "same_merge_request"].includes(item.reason) && closeIds.has(Number(item.keep_tab_id))) errors.push(`Keeper is also scheduled to close: ${item.keep_tab_id}`);
  }

  const assignmentIds = new Set();
  const assignmentsByTarget = new Map();
  for (const item of plan.assign) {
    const id = Number(item.tab_id);
    const tab = tabsById.get(id);
    if (!tab) errors.push(`Assigned tab is outside the scope or missing: ${id}`);
    if (assignmentIds.has(id)) errors.push(`Tab appears in multiple assignments: ${id}`);
    assignmentIds.add(id);
    if (closeIds.has(id)) errors.push(`Tab is both closed and assigned: ${id}`);
    if (tab?.pinned) errors.push(`Pinned tab must not be assigned: ${id}`);
    if (tab?.groupTitle && item.target_stack !== tab.groupTitle && !(item.target_kind === "renamed" && item.source_stack === tab.groupTitle)) errors.push(`Stable named-stack tab cannot move to another stack: ${id}`);
    if (!item.target_stack || !["existing", "new", "renamed"].includes(item.target_kind)) errors.push(`Invalid assignment target for tab ${id}`);
    if (item.target_kind === "renamed" && !item.source_stack) errors.push(`Renamed stack assignment requires source_stack for tab ${id}`);
    const key = JSON.stringify([item.target_kind, item.source_stack || "", item.target_stack]);
    if (!assignmentsByTarget.has(key)) assignmentsByTarget.set(key, []);
    assignmentsByTarget.get(key).push(id);
  }

  const existingByName = new Map();
  for (const stack of report.named_stacks) {
    if (!existingByName.has(stack.name)) existingByName.set(stack.name, []);
    existingByName.get(stack.name).push(stack);
  }
  const executionGroups = [];
  for (const [key, assignedIds] of assignmentsByTarget) {
    const [kind, sourceName, name] = JSON.parse(key);
    if (kind === "existing") {
      const matches = existingByName.get(name) || [];
      if (matches.length !== 1) errors.push(`Existing stack target must resolve once: ${name}`);
      else {
        const targetTabs = matches[0].member_ids.map((id) => tabsById.get(id));
        const targetWindow = targetTabs[0]?.windowId;
        if (assignedIds.some((id) => tabsById.get(id)?.windowId !== targetWindow)) errors.push(`Existing stack assignment crosses windows: ${name}`);
        const targetPinned = targetTabs[0]?.pinned;
        if (assignedIds.some((id) => tabsById.get(id)?.pinned !== targetPinned)) errors.push(`Existing stack assignment mixes pinned and unpinned tabs: ${name}`);
        executionGroups.push({ target_stack: name, target_kind: kind, target_color: matches[0].color, current_group_id: matches[0].id, assigned_ids: assignedIds, complete_member_ids: [...new Set([...matches[0].member_ids.filter((id) => !closeIds.has(id)), ...assignedIds])] });
      }
    } else if (kind === "new") {
      if ((existingByName.get(name) || []).length) errors.push(`New stack duplicates an existing stack name: ${name}`);
      const parts = name.split("｜");
      if (parts.length !== 2 || !ROLES.has(parts[0]) || !parts[1].trim()) errors.push(`New stack must use an allowed role｜topic name: ${name}`);
      if (name.length > 50) errors.push(`New stack name exceeds Vivaldi's 50-character limit: ${name}`);
      if (assignedIds.length < 2) errors.push(`New stack requires at least two assigned tabs: ${name}`);
      if (new Set(assignedIds.map((id) => tabsById.get(id)?.windowId)).size !== 1) errors.push(`New stack assignment crosses windows: ${name}`);
      executionGroups.push({ target_stack: name, target_kind: kind, target_color: ROLE_COLORS.get(parts[0]), assigned_ids: assignedIds, complete_member_ids: assignedIds });
    } else {
      const sources = existingByName.get(sourceName) || [];
      if (sources.length !== 1) errors.push(`Renamed source stack must resolve once: ${sourceName}`);
      if ((existingByName.get(name) || []).length) errors.push(`Renamed target already exists: ${name}`);
      const parts = name.split("｜");
      if (parts.length !== 2 || !ROLES.has(parts[0]) || !parts[1].trim()) errors.push(`Renamed stack must use an allowed role｜topic name: ${name}`);
      if (name.length > 50) errors.push(`Renamed stack name exceeds Vivaldi's 50-character limit: ${name}`);
      if (sources.length === 1) {
        const sourceTabs = sources[0].member_ids.map((id) => tabsById.get(id));
        const targetWindow = sourceTabs[0]?.windowId;
        if (assignedIds.some((id) => tabsById.get(id)?.windowId !== targetWindow)) errors.push(`Renamed stack assignment crosses windows: ${sourceName}`);
        const sourcePinned = sourceTabs[0]?.pinned;
        if (assignedIds.some((id) => tabsById.get(id)?.pinned !== sourcePinned)) errors.push(`Renamed stack assignment mixes pinned and unpinned tabs: ${sourceName}`);
        executionGroups.push({ source_stack: sourceName, target_stack: name, target_kind: kind, target_color: sources[0].color, current_group_id: sources[0].id, assigned_ids: assignedIds, complete_member_ids: [...new Set([...sources[0].member_ids.filter((id) => !closeIds.has(id)), ...assignedIds])] });
      }
    }
  }
  const consumedGroupIds = new Map();
  const targetNames = new Map();
  for (const group of executionGroups) {
    if (group.current_group_id) {
      if (consumedGroupIds.has(group.current_group_id)) errors.push(`Existing stack is consumed by multiple rebuilds: ${group.current_group_id}`);
      consumedGroupIds.set(group.current_group_id, group.target_stack);
    }
    if (targetNames.has(group.target_stack)) errors.push(`Target stack is produced by multiple rebuilds: ${group.target_stack}`);
    targetNames.set(group.target_stack, group.current_group_id || group.target_kind);
  }

  const dispositions = new Map();
  const addDisposition = (id, kind) => {
    const number = Number(id);
    if (!dispositions.has(number)) dispositions.set(number, []);
    dispositions.get(number).push(kind);
  };
  for (const id of plan.keep_ungrouped) addDisposition(id, "keep_ungrouped");
  for (const item of plan.close) addDisposition(item.tab_id, "close");
  for (const item of plan.assign) addDisposition(item.tab_id, "assign");
  for (const id of plan.needs_confirmation) addDisposition(id, "needs_confirmation");
  const candidateIds = new Set(report.candidate_ids);
  for (const id of candidateIds) {
    const kinds = dispositions.get(id) || [];
    if (kinds.length !== 1) errors.push(`Candidate ${id} needs exactly one disposition; found ${kinds.join(", ") || "none"}`);
  }
  for (const [id, kinds] of dispositions) {
    if (!candidateIds.has(id)) errors.push(`Disposition references non-candidate tab ${id}`);
    if (kinds.length > 1) errors.push(`Tab ${id} has multiple dispositions: ${kinds.join(", ")}`);
  }
  for (const id of keepUngroupedIds) {
    const tab = tabsById.get(id);
    if (!tab) errors.push(`Ungrouped keeper is outside the scope or missing: ${id}`);
    else if (tab.groupTitle) errors.push(`Named-stack tab cannot be moved to the ungrouped inbox: ${id}`);
    if (assignmentIds.has(id) || closeIds.has(id)) errors.push(`Ungrouped keeper has a conflicting action: ${id}`);
  }

  return { ok: errors.length === 0, errors, audit: report, execution_groups: executionGroups, url_normalizations: urlNormalizations, close: plan.close, needs_confirmation: plan.needs_confirmation };
}

function bridgeRestarted(before, after) {
  const beforeId = before.bridge?.id;
  const afterId = after.bridge?.id;
  return Boolean(beforeId && afterId && beforeId !== afterId);
}

function resolveRestartedScope(after, beforeScope, fixedUrls) {
  const workspace = (after.workspaces || []).find((item) => String(item.id) === String(beforeScope.workspaceId));
  if (beforeScope.workspaceId != null && !workspace) return { error: `Workspace is absent after browser restart: ${beforeScope.workspaceId}` };
  const scoped = (after.tabs || []).filter((tab) => beforeScope.workspaceId == null
    ? tab.workspaceId == null
    : String(tab.workspaceId) === String(beforeScope.workspaceId));
  const byWindow = new Map();
  for (const tab of scoped) {
    const id = Number(tab.windowId);
    if (!byWindow.has(id)) byWindow.set(id, []);
    byWindow.get(id).push(tab);
  }
  const fixed = new Set(fixedUrls);
  let candidates = [...byWindow.entries()].filter(([, tabs]) => [...fixed].every((url) => tabs.some((tab) => tab.url === url)));
  if (!candidates.length && byWindow.size === 1) candidates = [...byWindow.entries()];
  if (candidates.length !== 1) return { error: `Cannot map window ${beforeScope.windowId} after browser restart` };
  const [windowId, tabs] = candidates[0];
  return { scope: { workspaceId: beforeScope.workspaceId, workspaceName: workspace?.name || beforeScope.workspaceName, windowId, tabs } };
}

function expectedGroup(tab, assignment, executionByTarget) {
  if (assignment) {
    const execution = executionByTarget.get(assignment.target_stack);
    return { grouped: true, title: assignment.target_stack, color: execution?.target_color || "" };
  }
  return { grouped: Boolean(tab.groupId), title: tab.groupTitle || "", color: tab.groupColor || "" };
}

function mapTabsAfterRestart(beforeScope, afterScope, plan, validated) {
  const closedIds = new Set(plan.close.map((item) => Number(item.tab_id)));
  const assignments = new Map(plan.assign.map((item) => [Number(item.tab_id), item]));
  const executionByTarget = new Map(validated.execution_groups.map((group) => [group.target_stack, group]));
  const normalizedUrls = new Map(validated.url_normalizations.map((item) => [Number(item.tab_id), item.to_url]));
  const expected = beforeScope.tabs.filter((tab) => !closedIds.has(Number(tab.id))).map((tab) => ({
    tab,
    url: normalizedUrls.get(Number(tab.id)) || tab.url,
    group: expectedGroup(tab, assignments.get(Number(tab.id)), executionByTarget),
  }));
  const afterByUrl = new Map();
  for (const tab of afterScope.tabs) {
    if (!afterByUrl.has(tab.url)) afterByUrl.set(tab.url, []);
    afterByUrl.get(tab.url).push(tab);
  }
  const expectedByUrl = new Map();
  for (const item of expected) {
    if (!expectedByUrl.has(item.url)) expectedByUrl.set(item.url, []);
    expectedByUrl.get(item.url).push(item);
  }
  const byBeforeId = new Map();
  const usedAfterIds = new Set();
  const missing = [];
  for (const [url, items] of expectedByUrl) {
    const actual = afterByUrl.get(url) || [];
    const adjacency = items.map((item) => actual.map((tab, index) => {
      const sameWorkspace = String(tab.workspaceId) === String(item.tab.workspaceId);
      const samePinned = Boolean(tab.pinned) === Boolean(item.tab.pinned);
      const sameGrouping = Boolean(tab.groupId) === item.group.grouped
        && (tab.groupTitle || "") === item.group.title
        && (tab.groupColor || "") === item.group.color;
      const keepsActive = !item.tab.active || tab.active;
      return sameWorkspace && samePinned && sameGrouping && keepsActive ? index : null;
    }).filter((index) => index != null));
    const actualMatch = new Array(actual.length).fill(-1);
    const order = items.map((_, index) => index).sort((left, right) => adjacency[left].length - adjacency[right].length);
    function assign(itemIndex, seen) {
      for (const actualIndex of adjacency[itemIndex]) {
        if (seen.has(actualIndex)) continue;
        seen.add(actualIndex);
        if (actualMatch[actualIndex] === -1 || assign(actualMatch[actualIndex], seen)) {
          actualMatch[actualIndex] = itemIndex;
          return true;
        }
      }
      return false;
    }
    for (const itemIndex of order) if (!assign(itemIndex, new Set())) missing.push(items[itemIndex].tab.id);
    for (let actualIndex = 0; actualIndex < actual.length; actualIndex += 1) {
      const itemIndex = actualMatch[actualIndex];
      if (itemIndex === -1) continue;
      byBeforeId.set(Number(items[itemIndex].tab.id), actual[actualIndex]);
      usedAfterIds.add(Number(actual[actualIndex].id));
    }
  }
  return { byBeforeId, missing, additions: afterScope.tabs.filter((tab) => !usedAfterIds.has(Number(tab.id))) };
}

function verify(beforeBundle, afterBundle, plan, selector, fixedUrls = [], windowId) {
  const beforeValidation = validateSnapshotBundle(beforeBundle);
  const afterValidation = validateSnapshotBundle(afterBundle);
  const runtimeIdsChanged = bridgeRestarted(beforeBundle.browser, afterBundle.browser);
  const bundleErrors = [...beforeValidation.errors.map((error) => `Before snapshot: ${error}`), ...afterValidation.errors.map((error) => `After snapshot: ${error}`), ...compareSnapshotConfiguration(beforeBundle, afterBundle, { allowRuntimeIdChanges: runtimeIdsChanged })];
  if (bundleErrors.length) return { ok: false, errors: bundleErrors };
  const before = beforeBundle.browser;
  const after = afterBundle.browser;
  const selectedWindowId = windowId ?? plan.window_id;
  const validated = validatePlan(before, plan, selector, fixedUrls, selectedWindowId);
  if (!validated.ok) return validated;
  const beforeScope = resolveScope(before, selector ?? plan.workspace, selectedWindowId);
  const restartedScope = runtimeIdsChanged ? resolveRestartedScope(after, beforeScope, fixedUrls) : null;
  if (restartedScope?.error) return { ok: false, errors: [restartedScope.error] };
  const afterScope = restartedScope?.scope || resolveScope(after, String(beforeScope.workspaceId ?? "window"), beforeScope.windowId);
  const beforeById = new Map(beforeScope.tabs.map((tab) => [tab.id, tab]));
  const closedIds = new Set(plan.close.map((item) => Number(item.tab_id)));
  const assignedIds = new Set(plan.assign.map((item) => Number(item.tab_id)));
  const normalizedUrls = new Map(validated.url_normalizations.map((item) => [Number(item.tab_id), item.to_url]));
  const renamedSourceNames = new Set(validated.execution_groups.filter((group) => group.target_kind === "renamed").map((group) => group.source_stack));
  const errors = [];
  const warnings = [];
  const restartedMapping = runtimeIdsChanged ? mapTabsAfterRestart(beforeScope, afterScope, plan, validated) : null;
  const afterById = restartedMapping?.byBeforeId || new Map(afterScope.tabs.map((tab) => [tab.id, tab]));

  if (!runtimeIdsChanged) for (const id of closedIds) if (afterById.has(id)) errors.push(`Closed tab still exists: ${id}`);
  for (const id of restartedMapping?.missing || []) errors.push(`Unexpected missing tab after browser restart: ${id}`);
  for (const [id, tab] of beforeById) {
    if (closedIds.has(id)) continue;
    const current = afterById.get(id);
    if (!current) { errors.push(`Unexpected missing tab: ${id}`); continue; }
    if (current.url !== tab.url && current.url !== normalizedUrls.get(id)) errors.push(`Tab URL changed unexpectedly: ${id}`);
    if (String(current.workspaceId) !== String(tab.workspaceId)) errors.push(`Tab changed Workspace: ${id}`);
    if (tab.pinned !== current.pinned) errors.push(`Pinned state changed: ${id}`);
    if (tab.active && !current.active) errors.push(`Active tab lost active state: ${id}`);
    if (tab.groupTitle && !assignedIds.has(id) && !renamedSourceNames.has(tab.groupTitle)) {
      if (current.groupTitle !== tab.groupTitle) errors.push(`Stable stack membership changed for tab ${id}: ${tab.groupTitle} -> ${current.groupTitle || "no stack"}`);
      if (current.groupColor !== tab.groupColor) errors.push(`Stable stack color changed for tab ${id}: ${tab.groupColor} -> ${current.groupColor}`);
    }
  }
  for (const item of validated.url_normalizations) {
    const keeper = afterById.get(Number(item.tab_id));
    if (keeper && keeper.url !== item.to_url) errors.push(`Same-MR keeper was not normalized to ${item.to_url}: ${item.tab_id}`);
  }
  for (const id of plan.keep_ungrouped.map(Number)) if (afterById.get(id)?.groupId) errors.push(`Tab should remain ungrouped: ${id}`);
  for (const item of plan.assign) {
    const current = afterById.get(Number(item.tab_id));
    if (!current) continue;
    if (current.groupTitle !== item.target_stack) errors.push(`Tab ${item.tab_id} landed in ${current.groupTitle || "no stack"}, expected ${item.target_stack}`);
  }
  for (const group of validated.execution_groups) {
    const members = group.complete_member_ids.map((id) => afterById.get(Number(id))).filter(Boolean);
    if (members.length !== group.complete_member_ids.length) continue;
    const groupIds = new Set(members.map((tab) => tab.groupId).filter(Boolean));
    if (groupIds.size !== 1) errors.push(`Target stack ${group.target_stack} was not rebuilt as one group`);
    if (members.some((tab) => tab.groupTitle !== group.target_stack)) errors.push(`Target stack name does not cover its complete member set: ${group.target_stack}`);
    if (members.some((tab) => tab.groupColor !== group.target_color)) errors.push(`Target stack color is wrong: ${group.target_stack}`);
    if (groupIds.size === 1) {
      const [groupId] = groupIds;
      const actualIds = afterScope.tabs.filter((tab) => tab.groupId === groupId).map((tab) => tab.id).sort((left, right) => left - right);
      const expectedIds = group.complete_member_ids.map((id) => Number(afterById.get(Number(id))?.id ?? id)).sort((left, right) => left - right);
      if (JSON.stringify(actualIds) !== JSON.stringify(expectedIds)) errors.push(`Target stack has unexpected members: ${group.target_stack}`);
    }
  }
  for (const item of plan.close) {
    if (!["exact_url_duplicate", "same_merge_request"].includes(item.reason)) continue;
    const keeper = afterById.get(Number(item.keep_tab_id));
    if (!keeper) errors.push(`Duplicate keeper is missing: ${item.keep_tab_id}`);
  }
  for (const stack of validated.audit.named_stacks) {
    if (renamedSourceNames.has(stack.name)) continue;
    const survivingIds = stack.member_ids.filter((id) => !closedIds.has(id));
    const survivors = survivingIds.map((id) => afterById.get(Number(id))).filter(Boolean);
    if (survivors.length !== survivingIds.length || survivors.length === 0) continue;
    const groupIds = new Set(survivors.map((tab) => tab.groupId).filter(Boolean));
    if (groupIds.size !== 1) errors.push(`Stable stack was split: ${stack.name}`);
    if (survivors.some((tab) => tab.groupTitle !== stack.name || tab.groupColor !== stack.color)) errors.push(`Stable stack identity changed: ${stack.name}`);
  }

  const confirmationIds = new Set(plan.needs_confirmation.map(Number));
  for (const id of confirmationIds) {
    const previous = beforeById.get(id);
    const current = afterById.get(id);
    if (!previous || !current) continue;
    const groupingChanged = runtimeIdsChanged
      ? Boolean(current.groupId) !== Boolean(previous.groupId) || current.groupTitle !== previous.groupTitle || current.groupColor !== previous.groupColor
      : current.groupId !== previous.groupId || current.groupTitle !== previous.groupTitle || current.groupColor !== previous.groupColor;
    if (groupingChanged) {
      errors.push(`Needs-confirmation tab changed grouping: ${id}`);
    }
  }
  const unnamedTabs = afterScope.tabs.filter((tab) => tab.groupId && !String(tab.groupTitle || "").trim());
  const currentConfirmationIds = new Set([...confirmationIds].map((id) => afterById.get(id)?.id).filter((id) => id != null));
  for (const tab of unnamedTabs) if (!currentConfirmationIds.has(tab.id)) errors.push(`Unexpected unnamed-stack member remains: ${tab.id}`);
  const additions = restartedMapping?.additions || afterScope.tabs.filter((tab) => !beforeById.has(tab.id));
  const exactClosedUrls = new Set(plan.close.filter((item) => item.reason === "exact_url_duplicate").map((item) => beforeById.get(Number(item.tab_id))?.url).filter(Boolean));
  const sameMrClosedIdentities = new Set(plan.close.filter((item) => item.reason === "same_merge_request").map((item) => codebaseMergeRequest(beforeById.get(Number(item.tab_id))?.url)?.identity).filter(Boolean));
  for (const tab of additions) {
    const mergeRequest = codebaseMergeRequest(tab.url);
    if (exactClosedUrls.has(tab.url) || (mergeRequest && sameMrClosedIdentities.has(mergeRequest.identity))) {
      errors.push(`Closed duplicate identity still has an unexpected copy: ${tab.url}`);
    }
  }
  const newIds = additions.map((tab) => tab.id);
  const expectedCount = beforeScope.tabs.length - closedIds.size + newIds.length;
  if (afterScope.tabs.length !== expectedCount) errors.push(`Tab count does not reconcile: expected ${expectedCount}, found ${afterScope.tabs.length}`);
  if (newIds.length) warnings.push(`Concurrent additions: ${newIds.join(", ")}`);
  if (runtimeIdsChanged) warnings.push(`Browser restart remapped ${afterById.size} surviving tabs to new runtime IDs`);

  return { ok: errors.length === 0, errors, warnings, totals: { before: beforeScope.tabs.length, closed: closedIds.size, concurrent_additions: newIds.length, after: afterScope.tabs.length }, unnamed_tab_ids: unnamedTabs.map((tab) => tab.id), runtime_ids_remapped: runtimeIdsChanged };
}

const argv = process.argv.slice(2);
if (!argv.length || argv[0] === "--help" || argv[0] === "-h") {
  process.stdout.write(USAGE);
  process.exit(0);
}
const args = parseArgs(argv);
const fixedUrls = Array.isArray(args["fixed-url"]) ? args["fixed-url"] : args["fixed-url"] ? [args["fixed-url"]] : [];
if (!fixedUrls.length) die("At least one --fixed-url is required");
let result;
if (args.command === "audit") {
  if (!args.snapshot) die("audit requires --snapshot");
  result = audit(loadJson(args.snapshot), args.workspace, fixedUrls, args["window-id"]);
} else if (args.command === "validate") {
  if (!args.snapshot || !args.plan) die("validate requires --snapshot and --plan");
  result = validatePlan(loadJson(args.snapshot), loadPlan(args.plan), args.workspace, fixedUrls, args["window-id"]);
} else if (args.command === "verify") {
  if (!args.before || !args.after || !args.plan) die("verify requires --before, --after, and --plan");
  try {
    result = verify(loadSnapshotBundle(args.before), loadSnapshotBundle(args.after), loadPlan(args.plan), args.workspace, fixedUrls, args["window-id"]);
  } catch (error) {
    die(`Cannot read full snapshot bundle: ${error.message}`);
  }
} else {
  die("Usage: tidy-plan.mjs audit|validate|verify ...");
}
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
if (result.ok === false) process.exit(1);
