import re
import unittest

from app.core.capability_manifest import (
    UPSTREAM_CAPABILITIES,
    capability_command_catalog,
    capability_implementation_report,
)
from app.core.provenance import load_upstream_sources


class UpstreamProvenanceTests(unittest.TestCase):
    def test_all_requested_sources_have_pinned_license_and_capability_provenance(self):
        records = load_upstream_sources()
        by_id = {record.id: record for record in records}

        self.assertEqual(len(records), 13)
        self.assertEqual(set(by_id), {source["id"] for source in UPSTREAM_CAPABILITIES})
        self.assertTrue(all(re.fullmatch(r"[a-f0-9]{40}", record.reviewed_commit) for record in records))
        self.assertTrue(all(record.license_observation and record.code_treatment for record in records))
        self.assertTrue(all(record.capability_ids for record in records))
        self.assertTrue(all(
            len(by_id[source["id"]].capability_ids) == len(source["capabilities"])
            for source in UPSTREAM_CAPABILITIES
        ))

    def test_implementation_report_includes_revision_and_license_treatment(self):
        report = capability_implementation_report()
        self.assertTrue(all(row["reviewed_commit"] for row in report))
        self.assertTrue(all(row["license_observation"] for row in report))
        self.assertTrue(all(row["code_treatment"] for row in report))

    def test_every_capability_has_exact_non_round_robin_evidence(self):
        report = capability_implementation_report()
        expected_total = sum(len(source["capabilities"]) for source in UPSTREAM_CAPABILITIES)
        commands = capability_command_catalog()

        self.assertEqual(len(commands), expected_total)
        for source, row in zip(UPSTREAM_CAPABILITIES, report, strict=True):
            implementations = row["implementations"]
            self.assertEqual(
                [item["capability"] for item in implementations],
                source["capabilities"],
            )
            self.assertTrue(all(item["evidence"] for item in implementations))
            self.assertTrue(all(
                item["implementation_status"] in {"implemented", "provider-dependent", "interchange-only"}
                for item in implementations
            ))
