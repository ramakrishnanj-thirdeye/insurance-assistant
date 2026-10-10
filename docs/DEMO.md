# Demo run-of-show

About 10 minutes on the core path, plus optional extras when time and interest allow. Every chat step below is
also a `make demo-check` step (ids S01–S14), so the run-of-show is rehearsed headlessly before each demo.

**Measured** is the wall time `make demo-check` recorded for the step on the local profile (qwen3:8b on the
demo laptop, models warm, 2026-10-10, two passes: core path 183 s and 163 s of model time, all 14 steps passed
both times). **Slot** is the time to budget on stage, including talking and opening the trace.

## Before the audience arrives
1. Work through the demo-machine checklist at the end of this file.
2. `make demo`: warms qwen3:8b with `keep_alive: 30m`, starts the API without `--reload`, starts the UI and
   opens http://localhost:8501.
3. In a second terminal, `make demo-check`: it must report 14 of 14. It deletes its own threads afterwards.
4. Leave the browser on the Chat page, persona **customer**, customer **CUST139920 · CLM300210 · Approved**.

## Run-of-show

| # | Core | Persona | Ask or do | Expected outcome | Show | Measured | Slot | Fallback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 (S01) | core | customer CUST139920 | `Hello` | The greeting template, instantly | Trace: **Answered by: template (no LLM)**, no model call in the steps | 0.1 s | 0:30 | None needed: no model involved |
| 2 (S02) | core | customer | `What is the status of my claim CLM300210?` | "Claim CLM300210 is **Approved** …", cited `[claims:CLM300210]` | Trace: plain steps ("Looked up claim CLM300210"), the named answer checks (V1 Citations are real … V7 Grounded: skipped (eval only) on the local profile), template (no LLM) | 0.3 s | 0:45 | Re-ask; the fast path needs no model |
| 3 (S03) | core | customer | `What is the status of claim CLM327142?` | "I can only share details of policies and claims linked to your own account." | Access control lives in code (personas.yaml), not in the prompt | 0.1 s | 0:30 | None needed: a deterministic refusal |
| 4 (S04) | core | customer | `Can you guarantee my claim CLM311320 will be approved?` | No promise. The mandated wording "Final decision depends on complete claim assessment.", a `§15` citation, and what CLM311320 still needs (Pending Documents) | Check **V4 No promises** passed; the streamed draft never shows a promise | 63 s / 49 s | 1:30 | While it runs, explain the no-guarantee rule. If it stalls, open the Claim Dossier for CLM311320 to show the needs |
| 5 (S05) | core | claims_agent | `What is the maternity waiting period under Health Secure Plus?` | 24 months, cited `[Health Secure Plus §5 Maternity]`; the draft streams in grey with "checking…", then "✓ verified" | Streaming, then the trace: clauses retrieved (fused rank, rerank score), the checks | 26 s / 25 s | 1:00 | Re-ask. If the model is cold, keep talking through the trace of step 2 |
| 6 (S06) | core | claims_agent | `Is drunk driving covered under Motor Protect Comprehensive?` | No: the intoxication exclusion, cited `[Motor Protect Comprehensive §9 Exclusions]` | The wording says "intoxication", not "drunk driving": the glossary bridges it | 18 s / 17 s | 0:45 | Re-ask with "intoxication" |
| 7 (S07) | core | claims_agent | `Analyze claim CLM300210`, then **Approve** with the note `Hospital confirmed the admission by phone` | A review card: counts, 2 blockers (one is the claim date outside the policy period), escalation reasons, next best actions; after Approve, "Reviewer decision: **approve**" with the note | Human in the loop: the graph pauses and resumes from its checkpoint | 36 s / 36 s | 1:30 | If the card does not appear, open the Claim Dossier for CLM300210 (step 9), which has the same findings |
| 8 (S11) | core | supervisor | `Show the approval rate by line of business as a chart` | A bar chart per policy type, the result table and the validated SQL | SQL in the expander; the query passed the validator (read-only, allow-listed tables) | 39 s / 36 s | 1:00 | Re-ask. If the SQL fails twice, the answer falls back to the table with its `[sql:…]` citation |
| 9 (S13) | core | claims_agent or supervisor | **Claim Dossier** page, claim `CLM300210`, **Load** | Header: Approved ₹64,577 next to expected payable ₹58,119, with the note "₹6,458 above the expected payable (co-pay 10%)"; red blocker badges with plain messages; 4 missing and 2 pending documents; next best actions; as supervisor the consistency flag C1 "Paid despite blockers" | The co-pay leakage at a glance; the rules come from config/rules.yaml, not the model | 0.1 s | 1:30 | Deterministic: no model involved |
| 10 (S14) | core | claims_agent or supervisor | **Eval Dashboard** page, newest run | Metrics against targets with "k of n" and intervals; open gates; the calibration story (below); the retrieval ablation A–E | See "Calibration story" | 0.1 s | 1:30 | Open `eval/reports/baseline.md` |
| 11 (S08) | optional | claims_agent | `Why is CLM300210 pending?` | "CLM300210 is Approved, not pending", then the explanation; no review pause | A false premise corrected from the data | 37 s / 36 s | 1:00 | Skip |
| 12 (S09) | optional | claims_agent | `Give me a summary of claim CLM300423` | A summary of a clean claim: "0 blockers; doesn't need human review", no pause | Explain mode never pauses | 22 s / 21 s | 0:45 | Skip |
| 13 (S10) | optional | claims_agent | `Are vet bills for my pet dog covered?` | The abstention template "The policy documents don't address this directly …" with the closest clause; no model-written verdict | The confidence gate: low retrieval confidence means no answer is invented | 7 s / 7 s | 0:30 | Skip |
| 14 (S12) | optional | supervisor | `How many claims were paid in full despite a co-pay?` | 20,903 claims, cited `[sql:…]` | Leakage found with one question | 22 s / 21 s | 0:45 | Skip |
| 15 | optional | claims_agent | Claim Dossier, **Add narrative** | The narrative, the cited clauses (expanders) and a customer message draft with a copy button | The model writes prose only around deterministic findings | not measured | 1:00 | Skip; the deterministic dossier already tells the story |
| 16 | optional | Claude Desktop | `What is the status of CLM300210?` with the README MCP config | The same answer through the MCP server | The tools are reusable outside the app (AC-05-09) | manual | 1:00 | Skip |

Core path: 10 steps, about 10½ minutes. Optional extras: about 5 minutes.

## Calibration story (step 10)
- The correctness judge (llama3.1:8b) agrees with a human on **6 of 10** answers, below the 80% bar. So
  correctness and faithfulness are shown as **advisory**, not gated: we do not let an uncalibrated judge
  pass or fail the build.
- Human-verified correctness on the same sample: **8 of 10**.
- V7 (groundedness) precision: **3 of 7** flags were real. After the claim-splitter fix, 3 of those flags no
  longer reach the judge, and precision over the rest is **3 of 4**.
- Open gates are listed, not hidden: analytics exec_accuracy 10 of 15 on qwen3:8b (target 0.90). The plan is
  to re-measure on the api-lite profile once an API key exists.

## If something goes wrong
- **First answer very slow:** the model was not warm. `make demo` warms it; re-run the warm-up by restarting
  `make demo`, or ask a short question first.
- **"Cannot reach the API":** the API stopped. Restart `make demo`. If it says something already answers on
  port 8000, clean up the port (checklist below).
- **A model answer goes wrong live:** say so; open the trace to show which check caught it, or move to the
  deterministic Claim Dossier page.

## Demo-machine checklist
- [ ] Laptop plugged in; Windows power mode **Best performance**.
- [ ] Power-throttling exemptions for Python and Ollama (from an elevated prompt):
      `powercfg /powerthrottling disable /path "<path to python.exe in .venv>"`, and the same for `ollama.exe`.
- [ ] Ollama running. `make demo` sends a warm-up request with `keep_alive: 30m`. Check the GPU/CPU split with
      `ollama ps` at `num_ctx` 8192 (36% CPU / 64% GPU on 2026-10-06; less CPU is faster).
- [ ] The API runs **without `--reload`** (`make demo` does this; `make api` is for development).
- [ ] `INSURAI__LLM__PROFILE=local` in `.env` until an Anthropic API key exists.
- [ ] Port 8000 free. A stale API: PowerShell
      `Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess`, then
      `Stop-Process -Id <pid>`; Git Bash `netstat -ano | findstr :8000`, then `taskkill /PID <pid> /F`.
- [ ] Stop `make demo`, `make api`, `make mcp` and `make ui` before `make data` or `make index` (Windows locks
      the DuckDB file and the Qdrant store).
- [ ] `make demo-check` reports 14 of 14, twice.
- [ ] Browser zoom so the trace tables fit; notifications off.
