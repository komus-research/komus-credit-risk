# Codex Project Instructions

## Git Safety Rules

These rules are mandatory and must be followed before making any changes to the repository.

### 1. Check the current branch before starting

Before modifying any files, always check the current Git branch:

```bash
git branch --show-current
```

Do not modify project files until the current branch has been identified.

### 2. Never develop directly on `main`

The `main` branch is protected.

If the current branch is:

```text
main
```

do NOT:

* modify project files;
* create commits containing development changes;
* start implementing the requested feature;
* automatically create or switch to another branch.

Instead, stop and tell the user that they are currently on `main` and that development must happen in a separate branch.

Wait for the user to create or select the development branch.

### 3. Work only inside the current development branch

Once work starts on a non-`main` branch, treat that branch as the only branch available for development during the task.

Do NOT:

* switch to another branch;
* checkout another branch;
* modify another branch;
* commit to another branch;
* rebase onto another branch;
* cherry-pick commits into another branch;
* merge another branch;
* delete branches;
* rename branches;
* create additional branches unless explicitly requested by the user.

Commands such as the following must not be executed automatically:

```bash
git checkout <branch>
git switch <branch>
git switch -c <branch>
git checkout -b <branch>
git merge <branch>
git rebase <branch>
git cherry-pick <commit>
git branch -d <branch>
git branch -D <branch>
```

Reading Git metadata is allowed when necessary.

For example:

```bash
git status
git branch --show-current
git log
git diff
git diff --staged
```

### 4. Verify the Git state before making changes

Before starting development, inspect:

```bash
git branch --show-current
git status
```

Check for:

* the active branch;
* uncommitted changes;
* staged changes;
* untracked files.

Do not overwrite or discard existing user changes.

If existing changes may conflict with the requested work, stop and inform the user before proceeding.

### 5. Preserve the branch workflow

The expected workflow is:

```text
main
  │
  └── development branch
          │
          ├── development
          ├── testing
          └── completed work

                    ↓

              merge into main
              ONLY with explicit
              user approval
```

Development must happen on a separate branch created from `main`.

Do not bypass this workflow.

### 6. Commits

Commits may only be created on the active development branch.

Before committing, verify:

```bash
git branch --show-current
git status
git diff
```

Never commit development changes directly to `main`.

Do not amend, rewrite, squash, reset, or otherwise modify existing Git history unless the user explicitly requests it.

Never use destructive commands such as:

```bash
git reset --hard
git clean -fd
git push --force
git push --force-with-lease
```

unless the user explicitly requests the operation and its consequences have been explained.

### 7. Finishing development

When implementation is complete:

1. Verify the current branch.
2. Inspect `git status`.
3. Review the final diff.
4. Run the relevant tests/checks when available.
5. Report what was changed.
6. Tell the user whether the development branch appears ready to be merged.

Do NOT merge automatically.

### 8. Merging into `main` requires explicit approval

Merging into `main` is a protected action.

Never execute a merge into `main` merely because:

* implementation is complete;
* tests pass;
* the user previously said the feature should eventually be merged;
* merging appears to be the logical next step.

The user must explicitly approve the merge at that point.

Without explicit approval, stop after the development branch is ready.

Do NOT automatically execute:

```bash
git switch main
git checkout main
git merge <development-branch>
```

### 9. Merge procedure after approval

Only after the user explicitly approves merging the completed development branch into `main`:

1. Verify that the development branch is clean.
2. Verify that relevant tests/checks pass.
3. Identify the branch being merged.
4. Switch to `main`.
5. Check the state of `main`.
6. Merge the intended development branch into `main`.
7. Do not resolve unexpected merge conflicts by guessing.
8. If a merge conflict occurs, stop and explain the conflict to the user unless the resolution is trivial and explicitly authorized.
9. Verify the repository state after the merge.

Do not delete the development branch after merging unless the user explicitly asks for it.

### 10. Remote operations

Do not automatically push branches, tags, commits, or merges to a remote repository.

Commands such as:

```bash
git push
git push origin main
git push origin <branch>
git push --tags
```

require explicit user approval.

A local merge approval does not automatically imply approval to push the result to a remote repository.

### 11. Priority rule

When there is uncertainty about whether a Git operation may affect:

* `main`;
* another branch;
* Git history;
* remote repositories;
* existing user changes;

stop and ask the user before executing the operation.

Prefer preserving repository state over making assumptions.
