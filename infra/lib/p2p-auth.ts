// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import * as cdk from "aws-cdk-lib";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";

/**
 * Cognito Group names, most privileged first. This is the ONLY source of a
 * user's P2P role: membership can be changed solely through admin APIs
 * (AdminAddUserToGroup), and the Pre Token Generation trigger turns it into
 * the `p2p_role` claim that the Cedar policies and the frontend evaluate.
 * Keep in sync with ROLE_PRECEDENCE in lambda/pre_token_generation/handler.py.
 */
export const P2P_ROLE_GROUPS = [
  "admin",
  "procurement",
  "approver",
  "ap_clerk",
  "executive",
  "requester",
] as const;

export interface P2PAuthProps {
  /** Resource name prefix, e.g. "p2p-dev". */
  readonly prefix: string;
  /** ERPNext base URL, used for the SSO client's OAuth callback. */
  readonly erpnextUrl: string;
  /** Deployed frontend FQDN (adds https callback/logout URLs when set). */
  readonly frontendFqdn?: string;
}

/**
 * Cognito user pool, app clients, groups, hosted domain, and the
 * Pre Token Generation trigger for the P2P platform.
 *
 * Authorization design: a user's role must never be something the user can
 * write. Two independent controls enforce that:
 *
 *  1. Both app clients set an explicit `writeAttributes` list of display-only
 *     standard attributes. Cognito's default is "every attribute the pool
 *     defines", which would make `custom:role` self-writable via
 *     UpdateUserAttributes.
 *  2. The role claim (`p2p_role`) is asserted server-side by a V2 Pre Token
 *     Generation trigger from Cognito Group membership, on both the ID and
 *     access tokens, and the `custom:role` claim is suppressed. Nothing
 *     downstream reads `custom:role`.
 *
 * Deployed on its own by P2PAuthE2EStack so the live behaviour can be tested
 * end to end (infra/tests/e2e) without the rest of the platform.
 */
export class P2PAuth extends Construct {
  public readonly userPool: cognito.UserPool;
  public readonly frontendClient: cognito.UserPoolClient;
  public readonly erpnextSsoClient: cognito.UserPoolClient;
  public readonly cognitoDomain: cognito.UserPoolDomain;
  public readonly preTokenLambda: lambda.Function;

  constructor(scope: Construct, id: string, props: P2PAuthProps) {
    super(scope, id);

    const { prefix, erpnextUrl, frontendFqdn } = props;
    const account = cdk.Stack.of(this).account;

    // Pre Token Generation trigger: derives the authoritative `p2p_role` claim
    // from Cognito Group membership (operator-controlled) and strips the
    // user-writable custom:role attribute from the tokens.
    this.preTokenLambda = new lambda.Function(this, "PreTokenGenerationLambda", {
      functionName: `${prefix}-pre-token-generation`,
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "handler.handler",
      code: lambda.Code.fromAsset("lambda/pre_token_generation"),
      timeout: cdk.Duration.seconds(5),
      memorySize: 128,
      description: "Asserts p2p_role claim from Cognito Group membership",
    });

    this.userPool = new cognito.UserPool(this, "UserPool", {
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
        // Informational only. Authorization is keyed on Cognito Group
        // membership (see PreTokenGeneration trigger), never on these.
        role: new cognito.StringAttribute({ maxLen: 50 }),
        department: new cognito.StringAttribute({ maxLen: 100 }),
      },
      // Essentials is Cognito's default plan for new pools; set explicitly
      // because the V2 pre-token trigger (access token customization) needs it.
      featurePlan: cognito.FeaturePlan.ESSENTIALS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // V2_0 so the p2p_role claim is stamped on BOTH the ID and access tokens.
    // A gateway configured for Cognito JWT inbound auth may validate either
    // token, so both must carry the asserted role.
    this.userPool.addTrigger(
      cognito.UserPoolOperation.PRE_TOKEN_GENERATION_CONFIG,
      this.preTokenLambda,
      cognito.LambdaVersion.V2_0
    );

    // Attributes an end user may write about themselves through either app
    // client. Custom attributes are deliberately excluded; operators set them
    // with AdminUpdateUserAttributes, which this list does not restrict.
    const userWritableAttributes = new cognito.ClientAttributes().withStandardAttributes({
      givenName: true,
      familyName: true,
      fullname: true,
      locale: true,
      timezone: true,
    });

    const localUrls = ["http://localhost:5173/", "http://localhost:5174/"];
    const frontendUrls = [...localUrls, ...(frontendFqdn ? [`https://${frontendFqdn}/`] : [])];

    this.frontendClient = this.userPool.addClient("FrontendClient", {
      userPoolClientName: `${prefix}-frontend`,
      authFlows: { userSrp: true },
      writeAttributes: userWritableAttributes,
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.PROFILE,
        ],
        callbackUrls: frontendUrls,
        logoutUrls: frontendUrls,
      },
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(30),
      generateSecret: false,
    });

    // ERPNext SSO client — confidential (with secret) for server-side OAuth2 flow
    this.erpnextSsoClient = this.userPool.addClient("ERPNextSSOClient", {
      userPoolClientName: `${prefix}-erpnext-sso`,
      generateSecret: true,
      authFlows: { userSrp: true },
      writeAttributes: userWritableAttributes,
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.PROFILE,
        ],
        callbackUrls: [
          `${erpnextUrl}/api/method/frappe.integrations.oauth2_logins.custom/amazon_cognito`,
        ],
        logoutUrls: [erpnextUrl],
      },
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(30),
    });

    this.cognitoDomain = this.userPool.addDomain("CognitoDomain", {
      cognitoDomain: {
        domainPrefix: `${prefix}-${account}`,
      },
    });

    for (const group of P2P_ROLE_GROUPS) {
      new cognito.CfnUserPoolGroup(this, `Group_${group}`, {
        userPoolId: this.userPool.userPoolId,
        groupName: group,
        description: `P2P ${group} role`,
      });
    }
  }
}
