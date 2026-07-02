#!/usr/bin/env bash
# 看上游自上次同步以来改了什么。只"看"，不自动吸收。
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git fetch upstream --quiet

echo "== 上游新提交 (main..upstream/main) =="
git log --oneline main..upstream/main || echo "(无)"
echo
echo "== 变更文件（仅 skills/）=="
git diff --stat main upstream/main -- skills/ || echo "(无)"
echo
cat <<'TIPS'
下一步（都在 mine 分支上做）：
  看某个 skill 具体改动:   git diff main upstream/main -- skills/engineering/tdd/
  只接某一笔改动:          git cherry-pick <sha>
  接完后推进参考指针:      git checkout main && git merge --ff-only upstream/main && git checkout mine
铁律：永远不要 git merge upstream/main 到 mine —— 那会把你删掉的、不想要的全带回来。
TIPS
