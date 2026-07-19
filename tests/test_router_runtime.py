import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "router_runtime", ROOT / "scripts" / "router_runtime.py"
)
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def current(model, effort):
    return {
        "status": "verified", "thread_id": "019f6001-95ae-7411-a5ba-7895a1897e49",
        "model": model, "effort": effort, "source": "test", "reason": None,
    }


def segment():
    return {
        "segment_id": "docs", "goal": "Update docs", "task_kind": "mechanical",
        "risk": "low", "size": "tiny", "acceptance": ["Docs updated"],
        "validation_budget": "Diff check",
    }


class RouterRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.temp.name) / "ledger.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **values):
        return SimpleNamespace(
            ledger=self.ledger, sessions_root=None, no_runtime_detection=True, **values
        )

    def envelope(self, plan):
        selected = plan["segments"][0]
        return {
            "plan": plan, "route_id": plan["route_id"],
            "segment_id": selected["segment_id"], "attempt_id": selected["attempt_id"],
        }

    def test_fast_local_begin_skips_claim_and_returns_capsule(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-luna", "low")
        )
        output = io.StringIO()
        with redirect_stdout(output):
            RUNTIME.begin(self.args(envelope_json=json.dumps(self.envelope(plan))))
        result = json.loads(output.getvalue())
        self.assertFalse(result["claim_required"])
        self.assertIsNone(result["claimed"])
        self.assertNotIn("segments", result["context_capsule"])
        self.assertFalse(self.ledger.exists())

    def test_fast_switch_claims_once_and_blocks_replay(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-sol", "high")
        )
        encoded = json.dumps(self.envelope(plan))
        with redirect_stdout(io.StringIO()):
            RUNTIME.begin(self.args(envelope_json=encoded))
        with self.assertRaisesRegex(SystemExit, "already claimed"):
            RUNTIME.begin(self.args(envelope_json=encoded))
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual([item["event"] for item in events], [
            "segment_claim", "routing_efficiency",
        ])
        self.assertEqual(events[-1]["state_gate"], "stopped")

    def test_finish_records_verified_result_metrics_and_restore(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-sol", "medium")
        )
        result = {
            "plan": plan, "segment_id": "docs", "outcome": "completed",
            "task_class": "docs", "verification": "deterministic",
            "source": "user-confirmed", "actual_model": "gpt-5.6-luna",
            "actual_effort": "low",
            "metrics": {
                "source": "task-metadata", "routing_seconds": 0.5,
                "tool_round_trips": 2, "state_gate": "passed",
            },
        }
        output = io.StringIO()
        with redirect_stdout(output):
            RUNTIME.finish(self.args(result_json=json.dumps(result)))
        finished = json.loads(output.getvalue())
        self.assertTrue(finished["execution_recorded"])
        self.assertTrue(finished["metrics_recorded"])
        self.assertEqual(finished["next"]["action"], "restore")
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual([item["event"] for item in events], [
            "execution", "routing_efficiency",
        ])

    def test_finish_rejects_mutated_plan_before_recording(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-sol", "medium")
        )
        plan["segments"][0]["goal"] = "Forged"
        result = {
            "plan": plan, "segment_id": "docs", "outcome": "completed",
            "source": "user-confirmed", "actual_model": "gpt-5.6-luna",
            "actual_effort": "low",
        }
        with self.assertRaisesRegex(SystemExit, "hash mismatch"):
            RUNTIME.finish(self.args(result_json=json.dumps(result)))
        self.assertFalse(self.ledger.exists())


if __name__ == "__main__":
    unittest.main()
