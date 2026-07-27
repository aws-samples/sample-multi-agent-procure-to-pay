// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as rds from "aws-cdk-lib/aws-rds";
import * as elasticache from "aws-cdk-lib/aws-elasticache";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as route53_targets from "aws-cdk-lib/aws-route53-targets";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as elbv2_targets from "aws-cdk-lib/aws-elasticloadbalancingv2-targets";
import { Construct } from "constructs";

/**
 * ERPNext on EC2 with docker-compose, backed by managed RDS MariaDB + ElastiCache Redis.
 *
 * Uses cfn-init to bootstrap the instance:
 *   install Docker → write docker-compose.yaml + .env → docker compose up → bench new-site
 *
 * CloudFormation waits for cfn-signal before marking the instance CREATE_COMPLETE,
 * so the stack only succeeds if the full ERPNext site is up and healthy.
 */
export class ErpNextStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // =====================================================================
    // Context (from cdk.context.json)
    // =====================================================================

    const ctx = (key: string, fallback?: string): string => {
      const val = this.node.tryGetContext(key) as string | undefined;
      if (!val && !fallback)
        throw new Error(`Missing required context: "${key}". Set it in cdk.context.json`);
      return val || fallback!;
    };

    const hostedZoneName = this.node.tryGetContext("hostedZoneName") as string | undefined;
    const domainPrefix = this.node.tryGetContext("domainPrefix") as string | undefined;
    const externalDns = (this.node.tryGetContext("externalDns") as boolean) || false;
    const hasDomain = !!hostedZoneName && !!domainPrefix;
    const fqdn = hasDomain ? `${domainPrefix}.${hostedZoneName}` : undefined;

    // Passwords are required context values — no defaults. Generate strong values
    // (e.g. `openssl rand -base64 24`) and put them in cdk.context.json or pass via
    // --context erpnextAdminPassword=... --context dbRootPassword=...
    const erpnextAdminPwd = ctx("erpnextAdminPassword");
    const dbRootPwd = ctx("dbRootPassword");
    const erpnextImage = ctx("erpnextImage", "frappe/erpnext:v15");
    const instanceType = ctx("instanceType", "t3.large");
    const allowedCidr = ctx("allowedCidr", "0.0.0.0/0");

    const siteName = fqdn || "erp.localhost";

    // =====================================================================
    // VPC
    // =====================================================================

    const vpc = new ec2.Vpc(this, "Vpc", {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        { cidrMask: 24, name: "Public", subnetType: ec2.SubnetType.PUBLIC },
        { cidrMask: 24, name: "Private", subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      ],
    });

    // =====================================================================
    // Security Groups
    // =====================================================================

    const albSg = new ec2.SecurityGroup(this, "AlbSG", {
      vpc,
      description: "ALB - inbound HTTPS from allowed sources",
    });
    // Developer access only from allowed CIDR — Lambda reaches ALB via VPC (SG-to-SG rule added by P2PAgenticStack)
    albSg.addIngressRule(
      ec2.Peer.ipv4(allowedCidr),
      ec2.Port.tcp(443),
      "HTTPS from developer IP",
    );
    albSg.addIngressRule(
      ec2.Peer.ipv4(allowedCidr),
      ec2.Port.tcp(80),
      "HTTP redirect from developer IP",
    );
    // Amazon corporate network ranges (prefix list)
    const amazonCorpPl = ec2.Peer.prefixList("pl-60b85b09");
    albSg.addIngressRule(amazonCorpPl, ec2.Port.tcp(443), "HTTPS from Amazon corp");
    albSg.addIngressRule(amazonCorpPl, ec2.Port.tcp(80), "HTTP from Amazon corp");

    const ec2Sg = new ec2.SecurityGroup(this, "Ec2SG", {
      vpc,
      description: "EC2 ERPNext instance",
    });
    ec2Sg.addIngressRule(albSg, ec2.Port.tcp(8080), "ERPNext from ALB");

    const dbSg = new ec2.SecurityGroup(this, "DbSG", { vpc, description: "RDS MariaDB" });
    const redisSg = new ec2.SecurityGroup(this, "RedisSG", { vpc, description: "ElastiCache Redis" });

    dbSg.addIngressRule(ec2Sg, ec2.Port.tcp(3306), "MariaDB from EC2");
    redisSg.addIngressRule(ec2Sg, ec2.Port.tcp(6379), "Redis from EC2");

    // =====================================================================
    // RDS MariaDB (multi-AZ for HA)
    // =====================================================================

    const db = new rds.DatabaseInstance(this, "MariaDB", {
      engine: rds.DatabaseInstanceEngine.mariaDb({
        version: rds.MariaDbEngineVersion.VER_10_11_9,
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.SMALL),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [dbSg],
      credentials: rds.Credentials.fromPassword(
        "root",
        cdk.SecretValue.unsafePlainText(dbRootPwd),
      ),
      allocatedStorage: 20,
      maxAllocatedStorage: 50,
      multiAz: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      deletionProtection: false,
      parameterGroup: new rds.ParameterGroup(this, "MariaDBParams", {
        engine: rds.DatabaseInstanceEngine.mariaDb({
          version: rds.MariaDbEngineVersion.VER_10_11_9,
        }),
        parameters: {
          character_set_server: "utf8mb4",
          collation_server: "utf8mb4_unicode_ci",
          innodb_file_per_table: "1",
        },
      }),
    });

    // =====================================================================
    // ElastiCache Redis
    // =====================================================================

    const redisSubnetGroup = new elasticache.CfnSubnetGroup(this, "RedisSubnets", {
      description: "Redis subnet group",
      subnetIds: vpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }).subnetIds,
    });

    const redis = new elasticache.CfnCacheCluster(this, "Redis", {
      engine: "redis",
      cacheNodeType: "cache.t3.micro",
      numCacheNodes: 1,
      vpcSecurityGroupIds: [redisSg.securityGroupId],
      cacheSubnetGroupName: redisSubnetGroup.ref,
    });

    const redisAddr = redis.attrRedisEndpointAddress;
    const redisPort = redis.attrRedisEndpointPort;

    // =====================================================================
    // docker-compose.yaml content (official frappe_docker pattern,
    // Setup Example 2: external DB + Redis, no proxy, port 8080)
    // =====================================================================

    const composeYaml = `version: "3.8"

x-customizable-image: &customizable_image
  image: frappe/erpnext:\${ERPNEXT_VERSION}
  pull_policy: always
  restart: unless-stopped

x-depends-on-configurator: &depends_on_configurator
  depends_on:
    configurator:
      condition: service_completed_successfully

x-backend-defaults: &backend_defaults
  <<: [*depends_on_configurator, *customizable_image]
  volumes:
    - sites:/home/frappe/frappe-bench/sites

services:
  configurator:
    <<: *backend_defaults
    entrypoint: ["bash", "-c"]
    command:
      - >
        ls -1 apps > sites/apps.txt;
        bench set-config -g db_host \$\$DB_HOST;
        bench set-config -gp db_port \$\$DB_PORT;
        bench set-config -g redis_cache "redis://\$\$REDIS_CACHE";
        bench set-config -g redis_queue "redis://\$\$REDIS_QUEUE";
        bench set-config -g redis_socketio "redis://\$\$REDIS_QUEUE";
        bench set-config -gp socketio_port 9000;
    environment:
      DB_HOST: \${DB_HOST}
      DB_PORT: \${DB_PORT}
      REDIS_CACHE: \${REDIS_CACHE}
      // nosemgrep -- missing-template-string-indicator: literal string, no interpolation intended
      REDIS_QUEUE: \${REDIS_QUEUE}
    depends_on: {}
    restart: on-failure

  backend:
    <<: *backend_defaults

  frontend:
    <<: *customizable_image
    command: ["nginx-entrypoint.sh"]
    environment:
      BACKEND: backend:8000
      SOCKETIO: websocket:9000
      FRAPPE_SITE_NAME_HEADER: \${FRAPPE_SITE_NAME_HEADER:-\$\$host}
      UPSTREAM_REAL_IP_ADDRESS: 127.0.0.1
      UPSTREAM_REAL_IP_HEADER: X-Forwarded-For
      UPSTREAM_REAL_IP_RECURSIVE: "off"
      PROXY_READ_TIMEOUT: "120"
      CLIENT_MAX_BODY_SIZE: "50m"
    volumes:
      - sites:/home/frappe/frappe-bench/sites
    ports:
      - "8080:8080"
    depends_on:
      - backend
      - websocket

  websocket:
    <<: [*depends_on_configurator, *customizable_image]
    command: ["node", "/home/frappe/frappe-bench/apps/frappe/socketio.js"]
    volumes:
      - sites:/home/frappe/frappe-bench/sites

  queue-short:
    <<: *backend_defaults
    command: bench worker --queue short,default

  queue-long:
    <<: *backend_defaults
    command: bench worker --queue long,default,short

  scheduler:
    <<: *backend_defaults
    command: bench schedule

volumes:
  sites:
`;

    const envFileContent = [
      `ERPNEXT_VERSION=v15`,
      `DB_HOST=${db.dbInstanceEndpointAddress}`,
      `DB_PORT=3306`,
      `REDIS_CACHE=${redisAddr}:${redisPort}/0`,
      `REDIS_QUEUE=${redisAddr}:${redisPort}/1`,
      `FRAPPE_SITE_NAME_HEADER=${siteName}`,
    ].join("\n");

    // =====================================================================
    // EC2 Instance with cfn-init
    // =====================================================================

    const instance = new ec2.Instance(this, "ERPNext", {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroup: ec2Sg,
      instanceType: new ec2.InstanceType(instanceType),
      machineImage: ec2.MachineImage.latestAmazonLinux2023(),
      // Enforce IMDSv2 (require session token on every metadata request)
      requireImdsv2: true,
      blockDevices: [
        {
          deviceName: "/dev/xvda",
          volume: ec2.BlockDeviceVolume.ebs(30, { volumeType: ec2.EbsDeviceVolumeType.GP3 }),
        },
      ],
      init: ec2.CloudFormationInit.fromConfigSets({
        configSets: {
          default: ["install", "configure", "deploy"],
        },
        configs: {
          install: new ec2.InitConfig([
            ec2.InitPackage.yum("docker"),
            ec2.InitCommand.shellCommand(
              "systemctl enable docker && systemctl start docker",
              { key: "01-start-docker" },
            ),
            // Install docker-compose plugin v2
            ec2.InitCommand.shellCommand(
              [
                "mkdir -p /usr/local/lib/docker/cli-plugins",
                "curl -SL https://github.com/docker/compose/releases/download/v2.29.1/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose",
                "chmod +x /usr/local/lib/docker/cli-plugins/docker-compose",
              ].join(" && "),
              { key: "02-install-compose" },
            ),
          ]),
          configure: new ec2.InitConfig([
            ec2.InitCommand.shellCommand("mkdir -p /opt/erpnext", { key: "01-mkdir" }),
            ec2.InitFile.fromString("/opt/erpnext/docker-compose.yaml", composeYaml),
            ec2.InitFile.fromString("/opt/erpnext/.env", envFileContent),
          ]),
          deploy: new ec2.InitConfig([
            ec2.InitCommand.shellCommand(
              "cd /opt/erpnext && docker compose up -d",
              { key: "01-compose-up" },
            ),
            // Wait for configurator to complete and backend to be ready
            ec2.InitCommand.shellCommand(
              [
                "echo 'Waiting for backend to be ready...'",
                "for i in $(seq 1 60); do",
                "  docker compose -f /opt/erpnext/docker-compose.yaml ps backend 2>/dev/null | grep -q running && break",
                "  sleep 5",
                "done",
                "sleep 10",
              ].join("\n"),
              { key: "02-wait-backend" },
            ),
            ec2.InitCommand.shellCommand(
              `cd /opt/erpnext && docker compose exec -T backend bench new-site "${siteName}" --mariadb-user-host-login-scope=% --db-root-password "${dbRootPwd}" --admin-password "${erpnextAdminPwd}" --install-app erpnext || echo "Site may already exist"`,
              { key: "03-create-site" },
            ),
            ec2.InitCommand.shellCommand(
              `cd /opt/erpnext && docker compose exec -T backend bench use "${siteName}"`,
              { key: "04-use-site" },
            ),
          ]),
        },
      }),
      initOptions: {
        configSets: ["default"],
        timeout: cdk.Duration.minutes(30),
      },
    });

    // =====================================================================
    // ACM + Route53
    // =====================================================================

    let certificate: acm.ICertificate | undefined;
    let hostedZone: route53.IHostedZone | undefined;

    if (hasDomain) {
      if (externalDns) {
        // External DNS: ACM cert with manual DNS validation.
        // During deploy, CloudFormation will wait for certificate validation.
        // Check the ACM console for the CNAME records to add to your DNS provider.
        certificate = new acm.Certificate(this, "Cert", {
          domainName: fqdn!,
          validation: acm.CertificateValidation.fromDns(),
        });
      } else {
        // Route53-managed DNS: auto-create validation records
        hostedZone = route53.HostedZone.fromLookup(this, "HostedZone", {
          domainName: hostedZoneName!,
        });
        certificate = new acm.Certificate(this, "Cert", {
          domainName: fqdn!,
          validation: acm.CertificateValidation.fromDns(hostedZone),
        });
      }
    }

    // =====================================================================
    // Application Load Balancer
    // =====================================================================

    const alb = new elbv2.ApplicationLoadBalancer(this, "ALB", {
      vpc,
      internetFacing: true,
      securityGroup: albSg,
    });

    const targetGroup = new elbv2.ApplicationTargetGroup(this, "TG", {
      vpc,
      port: 8080,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [new elbv2_targets.InstanceTarget(instance, 8080)],
      healthCheck: {
        path: "/api/method/frappe.ping",
        port: "8080",
        healthyHttpCodes: "200",
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 5,
      },
    });

    if (hasDomain && certificate) {
      // HTTPS listener — open: false prevents adding 0.0.0.0/0 to SG
      alb.addListener("HTTPS", {
        port: 443,
        protocol: elbv2.ApplicationProtocol.HTTPS,
        certificates: [certificate],
        defaultTargetGroups: [targetGroup],
        open: false,
      });
      // HTTP → HTTPS redirect
      alb.addListener("HTTP", {
        port: 80,
        open: false,
        defaultAction: elbv2.ListenerAction.redirect({
          protocol: "HTTPS",
          port: "443",
          permanent: true,
        }),
      });
    } else {
      alb.addListener("HTTP", {
        port: 80,
        open: false,
        defaultTargetGroups: [targetGroup],
      });
    }

    // Route53 alias record (only when DNS is managed by Route53)
    if (hasDomain && hostedZone) {
      new route53.ARecord(this, "DnsRecord", {
        zone: hostedZone,
        recordName: domainPrefix,
        target: route53.RecordTarget.fromAlias(
          new route53_targets.LoadBalancerTarget(alb),
        ),
      });
    }

    // When using external DNS, output the ALB domain so operator can
    // create a CNAME record at their DNS provider.
    if (fqdn && externalDns) {
      new cdk.CfnOutput(this, "ExternalDnsTarget", {
        value: alb.loadBalancerDnsName,
        description: `Create a CNAME record: ${fqdn} → this value`,
      });
    }

    // =====================================================================
    // Internal ALB — for Lambda (VPC) → ERPNext connectivity
    // =====================================================================
    // Internet-facing ALBs resolve to public IPs, causing NAT hairpin routing
    // from private subnets. An internal ALB resolves to private IPs, so
    // Lambda → ALB traffic stays in the VPC with SG-to-SG matching.

    const internalAlbSg = new ec2.SecurityGroup(this, "InternalAlbSG", {
      vpc,
      description: "Internal ALB - VPC-only access to ERPNext",
    });
    // EC2 must accept traffic from internal ALB
    ec2Sg.addIngressRule(internalAlbSg, ec2.Port.tcp(8080), "Internal ALB to ERPNext");

    const internalAlb = new elbv2.ApplicationLoadBalancer(this, "InternalALB", {
      vpc,
      internetFacing: false,
      securityGroup: internalAlbSg,
    });

    // Reuse the same target group (same EC2 instance on port 8080)
    const internalTargetGroup = new elbv2.ApplicationTargetGroup(this, "InternalTG", {
      vpc,
      port: 8080,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [new elbv2_targets.InstanceTarget(instance, 8080)],
      healthCheck: {
        path: "/api/method/frappe.ping",
        port: "8080",
        healthyHttpCodes: "200",
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
      },
    });

    // Internal ALB needs HTTPS (adapter calls https://internal.<fqdn>)
    if (hasDomain && hostedZone) {
      const internalCert = new acm.Certificate(this, "InternalCert", {
        domainName: `internal.${fqdn!}`,
        validation: acm.CertificateValidation.fromDns(hostedZone),
      });
      internalAlb.addListener("InternalHTTPS", {
        port: 443,
        protocol: elbv2.ApplicationProtocol.HTTPS,
        certificates: [internalCert],
        defaultTargetGroups: [internalTargetGroup],
        open: false,
      });
    } else {
      internalAlb.addListener("InternalHTTP", {
        port: 80,
        open: false,
        defaultTargetGroups: [internalTargetGroup],
      });
    }

    // Private hosted zone: internal.<fqdn> → internal ALB (private IPs)
    const internalFqdn = fqdn ? `internal.${fqdn}` : undefined;
    if (internalFqdn) {
      // The zone covers the parent domain so internal.<fqdn> resolves
      const privateZone = new route53.PrivateHostedZone(this, "InternalZone", {
        zoneName: hostedZoneName!,
        vpc,
      });
      new route53.ARecord(this, "InternalDnsRecord", {
        zone: privateZone,
        recordName: `internal.${domainPrefix}`,
        target: route53.RecordTarget.fromAlias(
          new route53_targets.LoadBalancerTarget(internalAlb),
        ),
      });
    }

    // =====================================================================
    // Outputs
    // =====================================================================

    if (fqdn) {
      new cdk.CfnOutput(this, "ErpNextURL", {
        value: `https://${fqdn}`,
        exportName: "ErpNextURL",
      });
    }

    if (internalFqdn) {
      new cdk.CfnOutput(this, "ErpNextInternalURL", {
        value: `https://${internalFqdn}`,
        exportName: "ErpNextInternalURL",
      });
    }

    new cdk.CfnOutput(this, "InternalAlbSgId", {
      value: internalAlbSg.securityGroupId,
      exportName: "ErpNextInternalAlbSgId",
    });
    new cdk.CfnOutput(this, "AlbSecurityGroupId", {
      value: albSg.securityGroupId,
      exportName: "ErpNextAlbSgId",
    });
    new cdk.CfnOutput(this, "VpcId", {
      value: vpc.vpcId,
      exportName: "ErpNextVpcId",
    });
    new cdk.CfnOutput(this, "RdsEndpoint", { value: db.dbInstanceEndpointAddress });
    new cdk.CfnOutput(this, "RedisEndpoint", { value: `${redisAddr}:${redisPort}` });
    new cdk.CfnOutput(this, "InstanceId", { value: instance.instanceId });

    // =====================================================================
    // Tags
    // =====================================================================

    cdk.Tags.of(this).add("Project", "p2p-agentic-erp");
    cdk.Tags.of(this).add("Component", "erpnext");
    cdk.Tags.of(this).add("Environment", "dev");
  }
}
