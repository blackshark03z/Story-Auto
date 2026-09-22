from __future__ import annotations

import json
import unittest
from pathlib import Path

from story_auto.providers.flow.rpc_contract import (
    QUALIFIED_BASELINE_FINGERPRINT,
    ContractError,
    build_catalog,
    build_media,
    build_upload,
    build_video,
    catalog_records,
    match_output,
    parse_rpc,
    sanitize_session,
    validate_session,
)

PROJECT = "11111111-2222-3333-4444-555555555555"
REFERENCE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OUTPUT = "99999999-8888-7777-6666-555555555555"
REQUEST = "12345678-1234-1234-1234-123456789abc"
PROMPT = "Exact causal marker ABC-123"


def framed(*values):
    return ")]}'\n" + "\n".join(json.dumps(value) for value in values)


def catalog_wire(rows):
    auxiliary = ['id',None,None,['name',[1,2],None,None,'type',None,[1,2]],'id2']
    model = ['model',1,'label',['id']+[None]*9+[[['id','label',True,'value']]]]
    payload = [None, [auxiliary] * len(rows) if rows else None, rows or None,
               [model]*30, None, None, None, [None, None, [[None,1,2,None,'type']]*2, None, 1]]
    return framed([["wrb.fr", "Zzl0ze", json.dumps(payload)]])


def record(identity=OUTPUT, *, project=PROJECT, prompt=PROMPT, reference=REFERENCE, model="abra_r2v_8s", length=8):
    captured = json.loads((Path(__file__).parent / "fixtures/flow_rpc_catalog_redacted.json").read_text())["record"]
    mapping = {"OUTPUT": identity, "PROJECT": project, "REFERENCE": reference, "MODEL": model, "PROMPT": prompt}
    def fill(value):
        return [fill(v) for v in value] if isinstance(value, list) else mapping.get(value, value) if isinstance(value, str) else value
    row = fill(captured)
    row[3] = "CAE"
    return row[:length]


class FlowRpcContractTests(unittest.TestCase):
    def test_builders_have_qualified_shapes(self):
        upload = json.loads(build_upload(PROJECT, b"png", "captcha", REQUEST))
        self.assertEqual(upload[0][0][0], "maseQ")
        self.assertEqual(json.loads(upload[0][0][1])[2], "image/png")
        video = json.loads(build_video(PROJECT, PROMPT, REFERENCE, "captcha", REQUEST))
        payload = json.loads(video[0][0][1])
        request = payload[0][0]
        self.assertEqual((request[2], request[3]), ("abra_r2v_8s", 2))
        self.assertEqual(request[1][0][1], REFERENCE)
        self.assertEqual(json.loads(build_catalog(PROJECT))[0][0][0], "Zzl0ze")
        self.assertEqual(json.loads(build_media(OUTPUT))[0][0][0], "as29s")

    def test_rpc_parser_rejects_multiple_target_frames_and_bad_payload(self):
        one = [["wrb.fr", "as29s", json.dumps(["ok"])]]
        self.assertEqual(parse_rpc(framed(one), "as29s"), ["ok"])
        with self.assertRaisesRegex(ContractError, "RPC_PAYLOAD_AMBIGUOUS"):
            parse_rpc(framed(one, one), "as29s")
        bad = [["wrb.fr", "as29s", "not-json"]]
        with self.assertRaisesRegex(ContractError, "WRB_PAYLOAD_JSON_INVALID"):
            parse_rpc(framed(bad), "as29s")

    def test_catalog_detects_drift_before_length_filter_and_no_collision_dedup(self):
        with self.assertRaisesRegex(ContractError, "CATALOG_RECORD_SHAPE_DRIFT"):
            catalog_records(catalog_wire([record(length=8) + ["drift"]]), PROJECT)
        duplicate = [record(), record()]
        with self.assertRaisesRegex(ContractError, "CATALOG_RECORD_IDENTITY_COLLISION"):
            catalog_records(catalog_wire(duplicate), PROJECT)

    def test_catalog_empty_and_populated_envelopes(self):
        self.assertEqual(catalog_records(catalog_wire([]), PROJECT), [])
        for rows in ([record()], [record(length=7)], [record(),record(identity=REFERENCE,length=7)]):
            self.assertEqual(catalog_records(catalog_wire(rows), PROJECT), rows)

    def test_unrecognized_or_wrong_project_does_not_become_empty(self):
        for wire in (framed([]), framed([["wrb.fr","other","null"]]),
                     framed([["wrb.fr","Zzl0ze","null"]]),
                     framed([["wrb.fr","Zzl0ze","[]"]]),
                     catalog_wire([record(project=REFERENCE)]),
                     catalog_wire([record()]) + '\n' + catalog_wire([record()]).split('\n',1)[1]):
            with self.subTest(wire=wire[:30]):
                with self.assertRaises(ContractError): catalog_records(wire, PROJECT)

    def test_catalog_aux_schema_drift_rejected(self):
        for slot, replacement in ((3,[42]),(3,[]),(7,[None]*5),(1,[None])):
            payload = parse_rpc(catalog_wire([record()]), 'Zzl0ze')
            payload[slot] = replacement
            wire = framed([["wrb.fr","Zzl0ze",json.dumps(payload)]])
            with self.subTest(slot=slot):
                with self.assertRaises(ContractError): catalog_records(wire,PROJECT)

    def test_match_requires_exact_prompt_reference_model_project_and_distinct_output(self):
        good = record()
        self.assertEqual(match_output([good], PROJECT, PROMPT, REFERENCE), good)
        self.assertIsNone(match_output([record(prompt=PROMPT + " extra")], PROJECT, PROMPT, REFERENCE))
        with self.assertRaisesRegex(ContractError, "OUTPUT_REFERENCE_MISMATCH"):
            match_output([record(reference=OUTPUT)], PROJECT, PROMPT, REFERENCE)
        with self.assertRaisesRegex(ContractError, "OUTPUT_MODEL_MISMATCH"):
            match_output([record(model="other")], PROJECT, PROMPT, REFERENCE)
        with self.assertRaisesRegex(ContractError, "CATALOG_RECORD_PROJECT_MISMATCH"):
            match_output([record(project="22222222-3333-4444-5555-666666666666")], PROJECT, PROMPT, REFERENCE)
        with self.assertRaisesRegex(ContractError, "OUTPUT_REFERENCE_NOT_DISTINCT"):
            match_output([record(identity=REFERENCE)], PROJECT, PROMPT, REFERENCE)

    def test_session_validation_sanitizes_and_rejects_bad_identity(self):
        meta = {"host": "flow.google.com", "source": f"/project/{PROJECT}", "at": "a" * 42,
                "sid": "secret", "bl": "secret", "hl": "en", "captcha": True}
        validate_session(meta, PROJECT)
        safe = sanitize_session(meta, PROJECT)
        self.assertEqual(safe["qualified_baseline_fingerprint"], QUALIFIED_BASELINE_FINGERPRINT)
        self.assertNotIn("secret", repr(safe))
        meta["source"] = "/project/not-this-one"
        with self.assertRaisesRegex(ContractError, "SESSION_PROJECT_MISMATCH"):
            validate_session(meta, PROJECT)

    def test_decoy_membership_and_unqualified_status_fail_closed(self):
        decoy = [OUTPUT, PROJECT, None, "CAE", [PROMPT, REFERENCE, "abra_r2v_8s"], None, None, None]
        with self.assertRaises(ContractError): match_output([decoy], PROJECT, PROMPT, REFERENCE)
        pending = record()
        pending[3] = "PENDING"
        with self.assertRaisesRegex(ContractError, "STATUS_UNQUALIFIED"):
            match_output([pending], PROJECT, PROMPT, REFERENCE)

    def test_runtime_catalog_baseline_drift_blocks(self):
        from story_auto.providers.flow.rpc_contract import validate_catalog_baseline
        meta = {"host": "flow.google.com", "source": f"/project/{PROJECT}", "at": "a"*42,
                "sid": "present", "bl": "present", "hl": "en", "captcha": True}
        for rows in ([],[record()],[record(length=7)],[record(), record(identity=REFERENCE,length=7)]):
            self.assertEqual(validate_catalog_baseline(meta, rows, PROJECT), QUALIFIED_BASELINE_FINGERPRINT)
        malformed = record()
        malformed[3] = 42
        with self.assertRaisesRegex(ContractError, "STATUS_INVALID"):
            validate_catalog_baseline(meta, [malformed], PROJECT)
        with self.assertRaisesRegex(ContractError, "SHAPE_DRIFT"):
            validate_catalog_baseline(meta, [record() + [None]], PROJECT)


if __name__ == "__main__":
    unittest.main()
