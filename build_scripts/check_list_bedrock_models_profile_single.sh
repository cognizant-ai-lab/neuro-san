#!/bin/bash
  
# Script set up needed to do a quick test connection using AWS CLI to list all Bedrocks on this credential.

# Install AWS CLI prerequisites
apt-get install -y unzip zip

# Install AWS CLI v2 (which includes the Bedrock commands)
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip awscliv2.zip
./aws/install
aws --version
  
# List Bedrock foundation models for single profile only
aws bedrock list-foundation-models
