#!/usr/bin/env bash
set -euo pipefail

message=$1
shift
: "${TARGET_BRANCH:?TARGET_BRANCH is required}"
git check-ref-format "refs/heads/$TARGET_BRANCH"
git config user.name github-actions
git config user.email github-actions@users.noreply.github.com
# 仅暂存调用方明确指定的文件。
git add -- "$@"
if git diff --cached --quiet -- "$@"; then
  echo '没有需要保存的变更，跳过提交'
  exit 0
fi
git commit -m "$message" -- "$@"
# 共享 concurrency 负责工作流互斥；fetch/rebase 兼容期间发生的其他提交。
for attempt in 1 2 3; do
  git fetch origin "refs/heads/$TARGET_BRANCH"
  if ! git rebase FETCH_HEAD; then
    git rebase --abort
    echo '远端变更与本次保存冲突，停止推送以免覆盖数据' >&2
    exit 1
  fi
  if git push origin "HEAD:refs/heads/$TARGET_BRANCH"; then
    exit 0
  fi
  echo "推送失败，重新获取远端后重试（$attempt/3）" >&2
done
exit 1
