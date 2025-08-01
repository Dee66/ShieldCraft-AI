<section style="border:1px solid #a5b4fc; border-radius:10px; margin:1.5em 0; box-shadow:0 2px 8px #222; padding:1.5em; background:#111; color:#fff;">
<div style="margin-bottom:1.5em;">
  <a href="./checklist.md" style="color:#a5b4fc; font-weight:bold; text-decoration:none; font-size:1.1em;">⬅️ Back to Checklist</a>
</div>
<section style="border:1px solid #a5b4fc; border-radius:10px; margin:1.5em 0; box-shadow:0 2px 8px #222; padding:1.5em; background:#111; color:#fff;">
<h1 style="color:#a5b4fc; margin-top:0; font-size:2em;">AWS EventBridge Integration Planning</h1>

## 1. Objectives & Use Cases
- What business or technical problems are you solving with EventBridge?
- List the main workflows or scenarios (e.g., trigger ML pipeline on S3 upload, route security alerts, orchestrate data quality checks).

## 2. Event Sources
- Which AWS services or custom applications will emit events?
  - (e.g., S3, Lambda, Glue, SageMaker, custom microservices)
- For each source, what event types will be published?

## 3. Event Targets (Consumers)
- Which services or resources will consume/process these events?
  - (e.g., Lambda functions, Step Functions, SNS, SQS, other AWS services)
- For each target, what action should be triggered?

## 4. Event Buses
- Will you use the default event bus, or create custom event buses for domain separation?
  - (e.g., data-events, security-events, ml-events)
- If custom, what is the purpose of each bus?

## 5. Event Rules
- What rules will you define to filter and route events?
  - (e.g., S3:ObjectCreated → DataQuality Lambda, SageMaker:ModelDeployed → Notification)
- What event patterns or filters will you use?

## 6. Event Schema & Contracts
- For custom events, define the schema (fields, types, required/optional).
- Will you use the EventBridge Schema Registry for governance?

## 7. Security & Permissions
- Which IAM roles need permission to put events on the bus?
- Which roles can consume events?
- Any sensitive data or compliance considerations?

## 8. Cross-Stack Integration
- Which stacks will need to reference the event bus or rules?
- What outputs (CfnOutput) and imports (Fn.import_value) will be required?

## 9. Observability & Error Handling
- How will you monitor event delivery, failures, and dead-letter queues?
- What CloudWatch metrics, logs, or alerts are needed?

## 10. Testing & Validation
- How will you test event flows (unit, integration, end-to-end)?
- How will you validate event contracts and permissions?

</section>
