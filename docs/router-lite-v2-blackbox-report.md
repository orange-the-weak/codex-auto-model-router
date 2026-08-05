# Default routing path v2 Codex App black-box validation

> Historical evidence note: these measurements describe an earlier automatic-delegation design. The current Router still prefers direct tool concurrency, but uses the measured child-agent startup and lifecycle costs as priors for an automatic net-benefit gate. `--no-subagents` is the explicit opt-out; no extra permission prompt is required.

Date: 2026-08-03
Environment: Codex Desktop 0.146.0-alpha.9.2 on macOS

This test exercises the native Codex task interface. It does not simulate model dispatch with a local worker script. Token figures are derived from Codex session `token_count` events; non-cached input means `input_tokens - cached_input_tokens`.

## Results

| Scenario | Project-tool wait | Wall time | Result | Router errors shown | Extra non-cached input |
|---|---:|---:|---|---:|---:|
| Tiny SwiftUI copy edit, original Delegate behavior | 42.5 s | 51.6 s | Completed by local takeover | 0 | 5,469 |
| Tiny SwiftUI copy edit, startup-aware local path | 5.0 s | 5.4 s | Completed locally | 0 | 1,664 |
| Let Be Timer incremental build, install, and launch | 37.4 s | 128.7 s to launch | Build succeeded; app installed and visible | 0 Router errors | 36,340 |
| Three-source read-only research | 5.8 s to first dispatch | 85.2 s to two usable results; 223.4 s before cancelling one straggler | Two agents completed concurrently | 0 | 134,541 including all three agents |
| Deliberately invalid executor type | 8.5 s to local completion | 8.5 s | Coordinator took over | 1 deliberate scheduler rejection | 3,092 |

All four requested scenarios completed, so task completion was 4/4. Router decision/plan failures were 0/4. The only executor startup rejection was intentionally injected; valid executor starts were accepted without the old environment, ticket, hash, or ledger gates.

## Findings applied to v2

1. Tiny work must not pay an agent-startup tax. A tiny deterministic mechanical task now stays on the current verified GPT-5.6 route unless the user explicitly overrides it.
2. Deterministic tool-bound chains such as build/install can stay local for the same reason. The first iOS run proved the project chain, while the post-test policy check selected `tool-bound-local-fast-path` without another build.
3. A successful asynchronous agent start is not a failure merely because no result arrives within 15 seconds. The 15-second takeover applies only to explicit creation rejection or reported startup failure.
4. Parallel source research needs a straggler policy. The OpenAI and CursorBench agents finished in 68.5 s and 74.1 s, while the unresolved ChatBench agent consumed 65,879 non-cached input tokens before cancellation. The default path now marks results required or optional, stops optional stragglers after required acceptance passes, and permits only one alternate recovery attempt by default.
5. Cached input dominated the agent sessions and is intentionally not treated as equivalent to non-cached token cost.

## Scope and limits

- This is one real run per scenario, not a statistically controlled speed benchmark.
- The iOS scenario used exactly one incremental Debug build. A sandboxed Simulator call failed once and then succeeded with the approved host permission; this is an environment error, not a Router state failure.
- The research result demonstrates concurrent execution, not a serial speedup multiple. The useful completion boundary was two accepted sources; the third source exposed the long-tail failure mode that v2 now bounds.
- The current Codex process was already running when the updated Skill and presets were installed. Restart Codex before relying on the installed v2 behavior in other tasks.

## Local repository extension

The second pass used current files from three local repositories without modifying them: Let Be Timer, Snowboard Archive, and the Aliyun static/deployment repository.

| Scenario | Actual route | Project-tool wait | Wall time | Result | Extra non-cached input |
|---|---|---:|---:|---|---:|
| Let Be Timer AlarmKit localization-key check | Coordinator Sol/high, tiny local fast path | 5.3 s | 5.4 s | Key exists in both locales | 2,935 |
| Aliyun shell syntax check | Coordinator Sol/high, tool-bound local fast path | 5.7 s | 5.8 s | Both scripts passed `bash -n` | 1,371 |
| Three-repository parallel review | Sol/high coordinator + Luna/high + Luna/medium | 37.8 s to coordinator tool; 60–66 s to leaf tools | 161.3 s to all three results | 3/3 completed; no Router errors | 131,457 total |
| Isolated Snowboard gate review after capsule tightening | Luna/high | 49.6 s to leaf tool | 109.1 s | Same core findings from three raw files only | 30,827 total; 23,596 in leaf |

The first Snowboard leaf loaded global memory and used seven project-tool calls. The isolated retest treated the task capsule as self-contained, used exactly two allowed tool calls, did not access memory or the original repository, and independently reproduced the main findings. Leaf duration fell from 140.5 s to 101.2 s (28% lower), while leaf non-cached input fell from 50,747 to 23,596 tokens (54% lower).

This pass added two safeguards:

- direct task capsules are self-contained by default; global memory and unrelated history are excluded unless explicitly required;
- stop conditions, recovery counts, and validation budgets are hard limits, and automatic parallel candidates now default to at least 90 seconds because observed leaf startup-to-first-tool latency was about 38–40 seconds.

Across this extension, Router decision/plan failures were 0/4, requested tasks completed 6/6, and no state-machine, hash, environment-guard, ledger, Restore, or GPT-5.5 fallback message appeared.

## Cold-start-aware routing extension

A third pass tested the new delegation break-even and immediate-batch rules against current local repositories. These were native Codex agents and real repository reads, not local worker-script simulations.

| Test | Architecture | First project tool | Completion | Result |
|---|---|---:|---:|---|
| Let Be notification-category audit A | Luna/high leaf | 37.2 s after child start | 79.6 s | Correctly found no notification-category API use |
| Same core audit B | Sol/high coordinator local fast path | under 0.1 s command time | under 0.1 s command time | Same core zero-match conclusion with one `rg` |
| Snowboard health-gate leaf | Luna/high, immediate first spawn | 46.7 s after coordinator notice; 40.3 s after child start | 74.8 s child duration | Complete gate summary from two allowed files |
| Aliyun static-link leaf | Luna/medium, immediate second spawn | 53.5 s after coordinator notice; 38.9 s after child start | 78.2 s child duration | No broken internal links; one bounded command recovery |

The Let Be A/B isolates the architectural tax clearly: the delegated version spent 37.2 seconds before its first project tool and 79.6 seconds overall, while the coordinator reached the same required zero-match conclusion with one local command in under 0.1 seconds. This is a real same-task comparison, but only one run; it does not establish a universal multiplier or compare model quality on deeper work.

The back-to-back parallel dispatch started the first child 6.4 seconds after the compact notice and the second 14.5 seconds after it. The additional native spawn therefore added about 8.1 seconds even with no intervening reads, ledger work, or commentary. Child startup-to-first-tool remained 38.9–40.3 seconds, confirming that the Skill cannot remove the platform cold start. Compared with the earlier similar isolated traces, Snowboard child duration fell from 101.2 to 74.8 seconds and Aliyun from 92.3 to 78.2 seconds; scope and cache state were not perfectly controlled, so these are directional workflow improvements rather than formal speedup claims.

The applied policy now:

- keeps estimated sub-90-second work local only when the current verified GPT-5.6 route is a policy-accepted target or fallback;
- preserves delegation for a weaker current route, explicit override, high risk/consequence, or prior reasoning/verification failure;
- budgets 40 seconds of executor cold start, 10 seconds of initial dispatch, 8 seconds per additional spawn, and 10 seconds of aggregation;
- requires both 30 seconds and 15% estimated net benefit before parallelizing;
- dispatches selected tasks longest-first and labels every forecast as planning-only rather than measured speedup.

## Fresh versus reused executor probe

A fourth pass separated fresh task materialization from model/tool latency. Each condition used one fixed micro-task on Luna/medium, Luna/high, and Sol/high. The reused condition continued the exact completed executor task instead of creating another top-level task.

| Condition | Context ready | First tool | Final response |
|---|---:|---:|---:|
| Fresh Luna/medium | 31.6 s | 39.6 s | 41.0 s |
| Fresh Luna/high | 31.4 s | 35.5 s | 36.6 s |
| Fresh Sol/high | 31.4 s | 39.6 s | 44.5 s |
| Reused Luna/medium | 0.06 s | 2.7 s | 4.0 s |
| Reused Luna/high | 0.05 s | 2.7 s | 4.0 s |
| Reused Sol/high | 0.06 s | 9.4 s | 11.6 s |

Fresh context materialization was stable at 31.3–31.6 seconds across the three routes. Most of the old “40-second cold start” was therefore new-task context initialization, not model reasoning. Reusing the same executor inside the same user request removed that fixed delay; median time to first tool fell from 39.6 seconds to 2.7 seconds. This is still one run per route and does not establish a platform SLA.

The default path now models fresh and reused activation separately with conservative 40-second and 10-second priors. It may reuse an idle executor once only inside the same user request, with exact repository, model, effort, permission, sandbox, and ownership compatibility. Eligibility is checked again immediately before the follow-up. New requests, route changes, stale ownership, failed tasks, and sensitive external actions always use a fresh executor or stay local.

The implementation review itself then reused the existing Sol/high probe executor. The continued task reached context readiness in 0.06 seconds and its first repository tool in 7.0 seconds, providing a forward check of the chosen 10-second planning prior. A policy black-box pair also kept two fresh 90-second tasks serial (22-second estimated saving) while accepting two prequalified reused 90-second tasks (52-second estimated saving). Both figures remain planning estimates rather than measured end-to-end speedup.
