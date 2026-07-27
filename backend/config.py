# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Application settings loaded from environment variables and .env file.

Centralizes AWS, Bedrock, Cognito, and DynamoDB configuration using Pydantic.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    aws_region: str = "us-east-1"
    dynamodb_table_prefix: str = "p2p"
    s3_bucket: str = "p2p-documents"
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-6"
    bedrock_guardrail_id: str = ""
    bedrock_guardrail_version: str = ""
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
