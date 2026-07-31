# Contributing

Thanks for improving Codex Auto Model Router.

## Share a routing result

Use the [routing feedback form](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=routing-feedback.yml) when a route was too strong, too weak, unnecessarily fragmented, or blocked. Include the visible routing notice, expected route, outcome, Codex surface, and version. Remove prompts, source code, credentials, paths, and personal data.

## Before opening a pull request

1. Keep routing recommendations evidence-based and model availability claims verifiable.
2. Preserve the separation between actual execution, analysis runs, and recommended allocation.
3. Do not add API keys, external model gateways, telemetry, prompts, source code, or conversation content to the usage ledger.
4. Keep Query and Record on the deterministic no-agent fast path.
5. Add or update tests for script and distribution changes.

Run:

```bash
python3 -m unittest discover -s tests -v
python3 tests/validate_distribution.py
```

Use a focused pull request and explain the behavior change, evidence, and compatibility impact. By contributing, you agree that your contribution is provided under this repository's MIT License.
