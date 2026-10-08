#!/usr/bin/env node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Separate CDK app for the role-authorization end-to-end harness.
 *
 * Kept apart from bin/app.ts because the production app needs ERPNext context
 * (and a Docker build) just to construct, while this stack must be deployable
 * in any account with nothing else present.
 *
 *   npm run e2e:deploy    # cdk deploy via this app
 *   npm run e2e:destroy
 */
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { P2PAuthE2EStack } from "../lib/p2p-auth-e2e-stack";

const app = new cdk.App();

new P2PAuthE2EStack(app, "P2PAuthE2EStack", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || "us-east-1",
  },
  description: "ARIA role-authorization end-to-end test harness",
});
