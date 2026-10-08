// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore";
import * as agentcore from "@aws-cdk/aws-bedrock-agentcore-alpha";
import * as fs from "fs";
import { Construct } from "constructs";

/** Policy file shared by every deployment, relative to the infra/ directory. */
export const CEDAR_POLICY_FILE = "policies/p2p-procurement.cedar";

/** Names for the statements in CEDAR_POLICY_FILE, in file order. */
const POLICY_NAMES = [
  "iam_full_access",
  "oauth_read_access",
  "requisition_write",
  "po_receipt_write",
  "invoice_write",
  "payment_write",
];

export interface CedarStatement {
  readonly name: string;
  readonly statement: string;
  /** Cedar principal type the statement is scoped to. */
  readonly principalType: "IamEntity" | "OAuthUser";
}

/** Cedar statements from the policy file, comments stripped, in file order. */
export function loadCedarStatements(file: string = CEDAR_POLICY_FILE): CedarStatement[] {
  const raw = fs.readFileSync(file, "utf-8");
  const stripped = raw
    .split("\n")
    .filter((line: string) => !line.trimStart().startsWith("//"))
    .join("\n")
    .trim();
  return stripped
    .split(/(?=(?:permit|forbid)\()/)
    .map((s: string) => s.trim())
    .filter((s: string) => s.startsWith("permit") || s.startsWith("forbid"))
    .map((statement: string, i: number) => {
      const m = statement.match(/principal is AgentCore::(IamEntity|OAuthUser)/);
      if (!m) throw new Error(`Cedar statement ${i} has no recognised principal type`);
      return {
        name: POLICY_NAMES[i] || `policy_${i}`,
        statement,
        principalType: m[1] as "IamEntity" | "OAuthUser",
      };
    });
}

/** Every `erp___<tool>` action the policy file references, de-duplicated. */
export function cedarToolNames(file: string = CEDAR_POLICY_FILE): string[] {
  const raw = fs.readFileSync(file, "utf-8");
  const names = new Set<string>();
  for (const m of raw.matchAll(/erp___([a-z_]+)/g)) names.add(m[1]);
  return [...names];
}

export interface P2PToolPolicyEngineProps {
  /** Resource name prefix, e.g. "p2p-dev". */
  readonly prefix: string;
  /** Gateway the policies are scoped to and attached to (ENFORCE mode). */
  readonly gateway: agentcore.Gateway;
  /**
   * Target whose tools the policies reference. AgentCore validates actions
   * against the gateway's registered tools, so policies must be created after it.
   */
  readonly gatewayTarget: agentcore.GatewayTarget;
  /**
   * Principal types to load. AgentCore validates each policy against the
   * gateway's inbound authorizer: an OAuth/JWT gateway accepts only
   * `AgentCore::OAuthUser` policies and rejects `IamEntity` ones.
   * @default both (IAM-authenticated gateway)
   */
  readonly principalTypes?: ReadonlyArray<"IamEntity" | "OAuthUser">;
}

/**
 * AgentCore Policy Engine loaded with policies/p2p-procurement.cedar, one
 * CfnPolicy per statement, attached to the Gateway in ENFORCE mode.
 */
export class P2PToolPolicyEngine extends Construct {
  public readonly policyEngine: bedrockagentcore.CfnPolicyEngine;

  constructor(scope: Construct, id: string, props: P2PToolPolicyEngineProps) {
    super(scope, id);

    const { prefix, gateway, gatewayTarget } = props;
    const principalTypes = props.principalTypes ?? ["IamEntity", "OAuthUser"];
    const stack = cdk.Stack.of(this);
    const safePrefix = prefix.replace(/-/g, "_");

    this.policyEngine = new bedrockagentcore.CfnPolicyEngine(this, "PolicyEngine", {
      name: `${safePrefix}_policy`,
      description:
        "Cedar-based authorization for P2P procurement tools. " +
        "Enforces role-based access: read for all, write per role (p2p_role claim).",
    });

    // AgentCore requires tool-scoped policies to reference a specific Gateway ARN.
    // Construct the ARN from the gateway ID (L2 doesn't expose attrGatewayArn).
    const gatewayArn = `arn:aws:bedrock-agentcore:${stack.region}:${stack.account}:gateway/${gateway.gatewayId}`;
    const targetL1 = gatewayTarget.node.defaultChild as cdk.CfnResource;

    loadCedarStatements()
      .filter((s) => principalTypes.includes(s.principalType))
      .forEach(({ name, statement }) => {
        const scopedStatement = statement.replace(
          /resource is AgentCore::Gateway/g,
          `resource == AgentCore::Gateway::"${gatewayArn}"`
        );
        const policy = new bedrockagentcore.CfnPolicy(this, `Policy_${name}`, {
          name: `${safePrefix}_${name}`,
          policyEngineId: this.policyEngine.attrPolicyEngineId,
          definition: { cedar: { statement: scopedStatement } },
          description: `P2P Cedar policy: ${name.replace(/_/g, " ")}`,
        });
        policy.addDependency(this.policyEngine);
        if (targetL1) policy.addDependency(targetL1);
      });

    // Attach policy engine to Gateway via L1 escape hatch; the L2 Gateway
    // construct doesn't expose policyEngineConfiguration.
    const cfnGateway = gateway.node.defaultChild as bedrockagentcore.CfnGateway;
    cfnGateway.addPropertyOverride("PolicyEngineConfiguration", {
      Arn: this.policyEngine.attrPolicyEngineArn,
      Mode: "ENFORCE",
    });

    // Gateway execution role permissions for Policy Engine integration, per
    // https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-permissions.html
    const gatewayRole = gateway.node.findChild("ServiceRole") as iam.IRole;
    const policyGrant = gatewayRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        sid: "PolicyEngineConfiguration",
        actions: ["bedrock-agentcore:GetPolicyEngine"],
        resources: [this.policyEngine.attrPolicyEngineArn],
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
          this.policyEngine.attrPolicyEngineArn,
          `arn:aws:bedrock-agentcore:${stack.region}:${stack.account}:gateway/*`,
        ],
      })
    );

    // The Gateway calls AuthorizeAction on its own ARN during creation when a
    // PolicyEngine is attached, so the IAM policy and the engine must exist first.
    if (policyGrant.policyDependable) {
      cfnGateway.node.addDependency(policyGrant.policyDependable);
    }
    cfnGateway.addDependency(this.policyEngine);
  }
}
