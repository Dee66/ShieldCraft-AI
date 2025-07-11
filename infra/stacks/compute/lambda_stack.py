from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_cloudwatch as cloudwatch,
    Duration,
    RemovalPolicy,
    CfnOutput,
    custom_resources as cr,
)
from constructs import Construct
import json


class LambdaStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.IVpc,
        config: dict,
        lambda_role_arn: str = None,
        shared_resources: dict = None,
        shared_tags: dict = None,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        lambda_cfgs = config.get("lambda_", {}).get("functions", [])
        env = config.get("app", {}).get("env", "dev")
        tags_cfg = config.get("lambda_", {}).get("tags", {})

        # Tagging for traceability and custom tags
        self.tags.set_tag("Project", "ShieldCraftAI")
        self.tags.set_tag("Environment", env)
        for k, v in tags_cfg.items():
            self.tags.set_tag(k, v)
        if shared_tags:
            for k, v in shared_tags.items():
                self.tags.set_tag(k, v)

        if not isinstance(lambda_cfgs, list):
            raise ValueError("Lambda functions config must be a list.")
        fn_names = set()
        self.functions = []
        self.shared_resources = {}
        for fn_cfg in lambda_cfgs:
            # If no explicit role_arn in function config, use the stack-provided lambda_role_arn
            if not fn_cfg.get("role_arn") and lambda_role_arn:
                fn_cfg["role_arn"] = lambda_role_arn
            name = fn_cfg.get("name")
            runtime = fn_cfg.get("runtime", "PYTHON_3_11")
            handler = fn_cfg.get("handler", "index.handler")
            code_path = fn_cfg.get("code_path", f"lambda/{name}")
            environment = fn_cfg.get("environment", {})
            timeout = fn_cfg.get("timeout", 60)
            use_vpc = fn_cfg.get("vpc", True)
            memory = fn_cfg.get("memory", 128)
            role_arn = fn_cfg.get("role_arn")
            removal_policy = fn_cfg.get("removal_policy", None)
            if isinstance(removal_policy, str):
                removal_policy = getattr(RemovalPolicy, removal_policy.upper(), None)
            if removal_policy is None:
                removal_policy = (
                    RemovalPolicy.DESTROY if env == "dev" else RemovalPolicy.RETAIN
                )
            if not name or not runtime or not handler or not code_path:
                raise ValueError(
                    f"Lambda function config must include name, runtime, handler, and code_path. Got: {fn_cfg}"
                )
            if name in fn_names:
                raise ValueError(f"Duplicate Lambda function name: {name}")
            fn_names.add(name)
            # Validate runtime
            if not hasattr(_lambda.Runtime, runtime):
                raise ValueError(f"Invalid Lambda runtime: {runtime}")
            # Validate environment variables
            if not isinstance(environment, dict):
                raise ValueError(
                    f"Lambda environment must be a dict for function {name}"
                )
            # Validate timeout
            if not isinstance(timeout, int):
                raise ValueError(
                    f"Lambda timeout must be an int (seconds) for function {name}"
                )
            # IAM Role (shared, custom, or auto)
            role = None
            if role_arn:
                role = iam.Role.from_role_arn(
                    self, f"{construct_id}Lambda{name}Role", role_arn
                )
            elif shared_resources and shared_resources.get("lambda_role"):
                role = shared_resources["lambda_role"]
            # VPC and SG (shared or provided)
            lambda_vpc = vpc
            lambda_sgs = None
            if shared_resources:
                lambda_vpc = shared_resources.get("vpc", vpc)
                if shared_resources.get("default_sg"):
                    lambda_sgs = [shared_resources["default_sg"]]
            # Log retention (explicit LogGroup, robust mapping)
            log_retention = fn_cfg.get("log_retention", None)
            from aws_cdk import aws_logs

            retention_enum = None
            log_group = None
            if log_retention is not None:
                retention_map = {
                    1: aws_logs.RetentionDays.ONE_DAY,
                    3: aws_logs.RetentionDays.THREE_DAYS,
                    5: aws_logs.RetentionDays.FIVE_DAYS,
                    7: aws_logs.RetentionDays.ONE_WEEK,
                    14: aws_logs.RetentionDays.TWO_WEEKS,
                    30: aws_logs.RetentionDays.ONE_MONTH,
                    60: aws_logs.RetentionDays.TWO_MONTHS,
                    90: aws_logs.RetentionDays.THREE_MONTHS,
                    120: aws_logs.RetentionDays.FOUR_MONTHS,
                    150: aws_logs.RetentionDays.FIVE_MONTHS,
                    180: aws_logs.RetentionDays.SIX_MONTHS,
                    365: aws_logs.RetentionDays.ONE_YEAR,
                    400: aws_logs.RetentionDays.THIRTEEN_MONTHS,
                    545: aws_logs.RetentionDays.EIGHTEEN_MONTHS,
                    731: aws_logs.RetentionDays.TWO_YEARS,
                    1827: aws_logs.RetentionDays.FIVE_YEARS,
                    3653: aws_logs.RetentionDays.TEN_YEARS,
                }
                if isinstance(log_retention, int):
                    retention_enum = retention_map.get(
                        log_retention, aws_logs.RetentionDays.ONE_WEEK
                    )
                elif isinstance(log_retention, aws_logs.RetentionDays):
                    retention_enum = log_retention
                # Explicit LogGroup creation
                log_group = aws_logs.LogGroup(
                    self,
                    f"{name}LogGroup",
                    log_group_name=f"/aws/lambda/{name}",
                    retention=retention_enum,
                    removal_policy=removal_policy,
                )
            lambda_kwargs = dict(
                runtime=getattr(_lambda.Runtime, runtime),
                handler=handler,
                code=_lambda.Code.from_asset(code_path),
                environment=environment,
                timeout=Duration.seconds(timeout),
                memory_size=memory,
                vpc=lambda_vpc if use_vpc else None,
                security_groups=lambda_sgs,
                role=role,
            )
            if log_group is not None:
                lambda_kwargs["log_group"] = log_group
            fn = _lambda.Function(self, name, **lambda_kwargs)
            fn.apply_removal_policy(removal_policy)
            # Monitoring: CloudWatch alarms for errors, throttles, duration
            error_alarm = cloudwatch.Alarm(
                self,
                f"{construct_id}Lambda{name}ErrorAlarm",
                metric=cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Errors",
                    dimensions_map={"FunctionName": fn.function_name},
                    statistic="Sum",
                    period=Duration.minutes(5),
                ),
                threshold=1,
                evaluation_periods=1,
                alarm_description=f"Lambda {name} errors detected",
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            )
            throttle_alarm = cloudwatch.Alarm(
                self,
                f"{construct_id}Lambda{name}ThrottleAlarm",
                metric=cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Throttles",
                    dimensions_map={"FunctionName": fn.function_name},
                    statistic="Sum",
                    period=Duration.minutes(5),
                ),
                threshold=1,
                evaluation_periods=1,
                alarm_description=f"Lambda {name} throttles detected",
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            )
            duration_alarm = cloudwatch.Alarm(
                self,
                f"{construct_id}Lambda{name}DurationAlarm",
                metric=cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Duration",
                    dimensions_map={"FunctionName": fn.function_name},
                    statistic="Average",
                    period=Duration.minutes(5),
                ),
                threshold=fn.timeout.to_seconds() * 0.9,  # 90% of timeout
                evaluation_periods=1,
                alarm_description=f"Lambda {name} duration high",
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            )
            # Outputs
            CfnOutput(
                self,
                f"{construct_id}Lambda{name}Name",
                value=fn.function_name,
                export_name=f"{construct_id}-lambda-{name}-name",
            )
            CfnOutput(
                self,
                f"{construct_id}Lambda{name}Arn",
                value=fn.function_arn,
                export_name=f"{construct_id}-lambda-{name}-arn",
            )
            CfnOutput(
                self,
                f"{construct_id}Lambda{name}ErrorAlarmArn",
                value=error_alarm.alarm_arn,
                export_name=f"{construct_id}-lambda-{name}-error-alarm-arn",
            )
            CfnOutput(
                self,
                f"{construct_id}Lambda{name}ThrottleAlarmArn",
                value=throttle_alarm.alarm_arn,
                export_name=f"{construct_id}-lambda-{name}-throttle-alarm-arn",
            )
            CfnOutput(
                self,
                f"{construct_id}Lambda{name}DurationAlarmArn",
                value=duration_alarm.alarm_arn,
                export_name=f"{construct_id}-lambda-{name}-duration-alarm-arn",
            )
            # Shared resources dict for downstream stacks
            self.shared_resources[name] = {
                "function": fn,
                "role": fn.role,
                "error_alarm": error_alarm,
                "throttle_alarm": throttle_alarm,
                "duration_alarm": duration_alarm,
            }
            self.functions.append(fn)

        # Find the config for the topic creator Lambda
        topic_lambda_cfg = next(
            (f for f in lambda_cfgs if f["name"] == "msk_topic_creator"), None
        )
        if topic_lambda_cfg:
            # Import MSK cluster ARN and topic config from shared_resources or config
            msk_cluster_arn = shared_resources["msk"]["cluster_arn"]
            topic_config = config["msk"]["topics"]  # List of dicts

            # Set environment variables
            topic_lambda_cfg["environment"].update(
                {
                    "MSK_CLUSTER_ARN": msk_cluster_arn,
                    "TOPIC_CONFIG": json.dumps(topic_config),
                }
            )

            # Grant least-privilege permissions for MSK topic management
            fn = self.shared_resources["msk_topic_creator"]["function"]
            msk_arn = msk_cluster_arn
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=[
                        "kafka:DescribeCluster",
                        "kafka:GetBootstrapBrokers",
                        "kafka:CreateTopic",
                        "kafka:ListTopics",
                        "kafka:DescribeTopic",
                    ],
                    resources=[msk_arn],
                )
            )
            # Networking is handled by vpc/vpc_sg

            # --- Custom Resource to trigger topic creation ---
            provider = cr.Provider(self, "MskTopicCreatorProvider", on_event_handler=fn)
            cr.CustomResource(
                self,
                "MskTopicCreatorCustomResource",
                service_token=provider.service_token,
                properties={
                    "ClusterArn": msk_cluster_arn,
                    "TopicConfig": json.dumps(topic_config),
                },
            )

        from aws_cdk import aws_lambda, aws_iam

        class LambdaStack(Stack):
            def __init__(
                self,
                scope: Construct,
                construct_id: str,
                vpc: ec2.IVpc,
                config: dict,
                shared_resources: dict = None,
                **kwargs,
            ):
                super().__init__(scope, construct_id, **kwargs)
                lambda_cfgs = config.get("lambda", {}).get("functions", {})

                for name, fn_cfg in lambda_cfgs.items():
                    if name == "msk_topic_creator":
                        msk_cluster_arn = shared_resources["msk"]["cluster_arn"]
                        topic_config = config["msk"]["topics"]
                        fn_cfg["environment"].update(
                            {
                                "MSK_CLUSTER_ARN": msk_cluster_arn,
                                "TOPIC_CONFIG": json.dumps(topic_config),
                            }
                        )

                        fn = aws_lambda.Function(
                            self,
                            "MskTopicCreatorLambda",
                            runtime=aws_lambda.Runtime.PYTHON_3_11,
                            handler=fn_cfg["handler"],
                            code=aws_lambda.Code.from_asset(fn_cfg["code_path"]),
                            timeout=Duration.seconds(fn_cfg["timeout"]),
                            memory_size=fn_cfg["memory"],
                            vpc=vpc,
                            environment=fn_cfg["environment"],
                        )
                        fn.add_to_role_policy(
                            aws_iam.PolicyStatement(
                                actions=[
                                    "kafka:DescribeCluster",
                                    "kafka:GetBootstrapBrokers",
                                ],
                                resources=["*"],
                            )
                        )
