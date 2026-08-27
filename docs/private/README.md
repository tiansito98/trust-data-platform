# docs/private — never pushed to GitHub

**This repo is public.** Anything you drop in this folder stays on your machine:
`.gitignore` excludes the whole directory and tracks only this README, so the folder
exists on a fresh clone and the rule is visible instead of tribal knowledge.

## What belongs here

- Personal data of identifiable people: employee names, commissions, salaries,
  performance reviews, anything HR.
- Exports with internal figures we don't want public: revenue by branch, COBRA
  reconciliations, commercial targets.
- Sixt documents covered by the datashare agreement.
- Customer data: names, ID numbers, payment details.

## What does not

Ordinary technical documentation — architecture, data dictionaries, runbooks,
coding style. That lives in `docs/` and is versioned as usual.

## How to use it

Save the file here and you're done. To confirm git is ignoring it:

```powershell
git check-ignore -v docs/private/your_file.xlsx
```

If it prints the rule that blocks the file, you're fine. If it prints nothing, git
will push it — fix `.gitignore` before committing.

## Why this folder exists

On 2026-08-26 two commission-audit spreadsheets were pushed to `main` carrying
advisor names alongside their individual compensation. They were public for roughly
19 hours. They were removed on 2026-08-27, but they remain in git history: taking a
file out of the working tree does not erase it from earlier commits.

**If something sensitive does get pushed, flag it immediately.** Removing it for real
means rewriting history (`git filter-repo`) and force-pushing, which has to be
coordinated with the DigitalOcean runner that pushes daily.
