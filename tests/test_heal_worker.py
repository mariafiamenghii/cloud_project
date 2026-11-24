"""Unit tests for the purchase worker self-heal Lambda (no AWS access needed)."""

import os
import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from test_purchases import load_lambda

heal = load_lambda("heal_worker")

UUID = "11111111-2222-3333-4444-555555555555"
QUEUE_ARN = "arn:aws:sqs:us-east-1:123456789012:ticketing-purchase-queue"
WORKER = "ticketing-purchase-worker"
ENV = {
    "WORKER_FUNCTION_NAME": WORKER,
    "MAPPING_UUID": UUID,
    "QUEUE_ARN": QUEUE_ARN,
    "QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/ticketing-purchase-queue",
    "MAINTENANCE_PARAMETER": "/ticketing/purchase-worker/maintenance",
}


def denied(operation):
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, operation)


class HealWorkerTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.lam = MagicMock()
        self.lam.get_event_source_mapping.return_value = {
            "UUID": UUID, "State": "Disabled", "StateTransitionReason": "USER_INITIATED",
            "EventSourceArn": QUEUE_ARN,
            "FunctionArn": f"arn:aws:lambda:us-east-1:123456789012:function:{WORKER}",
        }
        self.lam.get_function_configuration.return_value = {"Role": "arn:aws:iam::123456789012:role/LabRole"}
        self.lam.update_event_source_mapping.return_value = {"State": "Enabling"}
        self.ssm = MagicMock()
        self.ssm.get_parameter.return_value = {"Parameter": {"Value": "off"}}
        self.sqs = MagicMock()
        self.sqs.get_queue_attributes.return_value = {"Attributes": {"ApproximateNumberOfMessages": "17"}}
        self.sts = MagicMock()
        self.sts.get_caller_identity.return_value = {
            "Arn": "arn:aws:sts::123456789012:assumed-role/LabRole/ticketing-heal-worker"}

        self.created = []
        clients = {"lambda": self.lam, "ssm": self.ssm, "sqs": self.sqs, "sts": self.sts}

        def client(name, *args, **kwargs):
            self.created.append(name)
            return clients[name]

        boto = patch.object(heal.boto3, "client", side_effect=client)
        boto.start()
        self.addCleanup(boto.stop)

    def run_heal(self):
        with self.assertLogs(level="INFO") as logs:
            result = heal.handler({}, None)
        return result, "\n".join(logs.output)

    def test_re_enables_the_disabled_purchase_trigger(self):
        result, logs = self.run_heal()
        self.assertEqual(result["outcome"], "re_enabled")
        self.lam.update_event_source_mapping.assert_called_once_with(UUID=UUID, Enabled=True)
        self.assertIn("re_enable_attempt", logs)
        self.assertIn('"outcome": "re_enabled"', logs)
        self.assertIn('"queuedMessages": 17', logs)

    def test_enabled_trigger_is_left_alone(self):
        for state in ("Enabled", "Enabling", "Updating", "Disabling", "Creating"):
            self.lam.get_event_source_mapping.return_value["State"] = state
            result, _ = self.run_heal()
            self.assertEqual(result["outcome"], "no_action")
        self.lam.update_event_source_mapping.assert_not_called()
        self.ssm.get_parameter.assert_not_called()

    def test_maintenance_flag_keeps_trigger_disabled(self):
        self.ssm.get_parameter.return_value = {"Parameter": {"Value": " ON "}}
        result, logs = self.run_heal()
        self.assertEqual(result["outcome"], "maintenance_hold")
        self.assertIn("maintenance_hold", logs)
        self.lam.update_event_source_mapping.assert_not_called()

    def test_unreadable_or_invalid_flag_fails_closed(self):
        self.ssm.get_parameter.side_effect = denied("GetParameter")
        result, logs = self.run_heal()
        self.assertEqual(result["outcome"], "maintenance_flag_unreadable")
        self.assertIn("ERROR", logs)

        self.ssm.get_parameter.side_effect = None
        self.ssm.get_parameter.return_value = {"Parameter": {"Value": "paused"}}
        result, _ = self.run_heal()
        self.assertEqual(result["outcome"], "maintenance_flag_unreadable")
        self.lam.update_event_source_mapping.assert_not_called()

    def test_waits_while_sqs_permissions_are_still_missing(self):
        self.sqs.get_queue_attributes.side_effect = denied("GetQueueAttributes")
        result, logs = self.run_heal()
        self.assertEqual(result["outcome"], "permissions_not_ready")
        self.assertIn("sqs:GetQueueAttributes", logs)
        self.lam.update_event_source_mapping.assert_not_called()

    def test_refuses_a_mapping_for_another_queue_or_function(self):
        for field, value in (("EventSourceArn", QUEUE_ARN.replace("purchase-queue", "other")),
                             ("FunctionArn", "arn:aws:lambda:us-east-1:123456789012:function:other")):
            self.setUp()
            self.lam.get_event_source_mapping.return_value[field] = value
            with self.assertLogs(level="ERROR"), self.assertRaises(heal.HealConfigError):
                heal.handler({}, None)
            self.lam.update_event_source_mapping.assert_not_called()

    def test_refuses_when_roles_differ(self):
        self.lam.get_function_configuration.return_value = {"Role": "arn:aws:iam::123456789012:role/Other"}
        with self.assertLogs(level="ERROR"), self.assertRaises(heal.HealConfigError):
            heal.handler({}, None)
        self.lam.update_event_source_mapping.assert_not_called()

    def test_failed_update_is_logged_and_raised(self):
        self.lam.update_event_source_mapping.side_effect = denied("UpdateEventSourceMapping")
        with self.assertLogs(level="ERROR") as logs, self.assertRaises(ClientError):
            heal.handler({}, None)
        self.assertIn("re_enable_failed", "\n".join(logs.output))

    def test_never_touches_data_services_or_disables(self):
        self.run_heal()
        self.assertTrue(set(self.created) <= {"lambda", "ssm", "sqs", "sts"}, self.created)
        for call in self.lam.update_event_source_mapping.call_args_list:
            self.assertIs(call.kwargs["Enabled"], True)
        self.sqs.receive_message.assert_not_called()
        self.sqs.delete_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
