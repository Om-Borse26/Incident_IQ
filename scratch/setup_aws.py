import boto3
import urllib.request
import json
import time

import os

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = "ap-south-1"

print("Initializing boto3 clients...")
session = boto3.Session(
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)
ec2 = session.client('ec2')
ecr = session.client('ecr')
sqs = session.client('sqs')

print("\n--- 1. Creating Key Pair ---")
try:
    key_pair = ec2.create_key_pair(KeyName='incidentiq-key')
    with open('incidentiq-key.pem', 'w') as f:
        f.write(key_pair['KeyMaterial'])
    print("[SUCCESS] Created key pair and saved incidentiq-key.pem locally")
except ec2.exceptions.ClientError as e:
    if 'InvalidKeyPair.Duplicate' in str(e):
        print("[INFO] Key pair 'incidentiq-key' already exists")
    else:
        print(f"[ERROR] Error creating key pair: {e}")

print("\n--- 2. Creating ECR Repository ---")
try:
    ecr.create_repository(repositoryName='incidentiq')
    print("[SUCCESS] Created ECR repository 'incidentiq'")
except ecr.exceptions.RepositoryAlreadyExistsException:
    print("[INFO] ECR repository 'incidentiq' already exists")

print("\n--- 3. Creating Security Group ---")
my_ip = urllib.request.urlopen('https://checkip.amazonaws.com').read().decode('utf-8').strip()
print(f"Detected local IP: {my_ip}")
sg_id = None
try:
    vpcs = ec2.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])
    vpc_id = vpcs['Vpcs'][0]['VpcId']
    
    sg = ec2.create_security_group(
        GroupName='incidentiq-sg',
        Description='IncidentIQ backend',
        VpcId=vpc_id
    )
    sg_id = sg['GroupId']
    
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': f"{my_ip}/32"}]},
            {'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
            {'IpProtocol': 'tcp', 'FromPort': 443, 'ToPort': 443, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
        ]
    )
    print(f"[SUCCESS] Created security group {sg_id} (SSH restricted to {my_ip})")
except ec2.exceptions.ClientError as e:
    if 'InvalidGroup.Duplicate' in str(e):
        print("[INFO] Security group 'incidentiq-sg' already exists")
        sgs = ec2.describe_security_groups(GroupNames=['incidentiq-sg'])
        sg_id = sgs['SecurityGroups'][0]['GroupId']
    else:
        print(f"[ERROR] Error creating security group: {e}")

print("\n--- 4. Launching EC2 Instance ---")
try:
    # Amazon Linux 2023 AMI in ap-south-1
    ami_id = 'ami-0f58b397bc5c1f2e8'
    
    # We will pass user data to automatically install docker so we don't have to SSH immediately
    user_data = '''#!/bin/bash
yum update -y
yum install docker -y
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user
mkdir -p /home/ec2-user/data
chmod 777 /home/ec2-user/data
'''
    
    instances = ec2.run_instances(
        ImageId=ami_id,
        InstanceType='t3.micro',
        KeyName='incidentiq-key',
        SecurityGroupIds=[sg_id],
        MinCount=1,
        MaxCount=1,
        UserData=user_data,
        TagSpecifications=[{'ResourceType': 'instance', 'Tags': [{'Key': 'Name', 'Value': 'incidentiq'}]}]
    )
    instance_id = instances['Instances'][0]['InstanceId']
    print(f"[SUCCESS] Launched EC2 instance {instance_id}")
    
    print("Waiting for instance to initialize before associating Elastic IP...")
    time.sleep(10)
    
    alloc = ec2.allocate_address(Domain='vpc')
    alloc_id = alloc['AllocationId']
    public_ip = alloc['PublicIp']
    print(f"[SUCCESS] Allocated Elastic IP: {public_ip}")
    
    ec2.associate_address(InstanceId=instance_id, AllocationId=alloc_id)
    print(f"[SUCCESS] Associated Elastic IP {public_ip} to instance {instance_id}")
    print(f"\n[URL] Your sslip.io URL will be: https://{public_ip.replace('.', '-')}.sslip.io")
except Exception as e:
    print(f"[ERROR] Error launching EC2: {e}")

print("\n--- 5. Creating SQS Queues ---")
try:
    dlq = sqs.create_queue(QueueName='incident-ingested-dlq')
    dlq_url = dlq['QueueUrl']
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=['QueueArn'])['Attributes']['QueueArn']
    print(f"[SUCCESS] Created DLQ: {dlq_url}")
    
    main_queue = sqs.create_queue(
        QueueName='incident-ingested-queue',
        Attributes={
            'VisibilityTimeout': '300',
            'RedrivePolicy': json.dumps({
                'deadLetterTargetArn': dlq_arn,
                'maxReceiveCount': 5
            })
        }
    )
    print(f"[SUCCESS] Created Main Queue: {main_queue['QueueUrl']}")
except Exception as e:
    print(f"[ERROR] Error creating SQS queues: {e}")

print("\n--- [DONE] Phase A Complete! ---")
