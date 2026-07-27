// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ecr_assets from "aws-cdk-lib/aws-ecr-assets";
import * as path from "path";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import * as apigwv2_integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as apigwv2_authorizers from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as sns from "aws-cdk-lib/aws-sns";
import * as wafv2 from "aws-cdk-lib/aws-wafv2";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as route53Targets from "aws-cdk-lib/aws-route53-targets";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as fs from "fs";
import { execSync } from "child_process";
import * as bedrock from "aws-cdk-lib/aws-bedrock";
import * as agentcore from "@aws-cdk/aws-bedrock-agentcore-alpha";
import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore";
import { Construct } from "constructs";

/**
 * P2P Agentic Platform Stack.
 *
 * Replaces all Terraform infrastructure with CDK.
 * Uses AgentCore constructs for agent runtimes, gateway, memory, and code interpreter.
 * ERPNext is the system of record — agents access it via MCP tools through Gateway.
 */
export class P2PAgenticStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: P2PAgenticStackProps) {
    super(scope, id, props);

    const prefix = "p2p-dev";

    // =====================================================================
    // =====================================================================
    // Cognito User Pool
    // =====================================================================

    const userPool = new cognito.UserPool(this, "UserPool", {
      userPoolName: `${prefix}-users`,
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      passwordPolicy: {
        minLength: 8,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: false,
      },
      customAttributes: {
        role: new cognito.StringAttribute({ maxLen: 50 }),
        department: new cognito.StringAttribute({ maxLen: 100 }),
      },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Resolve frontend FQDN early so Cognito callback URLs can reference it.
    // This duplicates the domain config logic below, but Cognito client must be
    // defined before the CloudFront section. Values come from CDK context.
    const _hostedZoneName = this.node.tryGetContext("hostedZoneName") as string | undefined;
    const _frontendDomainPrefix = this.node.tryGetContext("frontendDomainPrefix") as string | undefined;
    const _frontendFqdn = _hostedZoneName
      ? (_frontendDomainPrefix ? `${_frontendDomainPrefix}.${_hostedZoneName}` : _hostedZoneName)
      : undefined;

    const frontendClient = userPool.addClient("FrontendClient", {
      userPoolClientName: `${prefix}-frontend`,
      authFlows: { userSrp: true },
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.PROFILE,
        ],
        callbackUrls: [
          "http://localhost:5173/",
          "http://localhost:5174/",
          ...(_frontendFqdn ? [`https://${_frontendFqdn}/`] : []),
        ],
        logoutUrls: [
          "http://localhost:5173/",
          "http://localhost:5174/",
          ...(_frontendFqdn ? [`https://${_frontendFqdn}/`] : []),
        ],
      },
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(30),
      generateSecret: false,
    });

    // ERPNext SSO client — confidential (with secret) for server-side OAuth2 flow
    const erpnextSsoClient = userPool.addClient("ERPNextSSOClient", {
      userPoolClientName: `${prefix}-erpnext-sso`,
      generateSecret: true,
      authFlows: { userSrp: true },
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.PROFILE,
        ],
        callbackUrls: [
          `${props.erpnextUrl}/api/method/frappe.integrations.oauth2_logins.custom/amazon_cognito`,
        ],
        logoutUrls: [
          props.erpnextUrl,
        ],
      },
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(30),
    });

    const cognitoDomain = userPool.addDomain("CognitoDomain", {
      cognitoDomain: {
        domainPrefix: `${prefix}-${this.account}`,
      },
    });

    // Cognito Groups — role-based access (supplements custom:role attribute)
    const groups = ["requester", "approver", "ap_clerk", "procurement", "executive"];
    for (const group of groups) {
      new cognito.CfnUserPoolGroup(this, `Group_${group}`, {
        userPoolId: userPool.userPoolId,
        groupName: group,
        description: `P2P ${group} role`,
      });
    }

    // =====================================================================
    // Secrets Manager — ERPNext credentials
    // =====================================================================

    const erpnextSecret = new secretsmanager.Secret(this, "ERPNextSecret", {
      secretName: `${prefix}/erpnext-credentials`,
      description: "ERPNext OAuth and service account credentials",
      secretObjectValue: {
        url: cdk.SecretValue.unsafePlainText(
          props.erpnextUrl
        ),
        oauth_client_id: cdk.SecretValue.unsafePlainText("TO_BE_SET"),
        oauth_client_secret: cdk.SecretValue.unsafePlainText("TO_BE_SET"),
        // Per-user API keys populated by setup_erpnext_oauth.py
        service_api_key: cdk.SecretValue.unsafePlainText("TO_BE_SET"),
        service_api_secret: cdk.SecretValue.unsafePlainText("TO_BE_SET"),
      },
    });

    // =====================================================================
    // Cognito Identity Pool — SigV4 credentials for browser → AgentCore
    // =====================================================================

    const identityPool = new cognito.CfnIdentityPool(this, "IdentityPool", {
      identityPoolName: `${prefix}-identity`,
      allowUnauthenticatedIdentities: false,
      cognitoIdentityProviders: [
        {
          clientId: frontendClient.userPoolClientId,
          providerName: userPool.userPoolProviderName,
          serverSideTokenCheck: false,
        },
      ],
    });

    // Authenticated role — allows browser to invoke AgentCore runtimes via SigV4
    const authenticatedRole = new iam.Role(this, "CognitoAuthRole", {
      roleName: `${prefix}-cognito-authenticated`,
      assumedBy: new iam.FederatedPrincipal(
        "cognito-identity.amazonaws.com",
        {
          StringEquals: { "cognito-identity.amazonaws.com:aud": identityPool.ref },
          "ForAnyValue:StringLike": { "cognito-identity.amazonaws.com:amr": "authenticated" },
        },
        "sts:AssumeRoleWithWebIdentity"
      ),
    });
    authenticatedRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["bedrock-agentcore:InvokeAgentRuntime"],
        resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*`],
      })
    );

    // Unauthenticated role (required by Identity Pool but empty)
    const unauthenticatedRole = new iam.Role(this, "CognitoUnauthRole", {
      roleName: `${prefix}-cognito-unauthenticated`,
      assumedBy: new iam.FederatedPrincipal(
        "cognito-identity.amazonaws.com",
        {
          StringEquals: { "cognito-identity.amazonaws.com:aud": identityPool.ref },
          "ForAnyValue:StringLike": { "cognito-identity.amazonaws.com:amr": "unauthenticated" },
        },
        "sts:AssumeRoleWithWebIdentity"
      ),
    });

    new cognito.CfnIdentityPoolRoleAttachment(this, "IdentityPoolRoles", {
      identityPoolId: identityPool.ref,
      roles: {
        authenticated: authenticatedRole.roleArn,
        unauthenticated: unauthenticatedRole.roleArn,
      },
    });

    // =====================================================================
    // DynamoDB — agent-jobs (chat sessions), agent-errors, document-lifecycle
    // =====================================================================

    // agent-jobs and agent-errors tables REMOVED
    // - Chat sessions use AgentCore Memory (not DDB)
    // - Invoice processing uses dedicated invoice-jobs table
    // - Errors tracked in document-lifecycle runs[] array

    const invoiceJobsTable = new dynamodb.Table(this, "InvoiceJobs", {
      tableName: `${prefix}-invoice-jobs`,
      partitionKey: { name: "job_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "ttl",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const chatSessionsTable = new dynamodb.Table(this, "ChatSessions", {
      tableName: `${prefix}-chat-sessions`,
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const lifecycleTable = new dynamodb.Table(this, "DocumentLifecycle", {
      tableName: `${prefix}-document-lifecycle`,
      partitionKey: { name: "document_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // =====================================================================
    // ECR Repository — single repo for all agent containers
    // =====================================================================

    // Build agent container from backend/Dockerfile (ARM64).
    // CDK handles build, push to bootstrap ECR, and image URI referencing.
    // We use DockerImageAsset + fromImageUri (not fromAsset) because fromAsset
    // has a bound-once bug that only grants ECR pull to the first runtime.
    const agentImage = new ecr_assets.DockerImageAsset(this, "AgentImage", {
      directory: path.join(__dirname, "..", "..", "backend"),
      platform: ecr_assets.Platform.LINUX_ARM64,
    });
    const agentArtifact = agentcore.AgentRuntimeArtifact.fromImageUri(agentImage.imageUri);

    // =====================================================================
    // ERPNext Adapter Lambda (VPC — reaches ERPNext ALB via private network)
    // =====================================================================

    // Import VPC and internal ALB SG from ErpNextStack for private connectivity
    const vpc = ec2.Vpc.fromLookup(this, "Vpc", {
      tags: { Project: "p2p-agentic-erp" },
    });

    // Internal ALB SG — Lambda reaches ERPNext via internal ALB (private IPs)
    const internalAlbSgId = cdk.Fn.importValue("ErpNextInternalAlbSgId");
    const internalAlbSg = ec2.SecurityGroup.fromSecurityGroupId(this, "ImportedInternalAlbSg", internalAlbSgId);

    const adapterSg = new ec2.SecurityGroup(this, "AdapterSG", {
      vpc,
      description: "ERP Adapter Lambda - reaches ERPNext internal ALB within VPC",
      allowAllOutbound: true,
    });

    // SG-to-SG rule: allow Adapter Lambda → internal ALB on port 443.
    // Internal ALB resolves to private IPs, so traffic stays in VPC — no NAT needed.
    internalAlbSg.connections.allowFrom(adapterSg, ec2.Port.tcp(443), "Adapter Lambda to ERPNext internal ALB");

    const adapterLambda = new lambda.Function(this, "AdapterLambda", {
      functionName: `${prefix}-erp-adapter`,
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "adapters.canonical_api.handler",
      code: lambda.Code.fromAsset("../backend", {
        bundling: {
          image: lambda.Runtime.PYTHON_3_13.bundlingImage,
          command: [
            "bash", "-c",
            "pip install -r requirements.txt -t /asset-output && cp -r . /asset-output",
          ],
        },
      }),
      timeout: cdk.Duration.seconds(60),
      memorySize: 512,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [adapterSg],
      environment: {
        ERP_TYPE: "erpnext",
        // Use internal ALB URL — resolves to private IPs within VPC.
        ERPNEXT_URL: props.erpnextInternalUrl || props.erpnextUrl,
        ERPNEXT_SECRET_ARN: erpnextSecret.secretArn,
      },
    });

    erpnextSecret.grantRead(adapterLambda);

    // Textract + Bedrock permissions for invoice extraction
    adapterLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["textract:AnalyzeExpense"],
        resources: ["*"],
      })
    );
    adapterLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["s3:GetObject"],
        resources: [`arn:aws:s3:::${prefix}-documents/*`],
      })
    );
    adapterLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: ["*"],
      })
    );

    // =====================================================================
    // AgentCore Gateway (MCP protocol)
    // =====================================================================

    const gateway = new agentcore.Gateway(this, "P2PGateway", {
      gatewayName: `${prefix}-gateway`,
      description: "P2P ERP data access tools — MCP protocol",
      protocolConfiguration: agentcore.GatewayProtocol.mcp({
        supportedVersions: [agentcore.MCPProtocolVersion.MCP_2025_06_18],
        searchType: agentcore.McpGatewaySearchType.SEMANTIC,
        instructions:
          "P2P procurement tools for accessing ERP data. Use these tools to " +
          "read and write suppliers, items, requisitions, purchase orders, " +
          "receipts, invoices, and payments. All IDs are string identifiers. " +
          "Dates are ISO 8601 format.",
      }),
      authorizerConfiguration: agentcore.GatewayAuthorizer.usingAwsIam(),
    });

    // Generate MCP Gateway tool schema from the FastAPI canonical API source code.
    // This ensures the tool definitions always match the backend implementation.
    const toolSchemaPath = "lib/openapi/p2p-tools.json";
    try {
      const generated = execSync("python3 scripts/generate-tools-schema.py", {
        cwd: __dirname + "/..",
        encoding: "utf-8",
        timeout: 30000,
      });
      fs.writeFileSync(toolSchemaPath, generated);
      console.log(`Generated ${toolSchemaPath} from canonical API source`);
    } catch (e) {
      console.warn(`Tool schema generation failed, using existing file: ${e}`);
    }

    const toolSchema = agentcore.ToolSchema.fromLocalAsset(toolSchemaPath);

    const gatewayTarget = gateway.addLambdaTarget("ERPNextAdapter", {
      gatewayTargetName: "erp",
      description: "ERPNext P2P adapter — canonical procurement operations",
      lambdaFunction: adapterLambda,
      toolSchema,
    });

    // =====================================================================
    // AgentCore Policy Engine (Cedar authorization on tool calls)
    // =====================================================================

    const policyEngine = new bedrockagentcore.CfnPolicyEngine(
      this,
      "P2PPolicyEngine",
      {
        name: `${prefix.replace(/-/g, "_")}_policy`,
        description:
          "Cedar-based authorization for P2P procurement tools. " +
          "Enforces role-based access: read for all, write per role.",
      }
    );

    // Load Cedar policies from file — one CfnPolicy per permit/forbid statement
    // (AgentCore CfnPolicy expects exactly one policy per resource)
    const cedarRaw = fs.readFileSync(
      "policies/p2p-procurement.cedar",
      "utf-8"
    );
    // Strip comments and split on permit/forbid boundaries
    const stripped = cedarRaw
      .split("\n")
      .filter((line: string) => !line.trimStart().startsWith("//"))
      .join("\n")
      .trim();
    const statements = stripped
      .split(/(?=(?:permit|forbid)\()/)
      .map((s: string) => s.trim())
      .filter((s: string) => s.startsWith("permit") || s.startsWith("forbid"));

    const policyNames = [
      "iam_full_access",
      "oauth_read_access",
      "requisition_write",
      "po_receipt_write",
      "invoice_write",
      "payment_write",
    ];

    // AgentCore requires tool-scoped policies to reference a specific Gateway ARN.
    // Construct the ARN from the gateway ID (L2 doesn't expose attrGatewayArn).
    const gatewayArn = `arn:aws:bedrock-agentcore:${this.region}:${this.account}:gateway/${gateway.gatewayId}`;

    statements.forEach((statement: string, i: number) => {
      const name = policyNames[i] || `policy_${i}`;
      // Replace generic resource type with the specific gateway resource
      const scopedStatement = statement.replace(
        /resource is AgentCore::Gateway/g,
        `resource == AgentCore::Gateway::"${gatewayArn}"`
      );
      const policy = new bedrockagentcore.CfnPolicy(
        this,
        `Policy_${name}`,
        {
          name: `${prefix.replace(/-/g, "_")}_${name}`,
          policyEngineId: policyEngine.attrPolicyEngineId,
          definition: {
            cedar: { statement: scopedStatement },
          },
          description: `P2P Cedar policy: ${name.replace(/_/g, " ")}`,
        }
      );
      policy.addDependency(policyEngine);
      // Policies reference erp___ tool actions that only exist after the
      // GatewayTarget is created (tool registration happens at target creation).
      const targetL1 = gatewayTarget.node.defaultChild as cdk.CfnResource;
      if (targetL1) policy.addDependency(targetL1);
    });

    // Attach policy engine to Gateway via L1 escape hatch.
    // The L2 Gateway construct doesn't expose policyEngineConfiguration,
    // so we override the underlying CloudFormation property.
    const cfnGateway = gateway.node.defaultChild as bedrockagentcore.CfnGateway;
    cfnGateway.addPropertyOverride("PolicyEngineConfiguration", {
      Arn: policyEngine.attrPolicyEngineArn,
      Mode: "ENFORCE",
    });

    // Grant the Gateway's service role permission to access the PolicyEngine.
    // The Gateway calls AuthorizeAction on its own ARN during creation when
    // a PolicyEngine is attached. We must grant on both the policy engine
    // and all gateway resources in the account.
    const gatewayRole = gateway.node.findChild("ServiceRole") as iam.IRole;
    // Per AWS docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-permissions.html
    // Gateway execution role needs these 3 actions for Policy Engine integration.
    const policyGrant = gatewayRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        sid: "PolicyEngineConfiguration",
        actions: ["bedrock-agentcore:GetPolicyEngine"],
        resources: [policyEngine.attrPolicyEngineArn],
      })
    );
    gatewayRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        sid: "PolicyEngineAuthorization",
        actions: [
          "bedrock-agentcore:AuthorizeAction",
          "bedrock-agentcore:PartiallyAuthorizeActions",
        ],
        resources: [
          policyEngine.attrPolicyEngineArn,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:gateway/*`,
        ],
      })
    );

    // Ensure the IAM policy is fully created before the Gateway tries to use it.
    // Without this, CloudFormation may create the Gateway before the policy propagates.
    if (policyGrant.policyDependable) {
      cfnGateway.node.addDependency(policyGrant.policyDependable);
    }
    // Also ensure the PolicyEngine itself exists before Gateway references it
    cfnGateway.addDependency(policyEngine);

    // SNS topic for Cedar policy deny alerts — subscribe admin email post-deploy
    const cedarDenyTopic = new sns.Topic(this, "CedarDenyTopic", {
      topicName: `${prefix}-cedar-deny-alerts`,
      displayName: "P2P Cedar Policy Deny Alerts",
    });

    // =====================================================================
    // AgentCore Memory
    // =====================================================================

    const memoryRole = new iam.Role(this, "MemoryRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
      inlinePolicies: {
        memory: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              actions: [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
              ],
              resources: ["*"],
            }),
          ],
        }),
      },
    });

    const memory = new bedrockagentcore.CfnMemory(this, "P2PMemory", {
      name: `${prefix.replace(/-/g, "_")}_memory`,
      memoryExecutionRoleArn: memoryRole.roleArn,
      eventExpiryDuration: 30, // 30 days
      memoryStrategies: [
        {
          summaryMemoryStrategy: {
            name: "ConversationContext",
            description: "Summarize procurement conversation context",
            namespaces: ["/conversations/{sessionId}"],
          },
        },
        {
          semanticMemoryStrategy: {
            name: "ProcurementFacts",
            description: "Store procurement facts and decisions",
            namespaces: ["/procurement"],
          },
        },
      ],
    });

    // =====================================================================
    // AgentCore CodeInterpreter (spend analytics)
    // =====================================================================

    const codeInterpreter = new agentcore.CodeInterpreterCustom(
      this,
      "P2PCodeInterpreter",
      {
        codeInterpreterCustomName: `${prefix.replace(/-/g, "_")}_code_interpreter`,
        description: "Python sandbox for spend analytics and visualization",
        networkConfiguration:
          agentcore.CodeInterpreterNetworkConfiguration.usingPublicNetwork(),
      }
    );

    // =====================================================================
    // Bedrock Guardrail (Automated Reasoning)
    // =====================================================================

    const guardrail = new bedrock.CfnGuardrail(this, "ProcurementGuardrail", {
      name: `${prefix}-procurement-reasoning`,
      description:
        "Automated Reasoning guardrail for P2P procurement. " +
        "Validates agent recommendations against formal business rules: " +
        "three-way matching, approval thresholds, payment rules, supplier rules.",
      blockedInputMessaging:
        "This request cannot be processed as it violates procurement policy.",
      blockedOutputsMessaging:
        "The agent's recommendation was flagged by automated reasoning " +
        "as potentially inconsistent with procurement policy. Please review.",
      // Bedrock requires at least one policy. Use a minimal sensitive-info policy
      // as the base. The Automated Reasoning policy is added via console after deploy.
      sensitiveInformationPolicyConfig: {
        piiEntitiesConfig: [
          { type: "US_SOCIAL_SECURITY_NUMBER", action: "BLOCK" },
          { type: "CREDIT_DEBIT_CARD_NUMBER", action: "BLOCK" },
        ],
      },
    });

    // =====================================================================
    // AgentCore Runtimes (7 agents)
    // =====================================================================

    // AgentCore Runtimes — all share the same ECR image, AGENT_NAME env var selects behavior
    const AGENTS: Record<string, string> = {
      requisition: "Requisition",
      sourcing: "Sourcing",
      po_management: "PO_Management",
      receiving: "Receiving",
      invoice_matching: "Invoice_Matching",
      payment: "Payment",
      workflow: "Workflow",
    };

    const runtimeArns: Record<string, string> = {};

    for (const [name, label] of Object.entries(AGENTS)) {
      const runtime = new agentcore.Runtime(this, `${label}Runtime`, {
        runtimeName: `${prefix.replace(/-/g, "_")}_${name}`,
        agentRuntimeArtifact:
          agentArtifact,
        authorizerConfiguration:
          agentcore.RuntimeAuthorizerConfiguration.usingIAM(),
        networkConfiguration:
          agentcore.RuntimeNetworkConfiguration.usingPublicNetwork(),
        environmentVariables: {
          AGENT_NAME: name,
          BEDROCK_MODEL_ID: "us.anthropic.claude-sonnet-4-6",
          AWS_REGION_NAME: this.region,
          BEDROCK_AGENTCORE_MEMORY_ID: memory.attrMemoryId,
          DYNAMODB_TABLE_PREFIX: prefix,
          BEDROCK_GUARDRAIL_ID: guardrail.attrGuardrailId,
          BEDROCK_GUARDRAIL_VERSION: "DRAFT",
          ERPNEXT_SECRET_ARN: erpnextSecret.secretArn,
          ERPNEXT_URL: props.erpnextUrl,
          GATEWAY_ENDPOINT: `https://${gateway.gatewayId}.gateway.bedrock-agentcore.${cdk.Stack.of(this).region}.amazonaws.com/mcp`,
        },
        description: `P2P ${label} Agent`,
      });

      // Grant ECR pull for each runtime (fromImageUri doesn't auto-grant)
      agentImage.repository.grantPull(runtime.role);

      // Grant permissions
      gateway.grantRead(runtime);
      codeInterpreter.grantUse(runtime);
      // Runtimes only need lifecycle table (runs[] tracking)
      lifecycleTable.grantReadWriteData(runtime);
      erpnextSecret.grantRead(runtime);

      // Grant Bedrock model invocation
      runtime.addToRolePolicy(
        new iam.PolicyStatement({
          actions: [
            "bedrock:InvokeModel",
            "bedrock:InvokeModelWithResponseStream",
            "bedrock:ApplyGuardrail",
          ],
          resources: ["*"],
        })
      );

      // Grant memory access
      runtime.addToRolePolicy(
        new iam.PolicyStatement({
          actions: [
            "bedrock-agentcore:GetWorkloadAccessToken",
            "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
            "bedrock-agentcore:InvokeMemory",
          ],
          resources: ["*"],
        })
      );

      // Grant Gateway invocation (MCP tools)
      runtime.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ["bedrock-agentcore:InvokeGateway"],
          resources: [gateway.gatewayArn],
        })
      );

      runtimeArns[name] = runtime.agentRuntimeArn;
    }

    // =====================================================================
    // Backend API Lambda (FastAPI — dashboard, decisions, notifications)
    // =====================================================================

    const apiLambda = new lambda.Function(this, "ApiLambda", {
      functionName: `${prefix}-api`,
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "main.handler",
      code: lambda.Code.fromAsset("../backend", {
        bundling: {
          image: lambda.Runtime.PYTHON_3_13.bundlingImage,
          command: [
            "bash", "-c",
            "pip install -r requirements.txt -t /asset-output && cp -r . /asset-output",
          ],
        },
      }),
      timeout: cdk.Duration.seconds(120),
      memorySize: 1024,
      environment: {
        DATA_SOURCE: "erpnext",
        DYNAMODB_TABLE_PREFIX: prefix,
        COGNITO_USER_POOL_ID: userPool.userPoolId,
        COGNITO_APP_CLIENT_ID: frontendClient.userPoolClientId,
        AWS_REGION_NAME: this.region,
        BEDROCK_MODEL_ID: "us.anthropic.claude-sonnet-4-6",
        ERPNEXT_URL: props.erpnextUrl,
        ERPNEXT_SECRET_ARN: erpnextSecret.secretArn,
        BEDROCK_GUARDRAIL_ID: guardrail.attrGuardrailId,
        BEDROCK_GUARDRAIL_VERSION: "DRAFT",
        // Fix OpenTelemetry StopIteration in Lambda ZIP packaging
        OTEL_PYTHON_CONTEXT: "contextvars_context",
        // ADAPTER_API_URL is set after httpApi is created (see addEnvironment below)
        ...Object.fromEntries(
          Object.entries(runtimeArns).map(([k, v]) => [
            `AGENTCORE_${k.toUpperCase()}_ARN`,
            v,
          ])
        ),
      },
    });

    invoiceJobsTable.grantReadWriteData(apiLambda);
    apiLambda.addEnvironment("INVOICE_JOBS_TABLE", invoiceJobsTable.tableName);
    chatSessionsTable.grantReadWriteData(apiLambda);
    // decisionsTable removed — using lifecycle table for all decisions
    lifecycleTable.grantReadWriteData(apiLambda);
    erpnextSecret.grantRead(apiLambda);
    // AgentCore Memory for chat message persistence
    apiLambda.addEnvironment("BEDROCK_AGENTCORE_MEMORY_ID", memory.attrMemoryId);

    apiLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:ApplyGuardrail",
          "lambda:InvokeFunction",
        ],
        resources: ["*"],
      })
    );

    // Textract for invoice PDF extraction (Upload Invoice flow)
    apiLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["textract:AnalyzeExpense", "textract:AnalyzeDocument"],
        resources: ["*"],
      })
    );

    // Chat agent needs MCP Gateway access for ERP tools
    apiLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock-agentcore:InvokeGateway"],
        resources: [gatewayArn],
      })
    );

    // AgentCore Memory for chat message persistence
    apiLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "bedrock-agentcore:CreateEvent",
          "bedrock-agentcore:ListEvents",
          "bedrock-agentcore:DeleteEvent",
        ],
        resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:memory/*`],
      })
    );

    // =====================================================================
    // Domain config (used by API Gateway CORS and CloudFront)
    // =====================================================================

    const hostedZoneName = this.node.tryGetContext("hostedZoneName") as string | undefined;
    const frontendDomainPrefix = this.node.tryGetContext("frontendDomainPrefix") as string | undefined;
    const externalDns = (this.node.tryGetContext("externalDns") as boolean) || false;

    // Build frontend FQDN from context.
    // If frontendDomainPrefix is empty/undefined, use hostedZoneName as apex domain.
    // If frontendDomainPrefix is set (e.g. "aria"), use subdomain (e.g. aria.<hostedZoneName>).
    const frontendFqdn = hostedZoneName
      ? (frontendDomainPrefix ? `${frontendDomainPrefix}.${hostedZoneName}` : hostedZoneName)
      : undefined;

    // =====================================================================
    // API Gateway v2 (HTTP)
    // =====================================================================

    const httpApi = new apigwv2.HttpApi(this, "HttpApi", {
      apiName: `${prefix}-api`,
      corsPreflight: {
        allowOrigins: [
          "http://localhost:5173",
          "http://localhost:5174",
          ...(frontendFqdn ? [`https://${frontendFqdn}`] : []),
        ],
        allowMethods: [
          apigwv2.CorsHttpMethod.GET,
          apigwv2.CorsHttpMethod.POST,
          apigwv2.CorsHttpMethod.PUT,
          apigwv2.CorsHttpMethod.DELETE,
          apigwv2.CorsHttpMethod.OPTIONS,
        ],
        allowHeaders: ["Authorization", "Content-Type", "x-p2p-user-email"],
        maxAge: cdk.Duration.hours(1),
      },
    });

    const jwtAuthorizer = new apigwv2_authorizers.HttpJwtAuthorizer(
      "JwtAuth",
      `https://cognito-idp.${this.region}.amazonaws.com/${userPool.userPoolId}`,
      {
        jwtAudience: [frontendClient.userPoolClientId],
      }
    );

    const lambdaIntegration = new apigwv2_integrations.HttpLambdaIntegration(
      "ApiIntegration",
      apiLambda
    );

    const adapterIntegration = new apigwv2_integrations.HttpLambdaIntegration(
      "AdapterIntegration",
      adapterLambda
    );

    // ERP data routes → Adapter Lambda (canonical P2P API → ERPNext)
    // No JWT: also called by API Lambda and Simulation Lambda (server-to-server).
    // Protected by: CloudFront WAF + per-user ERPNext API keys in Secrets Manager.
    httpApi.addRoutes({
      path: "/api/erp/{proxy+}",
      methods: [apigwv2.HttpMethod.ANY],
      integration: adapterIntegration,
    });

    // All other API routes → API Lambda (agents, decisions, config)
    httpApi.addRoutes({
      path: "/{proxy+}",
      methods: [apigwv2.HttpMethod.ANY],
      integration: lambdaIntegration,
      authorizer: jwtAuthorizer,
    });

    // Health check — no auth
    httpApi.addRoutes({
      path: "/api/health",
      methods: [apigwv2.HttpMethod.GET],
      integration: lambdaIntegration,
    });

    // Wire API Lambda to adapter API (must be after httpApi creation)
    apiLambda.addEnvironment(
      "ADAPTER_API_URL",
      `https://${httpApi.httpApiId}.execute-api.${this.region}.amazonaws.com/api/erp`
    );

    // Wire API Lambda to AgentCore MCP Gateway (for chat agent ERP tools)
    apiLambda.addEnvironment(
      "GATEWAY_ENDPOINT",
      `https://${gateway.gatewayId}.gateway.bedrock-agentcore.${this.region}.amazonaws.com/mcp`
    );

    // =====================================================================
    // WAFv2 WebACL (CloudFront)
    // =====================================================================

    const webAcl = new wafv2.CfnWebACL(this, "CloudFrontWAF", {
      scope: "CLOUDFRONT",
      defaultAction: { allow: {} },
      name: `${prefix}-cloudfront-waf`,
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        metricName: `${prefix}-waf-cloudfront`,
        sampledRequestsEnabled: true,
      },
      rules: [
        {
          name: "AWSCommonRules",
          priority: 1,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: {
              vendorName: "AWS",
              name: "AWSManagedRulesCommonRuleSet",
            },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: `${prefix}-waf-common`,
            sampledRequestsEnabled: true,
          },
        },
        {
          name: "AWSIPReputation",
          priority: 2,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: {
              vendorName: "AWS",
              name: "AWSManagedRulesAmazonIpReputationList",
            },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: `${prefix}-waf-ip-reputation`,
            sampledRequestsEnabled: true,
          },
        },
        {
          name: "RateLimit",
          priority: 3,
          action: { block: {} },
          statement: {
            rateBasedStatement: {
              limit: 100,
              aggregateKeyType: "IP",
            },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: `${prefix}-waf-rate-limit`,
            sampledRequestsEnabled: true,
          },
        },
      ],
    });

    // =====================================================================
    // S3 + CloudFront + Custom Domain (Frontend — ARIA)
    // =====================================================================

    // Look up the hosted zone and create ACM certificate (if domain configured)
    let frontendCertificate: acm.ICertificate | undefined;
    let hostedZone: route53.IHostedZone | undefined;

    if (frontendFqdn && hostedZoneName) {
      if (externalDns) {
        // External DNS: ACM cert with manual DNS validation.
        // During deploy, CloudFormation will wait for certificate validation.
        // Check the ACM console for the CNAME records to add to your DNS provider.
        frontendCertificate = new acm.Certificate(this, "AriaCertificate", {
          domainName: frontendFqdn,
          validation: acm.CertificateValidation.fromDns(),
        });
      } else {
        // Route53-managed DNS: auto-create validation records
        hostedZone = route53.HostedZone.fromLookup(this, "HostedZone", {
          domainName: hostedZoneName,
        });

        frontendCertificate = new acm.Certificate(this, "AriaCertificate", {
          domainName: frontendFqdn,
          validation: acm.CertificateValidation.fromDns(hostedZone),
        });
      }
    }

    const frontendBucket = new s3.Bucket(this, "FrontendBucket", {
      bucketName: `${prefix}-frontend-${this.account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const distribution = new cloudfront.Distribution(this, "Distribution", {
      webAclId: webAcl.attrArn,
      ...(frontendFqdn && frontendCertificate ? {
        domainNames: [frontendFqdn],
        certificate: frontendCertificate,
      } : {}),
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(frontendBucket),
        viewerProtocolPolicy:
          cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      },
      additionalBehaviors: {
        "/api/*": {
          origin: new origins.HttpOrigin(
            `${httpApi.httpApiId}.execute-api.${this.region}.amazonaws.com`
          ),
          viewerProtocolPolicy:
            cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy:
            cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
      },
      defaultRootObject: "index.html",
      errorResponses: [
        {
          httpStatus: 403,
          responseHttpStatus: 200,
          responsePagePath: "/index.html",
        },
        {
          httpStatus: 404,
          responseHttpStatus: 200,
          responsePagePath: "/index.html",
        },
      ],
    });

    // Route53 alias record → CloudFront (only when DNS is managed by Route53)
    if (frontendFqdn && hostedZone) {
      new route53.ARecord(this, "AriaAliasRecord", {
        zone: hostedZone,
        recordName: frontendFqdn,
        target: route53.RecordTarget.fromAlias(
          new route53Targets.CloudFrontTarget(distribution)
        ),
      });
    }

    // When using external DNS, output the CloudFront domain so operator can
    // create a CNAME/ALIAS record at their DNS provider.
    if (frontendFqdn && externalDns) {
      new cdk.CfnOutput(this, "ExternalDnsTarget", {
        value: distribution.distributionDomainName,
        description: `Create a CNAME or ALIAS record: ${frontendFqdn} → this value`,
      });
    }

    // =====================================================================
    // Simulation Engine (EventBridge + Lambda + DynamoDB)
    // =====================================================================

    const simulationTable = new dynamodb.Table(this, "SimulationState", {
      tableName: `${prefix}-simulation-state`,
      partitionKey: {
        name: "scenario_id",
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "ttl",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const simulationLambda = new lambda.Function(this, "SimulationLambda", {
      functionName: `${prefix}-simulation`,
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "simulation.lambda_handler.handler",
      code: lambda.Code.fromAsset("../utilities", {
        bundling: {
          image: lambda.Runtime.PYTHON_3_13.bundlingImage,
          command: [
            "bash",
            "-c",
            "pip install requests faker boto3 python-dotenv -t /asset-output && cp -r . /asset-output",
          ],
        },
      }),
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      environment: {
        SIMULATION_TABLE: simulationTable.tableName,
        CANONICAL_API_URL: `https://${httpApi.httpApiId}.execute-api.${this.region}.amazonaws.com/api/erp`,
        AWS_REGION_NAME: this.region,
        SIMULATION_USE_LLM: "true",
        // Configurable delays for event scanner (hours)
        SIM_MIN_SHIPPING_HOURS: "0",
        SIM_MAX_SHIPPING_HOURS: "1",
        SIM_MIN_BILLING_HOURS: "0",
        SIM_MAX_BILLING_HOURS: "1",
        ...Object.fromEntries(
          Object.entries(runtimeArns).map(([k, v]) => [
            `AGENTCORE_${k.toUpperCase()}_ARN`,
            v,
          ])
        ),
      },
    });

    simulationTable.grantReadWriteData(simulationLambda);
    adapterLambda.grantInvoke(simulationLambda);

    simulationLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock-agentcore:InvokeAgentRuntime"],
        resources: ["*"],
      })
    );

    // Bedrock for LLM-powered document generation
    simulationLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: ["*"],
      })
    );

    // S3 for PDF invoice upload
    simulationLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["s3:PutObject"],
        resources: [`arn:aws:s3:::${prefix}-documents/*`],
      })
    );

    // ── EventBridge Rule 1: Demand Generator (every 6 hours) ────────────────
    // Creates 1-3 Material Requests from random requesters.
    // Starts DISABLED — enable for demo with: aws events enable-rule --name p2p-dev-demand-generator
    const demandRule = new events.Rule(this, "DemandGenerator", {
      ruleName: `${prefix}-demand-generator`,
      schedule: events.Schedule.rate(cdk.Duration.hours(6)),
      enabled: false,
      targets: [
        new targets.LambdaFunction(simulationLambda, {
          event: events.RuleTargetInput.fromObject({ mode: "demand" }),
        }),
      ],
    });

    // ── EventBridge Rule 2: GR Scanner (every 30 minutes) ────────────────────
    // Scans for POs needing Purchase Receipts (goods delivery simulation).
    // Starts DISABLED — enable: aws events enable-rule --name p2p-dev-gr-scanner
    new events.Rule(this, "GRScanner", {
      ruleName: `${prefix}-gr-scanner`,
      schedule: events.Schedule.rate(cdk.Duration.minutes(30)),
      enabled: false,
      targets: [
        new targets.LambdaFunction(simulationLambda, {
          event: events.RuleTargetInput.fromObject({ mode: "scan_receipts" }),
        }),
      ],
    });

    // ── EventBridge Rule 3: Invoice Scanner (every 90 minutes) ─────────────
    // Scans for POs needing Invoices (vendor billing simulation).
    // Starts DISABLED — enable: aws events enable-rule --name p2p-dev-invoice-scanner
    new events.Rule(this, "InvoiceScanner", {
      ruleName: `${prefix}-invoice-scanner`,
      schedule: events.Schedule.rate(cdk.Duration.minutes(90)),
      enabled: false,
      targets: [
        new targets.LambdaFunction(simulationLambda, {
          event: events.RuleTargetInput.fromObject({ mode: "scan_invoices" }),
        }),
      ],
    });

    // =====================================================================
    // Outputs
    // =====================================================================

    new cdk.CfnOutput(this, "CognitoUserPoolId", {
      value: userPool.userPoolId,
    });
    new cdk.CfnOutput(this, "CognitoClientId", {
      value: frontendClient.userPoolClientId,
    });
    new cdk.CfnOutput(this, "CognitoDomain", {
      value: cognitoDomain.domainName,
    });
    new cdk.CfnOutput(this, "CognitoIdentityPoolId", {
      value: identityPool.ref,
    });
    new cdk.CfnOutput(this, "ERPNextSSOClientId", {
      value: erpnextSsoClient.userPoolClientId,
      description: "Cognito app client ID for ERPNext Social Login (confidential, with secret)",
    });
    new cdk.CfnOutput(this, "ApiUrl", {
      value: httpApi.url || "",
    });
    new cdk.CfnOutput(this, "CloudFrontUrl", {
      value: `https://${distribution.distributionDomainName}`,
    });
    new cdk.CfnOutput(this, "FrontendBucketName", {
      value: frontendBucket.bucketName,
    });
    new cdk.CfnOutput(this, "GatewayId", {
      value: gateway.gatewayId,
    });
    new cdk.CfnOutput(this, "MemoryId", {
      value: memory.attrMemoryId,
    });
    new cdk.CfnOutput(this, "AgentImageBuilt", {
      value: "true",
      description: "Agent container image built from backend/ via CDK DockerImageAsset",
    });

    for (const [name, arn] of Object.entries(runtimeArns)) {
      new cdk.CfnOutput(this, `AgentCore${name}Arn`, { value: arn });
    }
    new cdk.CfnOutput(this, "GuardrailId", {
      value: guardrail.attrGuardrailId,
    });
    new cdk.CfnOutput(this, "PolicyEngineId", {
      value: policyEngine.attrPolicyEngineId,
    });
    new cdk.CfnOutput(this, "SimulationTableName", {
      value: simulationTable.tableName,
    });
    new cdk.CfnOutput(this, "SimulationLambdaArn", {
      value: simulationLambda.functionArn,
    });

    // =====================================================================
    // Frontend: build + deploy to S3 + runtime config
    // =====================================================================

    // Frontend is built locally and deployed via `npm run build && aws s3 sync`.
    // CDK writes a .env.production file with the correct values, then a deploy
    // script (or manual step) builds and uploads.
    // See: scripts/deploy-frontend.sh

    // =====================================================================
    // Tags
    // =====================================================================

    cdk.Tags.of(this).add("Project", "p2p-agentic-erp");
    cdk.Tags.of(this).add("Component", "agentic-platform");
    cdk.Tags.of(this).add("Environment", "dev");
  }
}

export interface P2PAgenticStackProps extends cdk.StackProps {
  erpnextUrl: string;
  /** ALB DNS name for internal VPC access (Lambda → ALB, avoids public IP routing). */
  erpnextInternalUrl?: string;
}
