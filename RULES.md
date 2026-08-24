# Rules Ledger

Standing rules for work in this repo. Append new rules; do not silently rewrite
existing ones. Each rule records what it requires and why it exists.

---

## R1 — Verify before recommending

**Rule.** Do not recommend, flag, suggest, or assert anything that has not been
verified first. This covers claims about code behavior, files, packages,
versions, and whether something is broken.

**Required practice.**

- Check the actual source, run the command, or read the file *before* naming
  something as affected, suspect, or in need of a fix.
- Do not generalize from one confirmed case to a sibling case. Membership in the
  same commit, directory, naming convention, or feature is not evidence.
- When something genuinely cannot be verified in the current environment, say so
  explicitly and label it unverified. Do not present it as a finding.
- State how a claim was checked, so the verification can be judged.

**Why.** On 2026-08-24, xCopy.py was correctly diagnosed as having a real embed
bug (`min_w, min_h = self.master.minsize()` against a shim returning `None`).
xSync.py was then flagged as probably having "the same idiom" purely because it
was added to the embed map in the same commit, `c5e52a7`. A one-line grep showed
xSync.py never calls `minsize` or `maxsize` at all. The suggestion was noise, it
contradicted the user's own working observation that xSync embeds fine, and it
cost trust. The grep took seconds and should have come first.

**Applies to.** Every recommendation, not just code review. A follow-up task
proposed at the end of a turn is a recommendation and is covered by this rule.

---

## R2 — Staging vs deployment: never assume anything can be installed

**Environments.**

- **Staging** — Rocky Linux 8 VM under VMware (this machine,
  `/home/admin/Apps/xNAVSL`). Exists to mirror deployment. Packages may be
  installed here, but only with explicit confirmation, and every install is a
  deliberate divergence to be tracked.
- **Deployment** — RHEL 8, Dell PowerEdge R750. **Nothing may be installed.**
  Treat its package set as frozen and read-only.

**Rule.** Never propose a fix, tool, or workflow that requires installing
anything on deployment. Before installing on staging, state exactly which
packages would be added, which are hard dependencies, and confirm with the user
first.

**Required practice.**

- Code must run on the Python 2.7 + Tkinter that deployment already has. The
  standard library is the dependency budget; third-party packages are not
  available and cannot be added.
- Verify a module is stdlib before relying on it. Python 3 module names
  (`tkinter`, `queue`, `configparser`) are absent under 2.7 and must stay inside
  `try/except ImportError` fallbacks.
- When staging gains a package deployment lacks, say so plainly, because staging
  has stopped mirroring deployment in that respect.

**Why.** Staging exists to reproduce deployment faithfully. A fix that works on
staging because of a package deployment cannot have is not a fix; it is a
divergence that hides the failure until it reaches production.

---

## R3 — Do not modify core script behavior unless instructed

**Rule.** Do not change the core functionality of any script without an explicit
instruction to do so. This covers business logic, algorithms, UI construction,
data handling, and shared mechanisms other tools depend on.

**Required practice.**

- Permitted without asking: file permissions, and changes the user explicitly
  requested.
- Not permitted without asking: editing behavior, refactoring, "improving" code,
  or fixing a bug found in passing.
- A fix authorized for one script does not authorize editing a different file.
  If the true cause sits elsewhere, report it and get approval before touching
  that file.
- Report bugs found in passing. Do not fix them unprompted.

**Why.** These are production site scripts running on a frozen deployment
server. An unrequested change is unreviewed risk, and a fix applied to a shared
component affects every tool that depends on it, not just the one being
discussed.

---
