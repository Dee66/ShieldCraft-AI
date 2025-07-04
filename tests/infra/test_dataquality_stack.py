import pytest
from aws_cdk import App, Stack, assertions
from infra.stacks.data.dataquality_stack import DataQualityStack
from aws_cdk import aws_ec2 as ec2

@pytest.fixture
def dq_config():
    return {
        "data_quality": {
            "glue_job": {
                "enabled": True,
                "name": "test-dq-job",
                "role_arn": "arn:aws:iam::123456789012:role/GlueJobRole",
                "command_name": "glueetl",
                "script_location": "s3://bucket/scripts/dq.py",
                "default_arguments": {}
            }
        },
        "app": {"env": "test"}
    }


# --- Happy path: Glue Job creation ---
def test_dataquality_stack_synthesizes(dq_config):
    app = App()
    test_stack = Stack(app, "TestStack")
    stack = DataQualityStack(
        test_stack,
        "TestDataQualityStack",
        config=dq_config,
        dq_glue_role_arn="arn:aws:iam::123456789012:role/MockGlueRole"
    )
    template = assertions.Template.from_stack(stack)
    template.resource_count_is("AWS::Glue::Job", 1)
    # Shared resources dict exposes glue job
    assert hasattr(stack, "shared_resources")
    assert "dq_glue_job" in stack.shared_resources
    assert stack.shared_resources["dq_glue_job"] == stack.dq_glue_job

# --- Happy path: Lambda creation ---
def test_dataquality_stack_lambda_creation():
    app = App()
    test_stack = Stack(app, "TestStack")
    config = {
        "data_quality": {
            "lambda": {
                "enabled": True,
                "handler": "index.handler",
                "code_path": "lambda/dataquality",
                "environment": {"FOO": "BAR"},
                "timeout": 30,
                "memory": 256,
                "log_retention": 3
            }
        },
        "app": {"env": "test"}
    }
    stack = DataQualityStack(
        test_stack,
        "TestDataQualityStack",
        config=config,
        dq_lambda_role_arn="arn:aws:iam::123456789012:role/MockLambdaRole"
    )
    assert hasattr(stack, "dq_lambda")
    # Shared resources dict exposes lambda
    assert "dq_lambda" in stack.shared_resources
    assert stack.shared_resources["dq_lambda"] == stack.dq_lambda
    # Lambda error alarm present
    assert hasattr(stack, "lambda_error_alarm")
    assert stack.lambda_error_alarm.alarm_arn is not None

# --- Happy path: Outputs ---
def test_dataquality_stack_outputs(dq_config):
    app = App()
    test_stack = Stack(app, "TestStack")
    stack = DataQualityStack(
        test_stack,
        "TestDataQualityStack",
        config=dq_config,
        dq_glue_role_arn="arn:aws:iam::123456789012:role/MockGlueRole"
    )
    template = assertions.Template.from_stack(stack)
    outputs = template.to_json().get("Outputs", {})
    assert "TestDataQualityStackDataQualityGlueJobName" in outputs
    # Glue job failure alarm output (if present)
    alarm_key = "TestDataQualityStackDataQualityGlueJobFailureAlarmArn"
    if alarm_key in outputs:
        assert outputs[alarm_key]

# --- Happy path: Tagging ---
def test_dataquality_stack_tags(dq_config):
    app = App()
    test_stack = Stack(app, "TestStack")
    stack = DataQualityStack(
        test_stack,
        "TestDataQualityStack",
        config=dq_config,
        dq_glue_role_arn="arn:aws:iam::123456789012:role/MockGlueRole"
    )
    tags = stack.tags.render_tags()
    assert any(tag.get("Key") == "Project" and tag.get("Value") == "ShieldCraftAI" for tag in tags)

# --- Happy path: Lambda error alarm output ---
def test_dataquality_stack_lambda_alarm_output():
    app = App()
    test_stack = Stack(app, "TestStack")
    config = {
        "data_quality": {
            "lambda": {
                "enabled": True,
                "handler": "index.handler",
                "code_path": "lambda/dataquality",
                "environment": {"FOO": "BAR"},
                "timeout": 30,
                "memory": 256,
                "log_retention": 3
            }
        },
        "app": {"env": "test"}
    }
    stack = DataQualityStack(
        test_stack,
        "TestDataQualityStack",
        config=config,
        dq_lambda_role_arn="arn:aws:iam::123456789012:role/MockLambdaRole"
    )
    template = assertions.Template.from_stack(stack)
    outputs = template.to_json().get("Outputs", {})
    assert "TestDataQualityStackDataQualityLambdaErrorAlarmArn" in outputs

# --- Unhappy path: Missing required Glue Job config ---
@pytest.mark.parametrize("bad_config", [
    {"data_quality": {"glue_job": {"enabled": True}}},
    {"data_quality": {"glue_job": {"enabled": True, "name": ""}}},
])
def test_dataquality_stack_invalid_glue_config(bad_config):
    app = App()
    test_stack = Stack(app, "TestStack")
    with pytest.raises(Exception):
        DataQualityStack(
            test_stack,
            "TestDataQualityStack",
            config=bad_config,
            dq_glue_role_arn="arn:aws:iam::123456789012:role/MockGlueRole"
        )

# --- Unhappy path: Invalid Lambda config ---
@pytest.mark.parametrize("bad_config", [
    {"data_quality": {"lambda": {"enabled": True, "handler": "", "code_path": ""}}},
    {"data_quality": {"lambda": {"enabled": True, "timeout": -1}}},
])
def test_dataquality_stack_invalid_lambda_config(bad_config):
    app = App()
    test_stack = Stack(app, "TestStack")
    with pytest.raises(Exception):
        DataQualityStack(
            test_stack,
            "TestDataQualityStack",
            config=bad_config,
            dq_lambda_role_arn="arn:aws:iam::123456789012:role/MockLambdaRole"
        )

# --- Happy path: Unknown config keys (should not raise) ---
def test_dataquality_stack_unknown_config_keys():
    app = App()
    test_stack = Stack(app, "TestStack")
    config = {"app": {"env": "test"}, "data_quality": {"lambda": {"enabled": True, "unknown_key": 123}}}
    stack = DataQualityStack(
        test_stack,
        "TestDataQualityStack",
        config=config,
        dq_lambda_role_arn="arn:aws:iam::123456789012:role/MockLambdaRole"
    )
    assert hasattr(stack, "tags")

# --- Happy path: Minimal config (no resources) ---
def test_dataquality_stack_minimal_config():
    app = App()
    test_stack = Stack(app, "TestStack")
    config = {"data_quality": {}}
    stack = DataQualityStack(test_stack, "TestDataQualityStack", config=config)
    assert hasattr(stack, "tags")
