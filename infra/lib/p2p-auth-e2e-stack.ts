// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as agentcore from "@aws-cdk/aws-bedrock-agentcore-alpha";
import { Construct } from "constructs";
import { P2PAuth } from "./p2p-auth";
import { P2PToolPolicyEngine, CEDAR_POLICY_FILE, cedarToolNames } from "./p2p-policy";

export interface P2PAuthE2EStackProps extends cdk.StackProps {
  /** Resource name prefix. Must differ from the main stack's "p2p-dev". */
  readonly prefix?: string;
}

/**
 * Minimal, self-contained deployment for end-to-end verification of the role
 * authorization design. Deploys ONLY:
 *
 *  - The production Cognito configuration (P2PAuth: pool, app clients with
 *    restricted writeAttributes, groups, V2 pre-token trigger).
 *  - An AgentCore Gateway with Cognito JWT inbound auth (so callers are
 *    `AgentCore::OAuthUser` principals and the Gateway maps JWT claims to
 *    Cedar tags exactly as it would in a JWT-authenticated production gateway).
 *  - A stub Lambda target that registers the same `erp___*` tool names the
 *    real adapter exposes and echoes the call instead of touching an ERP.
 *  - The production Cedar policies (P2PToolPolicyEngine) in ENFORCE mode.
 *
 * No VPC, ERPNext, agents, API, or frontend. infra/tests/e2e/run_e2e.py drives
 * the checks against this stack: attempt to self-update custom:role,
 * re-authenticate, call erp___create_payment through the Gateway with the
 * user's own token.
 *
 * Deploy:  cd infra && npx cdk deploy P2PAuthE2EStack
 * Destroy: cd infra && npx cdk destroy P2PAuthE2EStack
 */
export class P2PAuthE2EStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: P2PAuthE2EStackProps = {}) {
    super(scope, id, props);

    const prefix = props.prefix ?? "p2p-e2e";

    const auth = new P2PAuth(this, "Auth", {
      prefix,
      erpnextUrl: "https://erpnext.invalid",
    });

    // Stub target: the Gateway only needs tools with these names registered
    // for the Cedar actions to be valid. Echo the tool call back so the test
    // can tell "authorized and executed" apart from "denied by policy".
    const stubTarget = new lambda.Function(this, "StubErpTarget", {
      functionName: `${prefix}-stub-erp-target`,
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "index.handler",
      timeout: cdk.Duration.seconds(10),
      code: lambda.Code.fromInline(
        [
          "import json",
          "def handler(event, context):",
          "    ctx = getattr(context, 'client_context', None)",
          "    custom = getattr(ctx, 'custom', None) or {}",
          "    tool = custom.get('bedrockAgentCoreToolName', 'unknown')",
          "    return {'statusCode': 200, 'body': json.dumps({'stub': True, 'tool': tool, 'input': event})}",
        ].join("\n")
      ),
    });

    const gateway = new agentcore.Gateway(this, "Gateway", {
      gatewayName: `${prefix}-gateway`,
      description: "E2E gateway for role authorization tests (Cognito JWT inbound auth)",
      protocolConfiguration: agentcore.GatewayProtocol.mcp({
        supportedVersions: [agentcore.MCPProtocolVersion.MCP_2025_06_18],
        searchType: agentcore.McpGatewaySearchType.SEMANTIC,
        instructions: "Stub P2P tools for authorization testing. No ERP is attached.",
      }),
      authorizerConfiguration: agentcore.GatewayAuthorizer.usingCognito({
        userPool: auth.userPool,
        allowedClients: [auth.frontendClient],
      }),
    });

    // Same tool names as the production target so the production policy file
    // applies unchanged. Schemas are permissive; the stub ignores arguments.
    const tools = cedarToolNames(CEDAR_POLICY_FILE).map((name) => ({
      name,
      description: `Stub for ${name}`,
      inputSchema: { type: agentcore.SchemaDefinitionType.OBJECT, properties: {} },
    }));

    const gatewayTarget = gateway.addLambdaTarget("StubErp", {
      gatewayTargetName: "erp",
      description: "Stub ERP adapter for E2E authorization tests",
      lambdaFunction: stubTarget,
      toolSchema: agentcore.ToolSchema.fromInline(tools),
    });

    // OAuth gateway: AgentCore rejects IamEntity policies here, so load only
    // the OAuthUser statements, which are the ones under test.
    new P2PToolPolicyEngine(this, "ToolPolicy", {
      prefix,
      gateway,
      gatewayTarget,
      principalTypes: ["OAuthUser"],
    });

    new cdk.CfnOutput(this, "CognitoUserPoolId", { value: auth.userPool.userPoolId });
    new cdk.CfnOutput(this, "CognitoClientId", { value: auth.frontendClient.userPoolClientId });
    new cdk.CfnOutput(this, "GatewayId", { value: gateway.gatewayId });
    new cdk.CfnOutput(this, "GatewayUrl", {
      value: `https://${gateway.gatewayId}.gateway.bedrock-agentcore.${this.region}.amazonaws.com/mcp`,
    });
    new cdk.CfnOutput(this, "PreTokenLambdaName", { value: auth.preTokenLambda.functionName });
  }
}
