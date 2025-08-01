import os
import pytest
import boto3
from kafka.admin import KafkaAdminClient


def get_bootstrap_brokers(cluster_arn, region):
    client = boto3.client("kafka", region_name=region)
    resp = client.get_bootstrap_brokers(ClusterArn=cluster_arn)
    return resp["BootstrapBrokerStringTls"]


@pytest.mark.integration
@pytest.mark.msk
def test_msk_topics_exist():
    # Use ShieldCraft config_loader for all config
    import sys

    sys.path.append(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    )
    from infra.utils.config_loader import get_config_loader

    config = get_config_loader()
    msk_cfg = config.get_section("msk")
    lambda_cfgs = config.get_section("lambda_").get("functions", [])
    # Find the topic creator lambda config
    topic_lambda = next(
        (
            f
            for f in lambda_cfgs
            if f.get("name", f.get("id")) in ["msk_topic_creator", "MskTopicCreator"]
        ),
        None,
    )
    assert topic_lambda, "msk_topic_creator lambda config not found"

    # Get cluster ARN and topics from config, with environment variable fallback
    cluster_arn = (
        msk_cfg["cluster"].get("arn")
        or msk_cfg["cluster"].get("cluster_arn")
        or os.environ.get("MSK_CLUSTER_ARN")
    )
    if not cluster_arn:
        pytest.skip(
            "MSK cluster ARN not found in config or environment. Add 'arn' or 'cluster_arn' to msk.cluster config, or set MSK_CLUSTER_ARN env var."
        )

    # Support both new and legacy topic config
    topics_cfg = topic_lambda.get("environment", {}).get("TOPICS")
    if not topics_cfg:
        pytest.skip("No topics defined in msk_topic_creator lambda config.")
    expected_topics = [t["name"] for t in topics_cfg]

    region = config.get_section("app").get("region", "af-south-1")

    brokers = get_bootstrap_brokers(cluster_arn, region)
    admin = KafkaAdminClient(
        bootstrap_servers=brokers,
        security_protocol="SSL",
    )
    actual_topics = set(admin.list_topics())
    missing = [t for t in expected_topics if t not in actual_topics]
    assert not missing, f"Missing topics: {missing}"
