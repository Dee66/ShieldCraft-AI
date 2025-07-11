from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_secretsmanager as secretsmanager,
    aws_ecs as ecs,
    Duration,
)
from constructs import Construct


class AirbyteStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.IVpc,
        config: dict,
        airbyte_role_arn: str,
        shared_resources: dict = None,
        shared_tags: dict = None,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)
        airbyte_cfg = config.get("airbyte", {})
        env = config.get("app", {}).get("env", "dev")
        # Tagging for traceability and custom tags
        self.tags.set_tag("Project", "ShieldCraftAI")
        self.tags.set_tag("Environment", env)
        for k, v in airbyte_cfg.get("tags", {}).items():
            self.tags.set_tag(k, v)
        if shared_tags:
            for k, v in shared_tags.items():
                self.tags.set_tag(k, v)

        from aws_cdk import RemovalPolicy, CfnOutput

        # Removal policy
        removal_policy = airbyte_cfg.get("removal_policy", None)
        if isinstance(removal_policy, str):
            removal_policy = getattr(RemovalPolicy, removal_policy.upper(), None)
        if removal_policy is None:
            removal_policy = (
                RemovalPolicy.DESTROY if env == "dev" else RemovalPolicy.RETAIN
            )

        # --- Config Validation ---
        # instance_type = airbyte_cfg.get('instance_type', 't3.medium')
        desired_count = airbyte_cfg.get("desired_count", 1)
        cpu = airbyte_cfg.get("cpu", 1024)
        memory = airbyte_cfg.get("memory", 2048)
        if not isinstance(desired_count, int) or desired_count < 1:
            raise ValueError("Airbyte desired_count must be a positive integer")
        if cpu and (not isinstance(cpu, int) or cpu < 256):
            raise ValueError("Airbyte cpu must be an integer >= 256")
        if memory and (not isinstance(memory, int) or memory < 512):
            raise ValueError("Airbyte memory must be an integer >= 512")

        secret_arn = airbyte_cfg.get("db_secret_arn")
        db_secret = None
        if secret_arn:
            db_secret = secretsmanager.Secret.from_secret_complete_arn(
                self, f"{construct_id}AirbyteDbSecret", secret_arn
            )

        airbyte_sg = ec2.SecurityGroup(
            self,
            f"{construct_id}AirbyteSecurityGroup",
            vpc=vpc,
            description="Security group for Airbyte",
            allow_all_outbound=True,
        )

        self.cluster = ecs.Cluster(self, f"{construct_id}AirbyteCluster", vpc=vpc)

        # --- ECS Task Definition & Service ---
        airbyte_image = airbyte_cfg.get("image", "airbyte/airbyte:0.50.2")
        container_port = airbyte_cfg.get("container_port", 8000)

        from aws_cdk import aws_iam as iam

        # Import the Airbyte execution role from the provided ARN
        task_role = iam.Role.from_role_arn(
            self,
            f"{construct_id}AirbyteImportedTaskRole",
            airbyte_role_arn,
            mutable=False,
        )

        from aws_cdk import aws_logs as logs

        log_group_name = airbyte_cfg.get("log_group", f"/aws/ecs/airbyte-{env}")
        log_group = logs.LogGroup(
            self,
            f"{construct_id}AirbyteLogGroup",
            log_group_name=log_group_name,
            removal_policy=removal_policy,
        )

        task_def = ecs.FargateTaskDefinition(
            self,
            f"{construct_id}AirbyteTaskDef",
            cpu=cpu,
            memory_limit_mib=memory,
            task_role=task_role,
        )

        env_vars = airbyte_cfg.get("environment", {})
        container_secrets = {}
        if secret_arn:
            # Inject the actual secret value as AIRBYTE_DB_SECRET
            container_secrets["AIRBYTE_DB_SECRET"] = ecs.Secret.from_secrets_manager(
                db_secret
            )

        container = task_def.add_container(
            f"{construct_id}AirbyteContainer",
            image=ecs.ContainerImage.from_registry(airbyte_image),
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="airbyte", log_group=log_group
            ),
            environment=env_vars,
            secrets=container_secrets if container_secrets else None,
        )
        container.add_port_mappings(ecs.PortMapping(container_port=container_port))

        subnet_type_str = airbyte_cfg.get("subnet_type", "PRIVATE_WITH_EGRESS").upper()
        subnet_type = getattr(
            ec2.SubnetType, subnet_type_str, ec2.SubnetType.PRIVATE_WITH_EGRESS
        )

        self.service = ecs.FargateService(
            self,
            f"{construct_id}AirbyteService",
            cluster=self.cluster,
            task_definition=task_def,
            desired_count=desired_count,
            security_groups=[airbyte_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=subnet_type),
        )

        from aws_cdk import aws_elasticloadbalancingv2 as elbv2

        alb = elbv2.ApplicationLoadBalancer(
            self,
            f"{construct_id}AirbyteALB",
            vpc=vpc,
            internet_facing=True if subnet_type == ec2.SubnetType.PUBLIC else False,
            security_group=airbyte_sg,
        )
        listener = alb.add_listener(
            f"{construct_id}AirbyteListener", port=80, open=True
        )
        health_path = airbyte_cfg.get("health_check_path", "/api/v1/health")
        healthy_codes = airbyte_cfg.get("health_check_codes", "200")
        listener.add_targets(
            f"{construct_id}AirbyteTarget",
            port=container_port,
            targets=[self.service],
            health_check=elbv2.HealthCheck(
                path=health_path, healthy_http_codes=healthy_codes
            ),
        )

        # Restrict security group ingress to ALB or open to 0.0.0.0/0 for demo, but recommend locking down in prod
        allowed_cidr = airbyte_cfg.get("allowed_cidr", "0.0.0.0/0")
        airbyte_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(allowed_cidr),
            connection=ec2.Port.tcp(80),
            description="Allow HTTP from ALB or allowed CIDR",
        )

        self.alb = alb

        # --- Monitoring: CloudWatch alarms for ECS service and ALB ---
        from aws_cdk import aws_cloudwatch as cloudwatch

        # ECS Service Task Failures metric (ServiceTaskFailures)
        ecs_task_failures_metric = cloudwatch.Metric(
            namespace="AWS/ECS",
            metric_name="ServiceTaskFailures",
            dimensions_map={
                "ClusterName": self.cluster.cluster_name,
                "ServiceName": self.service.service_name,
            },
            statistic="Sum",
            period=Duration.minutes(5),
        )
        self.ecs_task_alarm = cloudwatch.Alarm(
            self,
            f"{construct_id}AirbyteTaskFailureAlarm",
            metric=ecs_task_failures_metric,
            threshold=1,
            evaluation_periods=1,
            alarm_description="ECS task failures detected",
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )
        CfnOutput(
            self,
            f"{construct_id}AirbyteTaskFailureAlarmArn",
            value=self.ecs_task_alarm.alarm_arn,
            export_name=f"{construct_id}-task-failure-alarm-arn",
        )
        self.alb_5xx_alarm = cloudwatch.Alarm(
            self,
            f"{construct_id}AirbyteAlb5xxAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/ApplicationELB",
                metric_name="HTTPCode_Target_5XX_Count",
                dimensions_map={"LoadBalancer": alb.load_balancer_full_name},
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=1,
            evaluation_periods=1,
            alarm_description="ALB 5XX errors detected",
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )
        CfnOutput(
            self,
            f"{construct_id}AirbyteAlb5xxAlarmArn",
            value=self.alb_5xx_alarm.alarm_arn,
            export_name=f"{construct_id}-alb-5xx-alarm-arn",
        )

        # --- Outputs: ALB DNS, ECS Service Name, Log Group Name ---
        CfnOutput(
            self,
            f"{construct_id}AirbyteALBDns",
            value=alb.load_balancer_dns_name,
            export_name=f"{construct_id}-alb-dns",
        )
        CfnOutput(
            self,
            f"{construct_id}AirbyteServiceName",
            value=self.service.service_name,
            export_name=f"{construct_id}-service-name",
        )
        CfnOutput(
            self,
            f"{construct_id}AirbyteLogGroupName",
            value=log_group.log_group_name,
            export_name=f"{construct_id}-log-group",
        )
        # Expose for downstream stacks
        self.shared_resources = {
            "cluster": self.cluster,
            "service": self.service,
            "alb": self.alb,
            "log_group": log_group,
            "task_alarm": self.ecs_task_alarm,
            "alb_5xx_alarm": self.alb_5xx_alarm,
        }
