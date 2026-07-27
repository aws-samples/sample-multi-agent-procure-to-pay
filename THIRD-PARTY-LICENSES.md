# Third-Party Licenses

This sample depends on the third-party software listed below. Each is used under
its own license; this file records attribution. Transitive dependencies are
governed by the licenses declared in the respective lockfiles
(`frontend/package-lock.json`, `infra/package-lock.json`) and Python requirements
files. Versions reflect the minimums declared in this repository; see the
lockfiles for exact resolved versions.

This project itself is licensed under MIT-0 (see [`LICENSE`](LICENSE)).

## Runtime services and container images

| Component | License | Project |
|-----------|---------|---------|
| ERPNext (`frappe/erpnext:v15` container image; system of record, used as an external service) | GPL-3.0 | https://github.com/frappe/erpnext |
| Frappe Framework (bundled in the ERPNext image) | MIT | https://github.com/frappe/frappe |
| MariaDB (ERPNext compose dependency) | GPL-2.0 | https://mariadb.org/ |
| Redis (ERPNext compose dependency) | RSALv2 / SSPLv1 | https://redis.io/ |
| Python base image `python:3.13-slim-bookworm` (Python: PSF-2.0; Debian base: mixed OSS) | PSF-2.0 / Debian | https://www.python.org/ , https://www.debian.org/ |

## Python (backend and utilities)

| Package | License | Project |
|---------|---------|---------|
| FastAPI | MIT | https://github.com/fastapi/fastapi |
| Uvicorn | BSD-3-Clause | https://github.com/encode/uvicorn |
| Mangum | MIT | https://github.com/jordaneremieff/mangum |
| Pydantic | MIT | https://github.com/pydantic/pydantic |
| pydantic-settings | MIT | https://github.com/pydantic/pydantic-settings |
| python-multipart | Apache-2.0 | https://github.com/Kludex/python-multipart |
| boto3 | Apache-2.0 | https://github.com/boto/boto3 |
| Strands Agents (`strands-agents`, `strands-agents-tools`) | Apache-2.0 | https://github.com/strands-agents/sdk-python |
| bedrock-agentcore | Apache-2.0 | https://github.com/aws/bedrock-agentcore-sdk-python |
| PyYAML | MIT | https://github.com/yaml/pyyaml |
| Requests | Apache-2.0 | https://github.com/psf/requests |
| Faker | MIT | https://github.com/joke2k/faker |
| python-dotenv | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| fpdf2 | LGPL-3.0 | https://github.com/py-pdf/fpdf2 |

### Python test-only dependencies

| Package | License | Project |
|---------|---------|---------|
| moto | Apache-2.0 | https://github.com/getmoto/moto |
| Hypothesis | MPL-2.0 | https://github.com/HypothesisWorks/hypothesis |

## Frontend (React SPA)

| Package | License | Project |
|---------|---------|---------|
| React, React-DOM | MIT | https://github.com/facebook/react |
| React Router (`react-router-dom`) | MIT | https://github.com/remix-run/react-router |
| AWS Amplify (`aws-amplify`) | Apache-2.0 | https://github.com/aws-amplify/amplify-js |
| Radix UI (`@radix-ui/react-*`) | MIT | https://github.com/radix-ui/primitives |
| lucide-react | ISC | https://github.com/lucide-icons/lucide |
| Motion (`motion`) | MIT | https://github.com/motiondivision/motion |
| Recharts | MIT | https://github.com/recharts/recharts |
| i18next | MIT | https://github.com/i18next/i18next |
| react-i18next | MIT | https://github.com/i18next/react-i18next |
| clsx | MIT | https://github.com/lukeed/clsx |
| tailwind-merge | MIT | https://github.com/dcastil/tailwind-merge |
| class-variance-authority | Apache-2.0 | https://github.com/joe-bell/cva |
| Inter typeface (loaded via Google Fonts) | SIL OFL 1.1 | https://github.com/rsms/inter |

### Vendored UI components

The primitives in `frontend/src/components/ui/` are adapted from **shadcn/ui**,
copied into this repository per its intended usage model.

| Component set | License | Project |
|---------------|---------|---------|
| shadcn/ui | MIT | https://github.com/shadcn-ui/ui |

### Frontend build tooling (dev dependencies)

| Package | License | Project |
|---------|---------|---------|
| Vite (`vite`, `@vitejs/plugin-react`) | MIT | https://github.com/vitejs/vite |
| TypeScript | Apache-2.0 | https://github.com/microsoft/TypeScript |
| Tailwind CSS (`tailwindcss`, `@tailwindcss/vite`) | MIT | https://github.com/tailwindlabs/tailwindcss |
| ESLint (`eslint`, `@eslint/js`, `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`) | MIT | https://github.com/eslint/eslint |
| globals | MIT | https://github.com/sindresorhus/globals |

## Infrastructure (AWS CDK)

| Package | License | Project |
|---------|---------|---------|
| AWS CDK (`aws-cdk-lib`, `aws-cdk`, `@aws-cdk/aws-bedrock-agentcore-alpha`) | Apache-2.0 | https://github.com/aws/aws-cdk |
| constructs | Apache-2.0 | https://github.com/aws/constructs |

## Development tooling (not distributed in the application)

| Tool | License | Project |
|------|---------|---------|
| pre-commit | MIT | https://github.com/pre-commit/pre-commit |
| gitleaks | MIT | https://github.com/gitleaks/gitleaks |
| Bandit | Apache-2.0 | https://github.com/PyCQA/bandit |
| Semgrep | LGPL-2.1 | https://github.com/semgrep/semgrep |
| Checkov | Apache-2.0 | https://github.com/bridgecrewio/checkov |
