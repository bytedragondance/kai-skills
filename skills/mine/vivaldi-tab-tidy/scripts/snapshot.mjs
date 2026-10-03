#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { loadSnapshotBundle, SNAPSHOT_FILES, validateSnapshotBundle } from "./snapshot-data.mjs";

const COMMANDS = [
  ["browser-snapshot.json", ["browser", "snapshot"]],
  ["stacks.json", ["stack", "list"]],
  ["workspaces.json", ["workspace", "list"]],
  ["workspace-rules.json", ["workspace", "rule", "list"]],
];
const USAGE = `@USAGE snapshot.mjs

BRIEF: Capture and validate four Vivaldi state views in a private Git ref.

SYNTAX:
  snapshot.mjs --phase PHASE [--repo PATH] [--output-dir PATH]
  snapshot.mjs --phase PHASE --source-dir PATH [--repo PATH] [--output-dir PATH] [--ref REF]

EXAMPLES:
  node snapshot.mjs --phase pre-tidy --repo /path/to/repo
  node snapshot.mjs --phase post-tidy --repo /path/to/repo
  node snapshot.mjs --phase test --source-dir /tmp/fixture --repo /tmp/repo --ref refs/vivaldi-snapshots/test
`;

function die(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith("--")) die(`Unexpected argument: ${key}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) die(`Missing value for ${key}`);
    result[key.slice(2)] = value;
    index += 1;
  }
  return result;
}

function run(command, args, options = {}) {
  return execFileSync(command, args, { encoding: "utf8", ...options }).trim();
}

function localStamp(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function capture(outputDir) {
  for (const [filename, command] of COMMANDS) {
    const output = run("vivaldi-agent", command);
    JSON.parse(output);
    writeFileSync(join(outputDir, filename), `${output}\n`, { mode: 0o600 });
  }
}

function copySource(sourceDir, outputDir) {
  for (const filename of SNAPSHOT_FILES) {
    const source = join(sourceDir, filename);
    if (!existsSync(source)) die(`Missing snapshot input: ${source}`);
    const value = readFileSync(source, "utf8");
    JSON.parse(value);
    writeFileSync(join(outputDir, filename), value.endsWith("\n") ? value : `${value}\n`, { mode: 0o600 });
  }
}

function validateSnapshot(outputDir) {
  const result = validateSnapshotBundle(loadSnapshotBundle(outputDir));
  if (result.errors.length) die(result.errors.join("; "));
  return result.totals;
}

function git(repo, args, options = {}) {
  return run("git", ["-C", repo, ...args], options);
}

function optionalGit(repo, args) {
  try { return git(repo, args); }
  catch (error) {
    if (error.status === 1) return "";
    throw error;
  }
}

function writeRef(repo, outputDir, ref, message) {
  try {
    git(repo, ["show-ref", "--verify", "--quiet", ref]);
    die(`Snapshot ref already exists: ${ref}`);
  } catch (error) {
    if (error.status !== 1) throw error;
  }

  const entries = SNAPSHOT_FILES.map((filename) => {
    const oid = git(repo, ["hash-object", "-w", join(outputDir, filename)]);
    return `100644 blob ${oid}\t${filename}`;
  }).join("\n");
  const tree = git(repo, ["mktree"], { input: `${entries}\n` });
  const parent = optionalGit(repo, ["for-each-ref", "--sort=-creatordate", "--count=1", "--format=%(objectname)", "refs/vivaldi-snapshots"]);

  const configuredName = optionalGit(repo, ["config", "--get", "user.name"]);
  const configuredEmail = optionalGit(repo, ["config", "--get", "user.email"]);
  const env = {
    ...process.env,
    GIT_AUTHOR_NAME: configuredName || "Vivaldi Snapshot",
    GIT_AUTHOR_EMAIL: configuredEmail || "vivaldi-snapshot@localhost",
    GIT_COMMITTER_NAME: configuredName || "Vivaldi Snapshot",
    GIT_COMMITTER_EMAIL: configuredEmail || "vivaldi-snapshot@localhost",
  };
  const args = ["commit-tree", tree];
  if (parent) args.push("-p", parent);
  const commit = git(repo, args, { input: `${message}\n`, env });
  git(repo, ["update-ref", ref, commit, "0000000000000000000000000000000000000000"]);
  for (const filename of SNAPSHOT_FILES) git(repo, ["cat-file", "-e", `${ref}:${filename}`]);
  return commit;
}

const argv = process.argv.slice(2);
if (!argv.length || argv.includes("--help") || argv.includes("-h")) {
  process.stdout.write(USAGE);
  process.exit(0);
}
const args = parseArgs(argv);
const phase = args.phase;
if (!phase || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(phase)) die("--phase must be a lowercase kebab-case label such as pre-tidy");

let repo;
try {
  repo = run("git", ["-C", resolve(args.repo || process.cwd()), "rev-parse", "--show-toplevel"]);
} catch {
  die("--repo must point inside a Git repository");
}
const outputDir = resolve(args["output-dir"] || mkdtempSync(join(tmpdir(), "vivaldi-snapshot-")));
mkdirSync(outputDir, { recursive: true, mode: 0o700 });
chmodSync(outputDir, 0o700);
for (const filename of SNAPSHOT_FILES) {
  const target = join(outputDir, filename);
  if (existsSync(target)) die(`Refusing to overwrite snapshot file: ${target}`);
}
if (args["source-dir"]) copySource(resolve(args["source-dir"]), outputDir);
else capture(outputDir);
const totals = validateSnapshot(outputDir);
const ref = args.ref || `refs/vivaldi-snapshots/${localStamp()}-${phase}`;
if (!/^refs\/vivaldi-snapshots\/[A-Za-z0-9._/-]+$/.test(ref)) die(`Invalid snapshot ref: ${ref}`);
try { git(repo, ["check-ref-format", ref]); }
catch { die(`Invalid snapshot ref: ${ref}`); }
const message = `Vivaldi ${phase} snapshot (${totals.tabs} tabs, ${totals.stacks} stacks, ${totals.workspaces} workspaces)`;
let commit;
try {
  commit = writeRef(repo, outputDir, ref, message);
} catch (error) {
  die(`Could not create the state-snapshot ref; do not mutate Vivaldi. Captured files remain at ${outputDir}. ${error.message}`);
}
process.stdout.write(`${JSON.stringify({ ref, commit, output_dir: outputDir, totals }, null, 2)}\n`);
