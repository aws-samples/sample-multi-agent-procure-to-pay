#!/usr/bin/env node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { ErpNextStack } from "../lib/erpnext-stack";
import { P2PAgenticStack } from "../lib/p2p-agentic-stack";

const app = new cdk.App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || "us-east-1",
};

// Stack 1: ERPNext on EC2 (already deployed)
const erpStack = new ErpNextStack(app, "ErpNextStack", {
  env,
  description:
    "ERPNext open-source ERP deployed on EC2 with docker-compose for P2P agentic workflow integration",
});

// Stack 2: ARIA — Agentic Requisition-to-Payment Intelligent Automation
new P2PAgenticStack(app, "P2PAgenticStack", {
  env,
  description:
    "ARIA platform — AgentCore runtimes, Gateway, Cedar Policy, CodeInterpreter, WAF",
  erpnextUrl: cdk.Fn.importValue("ErpNextURL"),
  erpnextInternalUrl: cdk.Fn.importValue("ErpNextInternalURL"),
});
